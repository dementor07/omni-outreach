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
from app.services import bus, inbound_reply
from app.services.unipile_client import UnipileClient, UnipileError, UnipileNotConfigured

log = logging.getLogger("unipile_sync")

# How often to sweep in-flight threads for new inbound messages.
POLL_INTERVAL_S = int(os.getenv("REPLY_POLL_INTERVAL_S", "60"))
# Cap concurrent Unipile reads per workspace (the client already backs off 429s).
_MAX_CONCURRENCY = int(os.getenv("REPLY_POLL_CONCURRENCY", "5"))
# Only the last few messages matter — we only ever inspect the newest.
_MESSAGES_LIMIT = 3


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


async def _poll_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await run_once()
        except Exception:  # noqa: BLE001
            # One bad sweep must never kill the loop.
            log.exception("[unipile_sync] sweep errored; continuing")
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

    log.info("[unipile_sync] polling in-flight threads every %ds", POLL_INTERVAL_S)
    try:
        await _poll_loop(stop)
    finally:
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
