"""Unipile inbound-sync worker — poll-based reply detection (the reliable path).

Unipile push webhooks proved unreliable for LinkedIn: a real reply DID fire the
``message_received`` webhook, but the payload shape did not carry a resolvable
sender, so the contact never matched and no lead woke — the sequence would have
kept sending follow-ups after a human replied (exactly what gets an account
flagged). Rather than trust push, this worker POLLS Unipile's authoritative
thread state on an interval and fires the same SM-8 wake the webhook would have.

Detection is exact, not heuristic:
  * a lead that has sent a DM carries ``custom_fields.chat_id`` (the DM handler
    stamps it so follow-ups thread onto the same conversation);
  * for every lead parked ``waiting`` with a chat_id, read the last few messages;
  * Unipile marks each message ``is_sender`` (1 = our seat sent it, 0 = inbound).
    If the NEWEST message is inbound (is_sender == 0) and we have not processed
    that message id yet, the contact has replied since our last send → halt.

Idempotency: the newest inbound message id is stamped on the lead
(``custom_fields.reply_seen_msg_id``) before the wake, and a per-cycle guard
fires ``process_reply`` at most once per contact — so one reply produces one
``message.received`` and one wake even across overlapping cycles. Once woken, the
lead leaves ``waiting`` and is no longer polled.

Runs as its own container (mirrors objective_worker / ai_jobs_worker); one
``UnipileClient`` per workspace per cycle, bounded Unipile concurrency.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

from app.config import settings
from app.db import (
    assert_rls_enforcing_role,
    close_pool,
    execute,
    fetch_all,
    init_pool,
    system_scope,
)
from app.services import bus, event_resume, inbound_reply
from app.services.unipile_client import UnipileClient, UnipileError, UnipileNotConfigured

log = logging.getLogger("unipile_sync")

# How often to sweep in-flight threads for new inbound messages.
POLL_INTERVAL_S = int(os.getenv("REPLY_POLL_INTERVAL_S", "60"))
# How often to re-check parked invites for acceptance. Slower than replies: a
# lead can sit at invite_accepted for days, so a tight cadence would fire an
# enormous number of profile reads per lead. 5 min is ample for a connection.
ACCEPT_INTERVAL_S = int(os.getenv("ACCEPT_POLL_INTERVAL_S", "300"))
# Cap concurrent Unipile reads per workspace (the client already backs off 429s).
_MAX_CONCURRENCY = int(os.getenv("REPLY_POLL_CONCURRENCY", "5"))
# Only the last few messages matter — we only ever inspect the newest.
_MESSAGES_LIMIT = 3
_INVITE_NODE = "event.invite_accepted"


async def _waiting_leads_with_chats() -> list[dict]:
    """Every lead parked 'waiting' that has an open chat thread, across all
    workspaces (system-scoped read; each is re-scoped by workspace when acted on).

    ``chat_id`` is the LinkedIn/WhatsApp thread key stamped by the DM handler.
    A lead with no chat has sent no message, so there is nothing to reply to.
    """
    async with system_scope():
        return list(
            await fetch_all(
                """
                SELECT l.id,
                       l.workspace_id,
                       l.contact_id,
                       l.custom_fields->>'chat_id'            AS chat_id,
                       l.custom_fields->>'reply_seen_msg_id'  AS reply_seen
                FROM omni_leads l
                WHERE l.status = 'waiting'
                  AND l.contact_id IS NOT NULL
                  AND COALESCE(l.custom_fields->>'chat_id', '') <> ''
                """
            )
        )


async def _stamp_reply_seen(ws: str, lead_id: str, msg_id: str) -> None:
    """Record the processed inbound message id on the lead so a subsequent cycle
    (before the wake un-parks it) does not re-fire on the same reply."""
    async with system_scope():
        await execute(
            "UPDATE omni_leads SET custom_fields = COALESCE(custom_fields, '{}'::jsonb) || $1::jsonb, "
            "updated_at = NOW() WHERE id = $2 AND workspace_id = $3",
            json.dumps({"reply_seen_msg_id": msg_id}), lead_id, ws,
        )


async def _check_lead(
    client: UnipileClient,
    ws: str,
    lead: dict,
    *,
    sem: asyncio.Semaphore,
    lock: asyncio.Lock,
    woken_contacts: set[str],
) -> int:
    """Inspect one lead's thread; fire the reply-halt if the newest message is a
    fresh inbound. Returns the number of leads woken (0 or ≥1)."""
    chat_id = lead["chat_id"]
    async with sem:
        try:
            resp = await client.list_chat_messages(chat_id, limit=_MESSAGES_LIMIT)
        except UnipileError as e:
            log.warning("[unipile_sync] chat %s read failed: %s", chat_id, e)
            return 0
    items = resp.get("items") if isinstance(resp, dict) else None
    if not items:
        return 0
    newest = items[0]
    # is_sender: 1 = our seat sent it, 0 = inbound. Require an EXPLICIT inbound
    # flag — never guess, and never treat our own send as a reply.
    if newest.get("is_sender") != 0:
        return 0
    msg_id = newest.get("id")
    if not msg_id or str(msg_id) == (lead.get("reply_seen") or ""):
        return 0  # already processed this reply

    contact_id = str(lead["contact_id"])
    # At-most-once per contact per cycle (a contact can have >1 waiting lead).
    async with lock:
        if contact_id in woken_contacts:
            await _stamp_reply_seen(ws, str(lead["id"]), str(msg_id))
            return 0
        woken_contacts.add(contact_id)

    # Stamp the high-water mark BEFORE the wake so an overlapping cycle skips it.
    await _stamp_reply_seen(ws, str(lead["id"]), str(msg_id))
    text = newest.get("text") or ""
    res = await inbound_reply.process_reply(
        ws, contact_id, text, channel="linkedin", source_message_id=str(msg_id)
    )
    log.info(
        "[unipile_sync] reply detected lead=%s contact=%s intent=%s woke=%s",
        lead["id"], contact_id, res.get("intent"), res.get("woke_leads"),
    )
    return int(res.get("woke_leads") or 0)


async def run_once() -> None:
    """One sweep: poll every in-flight thread and halt any that got a reply."""
    leads = await _waiting_leads_with_chats()
    if not leads:
        return
    by_ws: dict[str, list[dict]] = {}
    for lead in leads:
        by_ws.setdefault(str(lead["workspace_id"]), []).append(lead)

    total_woken = 0
    for ws, ws_leads in by_ws.items():
        try:
            client = await UnipileClient.for_workspace(ws)
        except UnipileNotConfigured:
            continue  # workspace has no Unipile connection — nothing to poll
        except UnipileError as e:
            log.warning("[unipile_sync] client init failed for ws %s: %s", ws, e)
            continue
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        lock = asyncio.Lock()
        woken_contacts: set[str] = set()
        results = await asyncio.gather(
            *(
                _check_lead(client, ws, lead, sem=sem, lock=lock, woken_contacts=woken_contacts)
                for lead in ws_leads
            ),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                log.exception("[unipile_sync] lead check errored", exc_info=r)
            else:
                total_woken += r
    if total_woken:
        log.info("[unipile_sync] swept %d thread(s); woke %d lead(s)", len(leads), total_woken)


# ── Acceptance sweep — advance leads parked at event.invite_accepted ──────────


def _public_id(url: str | None) -> str | None:
    """The slug after /in/ (mirrors _public_id_from_linkedin_url in webhooks_in
    and public_id_from_linkedin_url in unipile.rs)."""
    if not url:
        return None
    slug = url.strip().rstrip("/").split("/in/")[-1].strip().lower()
    return slug or None


async def _invite_leads() -> list[dict]:
    """Every lead parked 'waiting' at event.invite_accepted that we can re-check
    — it must carry the inviting seat (custom_fields.invite_account_id) and a
    linkedin_url to resolve the member. Legacy invites (pre invite_account_id)
    are skipped here; they still rely on the push webhook."""
    async with system_scope():
        return list(
            await fetch_all(
                """
                SELECT l.id,
                       l.workspace_id,
                       l.custom_fields->>'invite_account_id' AS account_id,
                       c.linkedin_url
                FROM omni_leads l
                JOIN omni_workflow_nodes n ON n.id = l.current_node_id
                JOIN omni_contacts c ON c.id = l.contact_id
                WHERE l.status = 'waiting'
                  AND n.node_type = $1
                  AND COALESCE(l.custom_fields->>'invite_account_id', '') <> ''
                  AND COALESCE(c.linkedin_url, '') <> ''
                """,
                _INVITE_NODE,
            )
        )


async def _check_acceptance(
    client: UnipileClient, ws: str, lead: dict, *, sem: asyncio.Semaphore
) -> int:
    """Re-check one parked invite through the inviting seat; resume the lead when
    the recipient is now a first-degree connection. Returns 1 if resumed."""
    public_id = _public_id(lead["linkedin_url"])
    if not public_id:
        return 0
    async with sem:
        try:
            prof = await client.member_profile(lead["account_id"], public_id)
        except UnipileError as e:
            log.warning("[unipile_sync] profile read failed for %s: %s", public_id, e)
            return 0
    if not isinstance(prof, dict):
        return 0
    # Accept either signal Unipile exposes; require an explicit positive (never
    # guess a missing field into an acceptance).
    accepted = prof.get("network_distance") == "FIRST_DEGREE" or prof.get("is_relationship") is True
    if not accepted:
        return 0
    resumed = await event_resume.resume_on_signal(ws, str(lead["id"]), "invite_accepted")
    if resumed:
        log.info("[unipile_sync] invite accepted (polled) lead=%s public_id=%s", lead["id"], public_id)
    return 1 if resumed else 0


async def run_acceptance_once() -> None:
    """One acceptance sweep: re-check every parked invite and advance the ones
    that have connected."""
    leads = await _invite_leads()
    if not leads:
        return
    by_ws: dict[str, list[dict]] = {}
    for lead in leads:
        by_ws.setdefault(str(lead["workspace_id"]), []).append(lead)
    total = 0
    for ws, ws_leads in by_ws.items():
        try:
            client = await UnipileClient.for_workspace(ws)
        except UnipileNotConfigured:
            continue
        except UnipileError as e:
            log.warning("[unipile_sync] client init failed for ws %s: %s", ws, e)
            continue
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        results = await asyncio.gather(
            *(_check_acceptance(client, ws, lead, sem=sem) for lead in ws_leads),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                log.exception("[unipile_sync] acceptance check errored", exc_info=r)
            else:
                total += r
    if total:
        log.info("[unipile_sync] acceptance sweep: advanced %d lead(s)", total)


async def _poll_loop(stop: asyncio.Event) -> None:
    """Drive two cadences off one loop: replies every POLL_INTERVAL_S, acceptance
    every ACCEPT_INTERVAL_S (throttled — parked invites live for days)."""
    last_accept = 0.0
    while not stop.is_set():
        try:
            await run_once()
        except Exception:  # noqa: BLE001
            # One bad sweep must never kill the loop.
            log.exception("[unipile_sync] reply sweep errored; continuing")
        now = asyncio.get_running_loop().time()
        if now - last_accept >= ACCEPT_INTERVAL_S:
            last_accept = now
            try:
                await run_acceptance_once()
            except Exception:  # noqa: BLE001
                log.exception("[unipile_sync] acceptance sweep errored; continuing")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_S)
        except TimeoutError:
            pass


async def run() -> None:
    await init_pool(settings.database_url)
    await assert_rls_enforcing_role()
    await bus.init_producer()  # process_reply publishes events + transitions

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    log.info(
        "[unipile_sync] replies every %ds, acceptance every %ds",
        POLL_INTERVAL_S, ACCEPT_INTERVAL_S,
    )
    try:
        await _poll_loop(stop)
    finally:
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
