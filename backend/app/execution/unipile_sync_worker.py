"""Unipile inbound-sync worker — poll-based reply + acceptance detection.

Unipile push webhooks proved unreliable for LinkedIn, so we poll. But polling
must be CHEAP (Unipile is billed per call) and QUIET (LinkedIn flags accounts
that "overdo a mechanism" — profile views especially). So both sweeps are
**O(seats), not O(leads)**, and neither views a profile on a timer:

  * REPLY  — one ``list_chats`` per seat surfaces which threads have unread
             inbound (``unread_count``). We only open the handful of threads that
             both changed AND belong to an in-flight lead, confirm the newest
             message is inbound, and halt. (The hard guarantee is the pre-send
             reply gate in the transition worker; this just ends the wait early.)
  * ACCEPT — one ``list_relations`` per seat lists everyone who accepted (each
             carries member_id + public_identifier). We match those against leads
             parked at event.invite_accepted and advance them. NO per-lead
             ``member_profile`` (profile view) — that was the real ban vector.

Cadences are deliberately slow and jittered (a follow-up is days away; an invite
takes hours/days to accept), so LinkedIn/Unipile see a human trickle, not a scan.
Runs as its own container; one ``UnipileClient`` per workspace per cycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
from collections import defaultdict

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

# Reply threads change fast but a follow-up is days out — minutes of latency are
# harmless (the pre-send gate is the hard stop). Acceptance is slower still.
REPLY_INTERVAL_S = int(os.getenv("REPLY_POLL_INTERVAL_S", "180"))
ACCEPT_INTERVAL_S = int(os.getenv("ACCEPT_POLL_INTERVAL_S", "1800"))
_JITTER_PCT = 0.25  # ±25% so the cadence isn't clockwork
_CHATS_PER_SEAT = int(os.getenv("REPLY_CHATS_PER_SEAT", "40"))
_RELATIONS_PER_SEAT = int(os.getenv("ACCEPT_RELATIONS_PER_SEAT", "50"))
_INVITE_NODE = "event.invite_accepted"


def _jittered(base: float) -> float:
    return max(30.0, base * (1.0 + random.uniform(-_JITTER_PCT, _JITTER_PCT)))


def _public_id(url: str | None) -> str | None:
    """The slug after /in/ (mirrors public_id_from_linkedin_url)."""
    if not url:
        return None
    slug = url.strip().rstrip("/").split("/in/")[-1].strip().lower()
    return slug or None


def _seat_ids(accounts) -> list[str]:
    """Account ids from a list_accounts response (shape-tolerant)."""
    items = accounts.get("items") if isinstance(accounts, dict) else accounts
    ids: list[str] = []
    for a in items or []:
        aid = a.get("id") if isinstance(a, dict) else None
        if aid:
            ids.append(str(aid))
    return ids


# ── Reply sweep — one list_chats per seat, only open changed campaign threads ──


async def _process_reply_for_lead(client: UnipileClient, ws: str, lead: dict) -> int:
    """Confirm the lead's thread newest is inbound and halt. Only called for a
    lead whose chat already showed unread — so this is a tiny, bounded read."""
    chat_id = lead["chat_id"]
    try:
        resp = await client.list_chat_messages(str(chat_id), limit=2)
    except UnipileError as e:
        log.warning("[unipile_sync] chat %s read failed: %s", chat_id, e)
        return 0
    items = resp.get("items") if isinstance(resp, dict) else None
    if not items:
        return 0
    newest = items[0]
    if newest.get("is_sender") != 0:  # 1=our send, 0=inbound; explicit only
        return 0
    msg_id = newest.get("id")
    if not msg_id or str(msg_id) == (lead.get("reply_seen") or ""):
        return 0
    async with system_scope():
        await execute(
            "UPDATE omni_leads SET custom_fields = COALESCE(custom_fields, '{}'::jsonb) || $1::jsonb, "
            "updated_at = NOW() WHERE id = $2 AND workspace_id = $3",
            json.dumps(
                {
                    "reply_seen_msg_id": str(msg_id),
                    **({"chat_seen_ts": lead["_chat_ts"]} if lead.get("_chat_ts") else {}),
                }
            ),
            str(lead["id"]),
            ws,
        )
    res = await inbound_reply.process_reply(
        ws, str(lead["contact_id"]), newest.get("text") or "",
        channel="linkedin", source_message_id=str(msg_id),
    )
    log.info(
        "[unipile_sync] reply detected lead=%s intent=%s woke=%s",
        lead["id"], res.get("intent"), res.get("woke_leads"),
    )
    return int(res.get("woke_leads") or 0)


async def _link_chat_to_lead(ws: str, chat: dict) -> int:
    """INBOX-DISCOVER-001: attach an unlinked Unipile chat to the lead it belongs to.

    ``chat_id`` was only ever written when OUR outbound DM opened a chat, so a
    prospect who replied after accepting an invite had a real conversation that
    the inbox could not see: 249 chats existed across the seats, 85 of them
    carried an inbound message, and only 14 were linked.

    The chat list response already includes ``attendee_provider_id``, which is
    the same LinkedIn member id contacts store as ``custom_fields.provider_id``,
    so the match needs no extra API call and no profile view.
    """
    attendee = str(chat.get("attendee_provider_id") or "")
    chat_id = str(chat.get("id") or "")
    if not attendee or not chat_id:
        return 0
    async with system_scope():
        rows = await fetch_all(
            """
            UPDATE omni_leads l
               SET custom_fields = COALESCE(l.custom_fields, '{}'::jsonb)
                                   || jsonb_build_object('chat_id', $3::text),
                   updated_at = NOW()
              FROM omni_contacts c
             WHERE c.id = l.contact_id
               AND l.workspace_id = $1
               AND c.custom_fields->>'provider_id' = $2
               AND COALESCE(l.custom_fields->>'chat_id', '') = ''
            RETURNING l.id
            """,
            ws,
            attendee,
            chat_id,
        )
    return len(rows)


async def run_reply_sweep() -> None:
    async with system_scope():
        leads = await fetch_all(
            """
            SELECT DISTINCT ON (l.custom_fields->>'chat_id')
                   l.id, l.workspace_id, l.contact_id,
                   l.custom_fields->>'chat_id'           AS chat_id,
                   l.custom_fields->>'reply_seen_msg_id' AS reply_seen,
                   l.custom_fields->>'chat_seen_ts'      AS chat_seen_ts
            FROM omni_leads l
            WHERE l.contact_id IS NOT NULL
              AND COALESCE(l.custom_fields->>'chat_id', '') <> ''
            -- INBOX-REPLY-001: NOT restricted to status='waiting'. A lead whose
            -- sequence already completed can still be replied to, and that reply
            -- has to reach the inbox. process_reply is idempotent (uuid5 on the
            -- provider message id) and only wakes leads that are actually parked
            -- on a reply gate, so a finished lead is recorded, never resurrected.
            ORDER BY l.custom_fields->>'chat_id', l.updated_at DESC
            """
        )
    if not leads:
        return
    # workspace -> {chat_id: lead}. The chat_id map is our "care set": we only
    # ever act on threads that belong to an in-flight lead.
    by_ws: dict[str, dict[str, dict]] = defaultdict(dict)
    for lead in leads:
        by_ws[str(lead["workspace_id"])][str(lead["chat_id"])] = lead

    total_woken = 0
    for ws, chat_map in by_ws.items():
        try:
            client = await UnipileClient.for_workspace(ws)
            seats = _seat_ids(await client.list_accounts())
        except (UnipileNotConfigured, UnipileError) as e:
            log.warning("[unipile_sync] reply sweep skip ws %s: %s", ws, e)
            continue
        care = set(chat_map)
        hits: list[dict] = []
        discovered = 0
        for seat in seats:
            try:
                chats = await client.list_chats(seat, limit=_CHATS_PER_SEAT)
            except UnipileError as e:
                log.warning("[unipile_sync] list_chats(%s) failed: %s", seat, e)
                continue
            for chat in (chats.get("items") if isinstance(chats, dict) else None) or []:
                cid = str(chat.get("id") or "")
                if cid not in care:
                    # INBOX-DISCOVER-001: a chat we have never linked to a lead.
                    # The chat list already carries attendee_provider_id, so the
                    # match costs no extra API call.
                    discovered += await _link_chat_to_lead(ws, chat)
                    continue
                lead = chat_map[cid]
                stamp = str(chat.get("timestamp") or "")
                moved = bool(stamp) and stamp != (lead.get("chat_seen_ts") or "")
                if int(chat.get("unread_count") or 0) > 0 or moved:
                    lead["_chat_ts"] = stamp
                    hits.append(lead)
        if discovered:
            log.info("[unipile_sync] linked %d previously untracked chat(s)", discovered)
        for lead in hits:
            total_woken += await _process_reply_for_lead(client, ws, lead)
    if total_woken:
        log.info("[unipile_sync] reply sweep woke %d lead(s)", total_woken)


# ── Acceptance sweep — one list_relations per inviting seat, no profile views ──


async def _parked_invites() -> list[dict]:
    """Leads waiting at event.invite_accepted that carry the inviting seat + an
    identity to match a relation against."""
    async with system_scope():
        return list(
            await fetch_all(
                """
                SELECT l.id, l.workspace_id,
                       l.custom_fields->>'invite_account_id' AS account_id,
                       l.custom_fields->>'provider_id'       AS provider_id,
                       c.linkedin_url
                FROM omni_leads l
                JOIN omni_workflow_nodes n ON n.id = l.current_node_id
                JOIN omni_contacts c ON c.id = l.contact_id
                WHERE l.status = 'waiting'
                  AND n.node_type = $1
                  AND COALESCE(l.custom_fields->>'invite_account_id', '') <> ''
                """,
                _INVITE_NODE,
            )
        )


def _relation_matches(provider_id: str | None, linkedin_url: str | None, connected: set[str]) -> bool:
    """True when a parked invite's identity appears in a seat's connections set —
    by the provider_id we stamped at invite, or the contact's URL slug."""
    pid = (provider_id or "").strip()
    slug = _public_id(linkedin_url) or ""
    return bool((pid and pid in connected) or (slug and slug in connected))


async def _relations_id_set(client: UnipileClient, seat: str) -> set[str]:
    """member_ids + public_identifiers of a seat's recent connections — the set a
    parked invite must appear in to count as accepted. One call, no profile view."""
    try:
        resp = await client.list_relations(seat, limit=_RELATIONS_PER_SEAT)
    except UnipileError as e:
        log.warning("[unipile_sync] list_relations(%s) failed: %s", seat, e)
        return set()
    ids: set[str] = set()
    for r in (resp.get("items") if isinstance(resp, dict) else None) or []:
        if r.get("member_id"):
            ids.add(str(r["member_id"]))
        if r.get("public_identifier"):
            ids.add(str(r["public_identifier"]).lower())
    return ids


async def run_acceptance_sweep() -> None:
    leads = await _parked_invites()
    if not leads:
        return
    # (workspace, inviting seat) -> leads. We only query seats that actually have
    # a pending invite, so the call count is bounded by seats-with-pending-invites.
    by_seat: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for lead in leads:
        by_seat[(str(lead["workspace_id"]), str(lead["account_id"]))].append(lead)

    clients: dict[str, UnipileClient] = {}
    advanced = 0
    for (ws, seat), seat_leads in by_seat.items():
        try:
            client = clients.get(ws) or await UnipileClient.for_workspace(ws)
            clients[ws] = client
        except (UnipileNotConfigured, UnipileError) as e:
            log.warning("[unipile_sync] acceptance skip ws %s: %s", ws, e)
            continue
        connected = await _relations_id_set(client, seat)
        if not connected:
            continue
        for lead in seat_leads:
            if _relation_matches(lead.get("provider_id"), lead.get("linkedin_url"), connected):
                if await event_resume.resume_on_signal(ws, str(lead["id"]), "invite_accepted"):
                    advanced += 1
                    log.info("[unipile_sync] invite accepted (relations) lead=%s", lead["id"])
    if advanced:
        log.info("[unipile_sync] acceptance sweep advanced %d lead(s)", advanced)


async def _poll_loop(stop: asyncio.Event) -> None:
    """Replies every ~REPLY_INTERVAL_S, acceptance every ~ACCEPT_INTERVAL_S, both
    jittered. Acceptance runs on the first tick then on its slower cadence."""
    last_accept = 0.0
    while not stop.is_set():
        try:
            await run_reply_sweep()
        except Exception:  # noqa: BLE001
            log.exception("[unipile_sync] reply sweep errored; continuing")
        now = asyncio.get_running_loop().time()
        if now - last_accept >= ACCEPT_INTERVAL_S:
            last_accept = now
            try:
                await run_acceptance_sweep()
            except Exception:  # noqa: BLE001
                log.exception("[unipile_sync] acceptance sweep errored; continuing")
        try:
            await asyncio.wait_for(stop.wait(), timeout=_jittered(REPLY_INTERVAL_S))
        except TimeoutError:
            pass


async def run() -> None:
    await init_pool(settings.database_url)
    await assert_rls_enforcing_role()
    await bus.init_producer()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    log.info(
        "[unipile_sync] O(seats) sweeps — replies ~%ds, acceptance ~%ds (jittered, no profile views)",
        REPLY_INTERVAL_S, ACCEPT_INTERVAL_S,
    )
    try:
        await _poll_loop(stop)
    finally:
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
