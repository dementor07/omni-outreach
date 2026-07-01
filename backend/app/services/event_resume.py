"""Resume leads parked at event.* nodes when the awaited signal arrives.

EVENT-PARK-001 fix. The ``event.email_opened`` / ``event.link_clicked`` /
``event.invite_accepted`` nodes park a lead (status='waiting') to await an
external signal. They used to emit ``wait.requested`` — an event with NO
consumer and NO timeout — so the lead stranded forever.

The working park→resume contract (see routers/approvals.py:resolve_approval and
routers/webhooks_in.py) is: emit a ``transition`` onto ``TRANSITIONS_TOPIC`` off
the parked node on the awaited handle; the transition worker un-parks the lead
and advances it. This module is the bridge that turns the real signal —
an open/click pixel hit (routers/tracking.py) or a Unipile invite-accepted
webhook (routers/webhooks_in.py) — into that transition.

Each signal maps to exactly one (node_type, success_handle). We resume a lead
ONLY when it is currently parked (status='waiting') at the matching node type,
so a stray signal for a lead that isn't waiting on it is a safe no-op (e.g. an
open pixel firing for a lead that already advanced past the wait node).
"""

from __future__ import annotations

import logging

from app.db import fetch_one, system_scope
from app.services import bus

log = logging.getLogger(__name__)

# signal kind -> (node_type the lead must be parked at, handle to fire on arrival)
_SIGNAL_RESUME: dict[str, tuple[str, str]] = {
    "email_opened": ("event.email_opened", "opened"),
    "link_clicked": ("event.link_clicked", "clicked"),
    "invite_accepted": ("event.invite_accepted", "accepted"),
}


async def resume_parked_node(
    workspace_id: str,
    lead_id: str,
    node_id: str,
    *,
    handle: str = "resumed",
    correlation_id: str | None = None,
) -> bool:
    """Resume a lead parked at a SPECIFIC node (by node_id), firing ``handle``.

    Used by the n8n callback (channel.n8n wait_for_callback): the signed token
    already identifies the exact parked node, so — unlike ``resume_on_signal``,
    which matches by node TYPE — we resume by node id. The lead must currently be
    parked ('waiting') at that node; otherwise it's a safe no-op (already
    advanced / timed out / gone). Never raises — a callback's public ack must not
    break on a resume failure."""
    try:
        async with system_scope():
            row = await fetch_one(
                """
                SELECT current_node_id
                FROM omni_leads
                WHERE id = $1 AND workspace_id = $2
                  AND status = 'waiting' AND current_node_id = $3
                """,
                lead_id,
                workspace_id,
                node_id,
            )
        if not row:
            return False
        transition = {
            "lead_id": str(lead_id),
            "source_node_id": str(node_id),
            "handle": handle,
            "event_type": "transition",
            "metadata": {
                "workspace_id": workspace_id,
                "correlation_id": correlation_id,
                "resume_signal": "n8n_callback",
            },
        }
        if bus._producer is None:  # type: ignore[attr-defined]
            log.warning("[event-resume] bus producer not ready; cannot resume lead %s at node %s", lead_id, node_id)
            return False
        await bus._producer.send_and_wait(  # type: ignore[union-attr]
            bus.TRANSITIONS_TOPIC, value=transition, key=str(lead_id)
        )
        log.info("[event-resume] resumed lead %s at node %s -> handle %s", lead_id, node_id, handle)
        return True
    except Exception:  # noqa: BLE001 — never break the caller's public response
        log.exception("[event-resume] failed resuming lead %s at node %s", lead_id, node_id)
        return False


async def resume_on_signal(
    workspace_id: str,
    lead_id: str | None,
    signal: str,
    *,
    correlation_id: str | None = None,
) -> bool:
    """If ``lead_id`` is parked at the node that awaits ``signal``, emit the
    resume transition on its success handle. Returns True when a resume was
    emitted, False on any no-op (no lead, not parked, wrong node, bus down).

    Best-effort and self-contained: a failure here must never break the caller
    (a public pixel response or a webhook ack)."""
    mapping = _SIGNAL_RESUME.get(signal)
    if not mapping or not lead_id:
        return False
    node_type, handle = mapping
    try:
        async with system_scope():
            row = await fetch_one(
                """
                SELECT l.current_node_id, n.node_type
                FROM omni_leads l
                JOIN omni_workflow_nodes n ON n.id = l.current_node_id
                WHERE l.id = $1 AND l.workspace_id = $2
                  AND l.status = 'waiting'
                """,
                lead_id,
                workspace_id,
            )
        if not row or row.get("node_type") != node_type:
            # Lead isn't parked here (already advanced / different wait / gone).
            return False
        transition = {
            "lead_id": str(lead_id),
            "source_node_id": str(row["current_node_id"]),
            "handle": handle,
            "event_type": "transition",
            "metadata": {
                "workspace_id": workspace_id,
                "correlation_id": correlation_id,
                "resume_signal": signal,
            },
        }
        if bus._producer is None:  # type: ignore[attr-defined]
            log.warning("[event-resume] bus producer not ready; cannot resume lead %s on %s", lead_id, signal)
            return False
        await bus._producer.send_and_wait(  # type: ignore[union-attr]
            bus.TRANSITIONS_TOPIC, value=transition, key=str(lead_id)
        )
        log.info("[event-resume] resumed lead %s on %s -> handle %s", lead_id, signal, handle)
        return True
    except Exception:  # noqa: BLE001 — never break the caller's public response
        log.exception("[event-resume] failed resuming lead %s on signal %s", lead_id, signal)
        return False
