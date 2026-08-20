"""Transition worker.

Consumes ``outreach.transitions`` (emitted by the Flink orchestrator after the
muscle returns a result) and advances the lead through the canvas DAG:

  1. read the transition: (source_node_id, handle, lead_id)
  2. find the edge leaving source_node_id on that handle
  3. set the lead's current_node_id to the edge's target
  4. fire the target node by re-running its Python ``execute`` and publishing
     any intent events to omni.events (the dispatcher turns those into the
     next muscle command). Conditions/flow nodes resolve locally and emit
     their own transition so the DAG keeps moving without a muscle hop.

When no outgoing edge matches the handle, the lead has reached a leaf — mark it
completed.

Transition shape (StateTransition in app/core/events.py):
  {lead_id, campaign_id, source_node_id, handle, metadata:{workspace_id?,...}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import signal
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiokafka import AIOKafkaConsumer

import app.nodes as noderegistry
from app.config import settings
from app.db import (
    acquire,
    assert_rls_enforcing_role,
    close_pool,
    execute,
    fetch_all,
    fetch_one,
    init_pool,
    system_scope,
)
from app.execution import commands
from app.services import bus, company_kg, email_verification, inbound_reply, send_policy, suppression
from app.services.unipile_client import UnipileClient, UnipileError, UnipileNotConfigured

log = logging.getLogger("transitions")

TRANSITIONS_TOPIC = "outreach.transitions"
CONSUMER_GROUP = "v2-transitions"

# Decision A (logic-integrity ledger): the terminal-state contract. A lead in
# one of these states is DONE — no transition may advance, re-fire, or resurrect
# it. Kafka is at-least-once and Flink's sink is AT_LEAST_ONCE, so redelivered/
# re-emitted transitions for already-finished leads are NORMAL, not exceptional;
# without this guard they resurrected errored leads (SM-1) and cancelled race
# losers (SM-6). Enforced once, at handle_transition entry.
TERMINAL_STATUSES = ("completed", "errored", "cancelled", "converted", "ended", "suppressed", "invalid")

# SPINE-LEAF-001: when a lead reaches a leaf (a handle with no outgoing edge), the
# terminal status must REFLECT THE HANDLE, not be a blanket "completed". A node
# emitting on_error (the send/scrape failed) or empty (found nothing) with no
# wired handler is the common case — recording those as "completed" makes a
# failure indistinguishable from success in Leads/Analytics and reports a false
# campaign.run.completed to the objective loop. Map the outcome honestly.
_LEAF_TERMINAL_STATUS: dict[str, str] = {
    "on_error": "errored",
    "error": "errored",
    "failed": "errored",
    "empty": "ended",
    "no_results": "ended",
    "none": "ended",
    # RELGATE-001: a DM held because the recipient isn't a 1st-degree connection
    # is not a failure and not a success — if the campaign didn't wire a
    # `not_connected` branch (e.g. loop back to invite), end the lead honestly
    # rather than record a false 'completed'.
    "not_connected": "ended",
    # NOCHAT-001: a DM that opened a chat but got no chat_id back is degraded —
    # the send likely went but we can't thread a follow-up. Unwired, end the
    # lead honestly (not 'completed') so the degradation is visible.
    "no_thread": "ended",
    # DEDUP-SEND-001: a send skipped because the contact was already messaged on
    # this channel (dedupe_action=skip_step) with no wired continuation ends
    # honestly — it's neither a fresh send nor a failure.
    "already_messaged": "ended",
    # MSG-QA-001: the reviewer refused this draft for the PROSPECT, not the
    # wording. Unwired, the lead stops here — but nothing was sent, so
    # 'completed' would claim a send that never happened.
    "reject": "ended",
}


def _leaf_terminal_status(handle: str) -> str:
    """Terminal status for a lead that fell off the graph on `handle`. A failure
    handle terminalizes 'errored', an empty/no-result handle 'ended', and any
    success/continuation handle (default/then/done/known/new/…) 'completed'."""
    return _LEAF_TERMINAL_STATUS.get((handle or "").strip().lower(), "completed")


def _suppression_identity(contact: dict | None, lead: dict | None) -> dict | None:
    """DNC-SKIP-001: the recipient identity to suppression-check, from the contact
    row if present, else from the lead's own custom_fields (a discovered person /
    company before a contact row exists). suppression.is_suppressed matches on
    email / linkedin_url / domain, so surface those keys from wherever they live."""
    if contact:
        return contact
    cf = (lead or {}).get("custom_fields") or {}
    person = cf.get("item") if isinstance(cf.get("item"), dict) else {}
    ident = {
        "email": cf.get("email") or person.get("email"),
        "linkedin_url": cf.get("linkedin_url") or person.get("linkedin_url"),
        "company": cf.get("company") or person.get("company") or person.get("company_name"),
    }
    return ident if any(ident.values()) else None

# Outbound channels that physically message the contact — the DNC gate (T1)
# applies to these. Internal "channels" (tags, alerts, enrich) are not sends.
_OUTBOUND_SEND_CHANNELS = frozenset(
    {
        "channel.email", "channel.sms", "channel.voice",
        "channel.linkedin_invite", "channel.linkedin_dm",
        "channel.linkedin_inmail", "channel.linkedin_profile_view",
        "channel.whatsapp", "channel.instagram", "channel.telegram",
        "channel.slack", "channel.webhook_out",
        # UNIPILE-FULL: per-lead social ACTIONS are real outbound side effects, so
        # they MUST pass the same send gates (DNC/dedupe/rate) as a message when
        # fired in a campaign — route them through the _gate_send chokepoint.
        "channel.linkedin_react_post", "channel.linkedin_comment_post",
        "channel.linkedin_endorse", "channel.linkedin_follow",
        "channel.message_react", "channel.invite_cancel",
    }
)

# DEDUP-SEND-001: the channels that address a PERSON (a contact) — the subset of
# the send channels where "don't message the same person twice" is meaningful.
# slack (a team alert) and webhook_out (an HTTP sink) carry no contact recipient,
# so the dedupe guard never applies to them. The channel token stored in
# omni_send_outcomes.channel is the bare suffix ("linkedin", "email", …), which
# is what the guard matches a prior send on.
_PERSON_MESSAGE_CHANNELS = frozenset(
    {
        "channel.email", "channel.sms", "channel.voice",
        "channel.linkedin_invite", "channel.linkedin_dm",
        "channel.linkedin_inmail", "channel.linkedin_profile_view",
        "channel.whatsapp", "channel.instagram", "channel.telegram",
    }
)

# Recursion guards for flow.for_each. A single mis-wired loop edge can melt the
# system (see 2026-06 incident: one edge from a downstream join back into the
# for_each created a 113k-lead explosion). Two guards:
#   1. Ancestor walk — if any ancestor lead was spawned by THIS for_each node,
#      refuse to fan out again (the canvas has a cycle).
#   2. Per-root descendant cap — if the root parent's lineage already exceeds
#      MAX_DESCENDANTS_PER_ROOT, refuse further fan-out (runaway growth).
MAX_DESCENDANTS_PER_ROOT = 10_000
MAX_ANCESTOR_WALK_DEPTH = 64
# E2E-002: how many times a for_each may release its claim waiting for a
# source's collection mutation to land (delivery-ordering gap) before treating
# the collection as genuinely empty and routing to done/empty. Each redelivered
# transition is one attempt; the source result is redelivered several times, so
# a small bound is enough to bridge the gap without spinning on a truly-empty source.
FANOUT_EMPTY_RETRY_LIMIT = 8


async def _target_node(workspace_id: str, source_node_id: str, handle: str) -> dict | None:
    """Edge leaving source_node_id on `handle` -> the target node row."""
    async with system_scope():
        edge = await fetch_one(
            """
            SELECT target_node_id FROM omni_workflow_edges
            WHERE workspace_id=$1 AND source_node_id=$2 AND source_handle=$3
            LIMIT 1
            """,
            workspace_id,
            source_node_id,
            handle,
        )
        if not edge:
            return None
        return await fetch_one(
            "SELECT id, node_type, config, workflow_id FROM omni_workflow_nodes WHERE id=$1 AND workspace_id=$2",
            edge["target_node_id"],
            workspace_id,
        )


async def _advance_lead(workspace_id: str, lead_id: str, node_id: str | None, status: str = "active") -> None:
    async with system_scope():
        await execute(
            "UPDATE omni_leads SET current_node_id=$1, status=$2, updated_at=NOW() WHERE id=$3 AND workspace_id=$4",
            node_id,
            status,
            lead_id,
            workspace_id,
        )


async def _outgoing_edge(workspace_id: str, source_node_id: str, handle: str) -> dict | None:
    """The (target_node_id) edge leaving source_node_id on `handle`, or None."""
    async with system_scope():
        return await fetch_one(
            """
            SELECT target_node_id FROM omni_workflow_edges
            WHERE workspace_id=$1 AND source_node_id=$2 AND source_handle=$3
            LIMIT 1
            """,
            workspace_id,
            source_node_id,
            handle,
        )


async def _node_row(workspace_id: str, node_id: str) -> dict | None:
    async with system_scope():
        return await fetch_one(
            "SELECT id, node_type, config, workflow_id FROM omni_workflow_nodes WHERE id=$1 AND workspace_id=$2",
            node_id,
            workspace_id,
        )


async def _lead_with_contact(workspace_id: str, lead_id: str) -> tuple[dict | None, dict | None]:
    async with system_scope():
        lead = await fetch_one("SELECT * FROM omni_leads WHERE id=$1 AND workspace_id=$2", lead_id, workspace_id)
        contact = None
        if lead and lead.get("contact_id"):
            contact = await fetch_one(
                "SELECT * FROM omni_contacts WHERE id=$1 AND workspace_id=$2", lead["contact_id"], workspace_id
            )
    return lead, contact


async def _advance_and_fire(workspace_id: str, lead_id: str, target_node_id: str, correlation_id: str | None) -> None:
    """Move a lead to target_node_id and fire it — the normal advance path,
    reused by the for_each/join release so they don't duplicate it."""
    await _advance_lead(workspace_id, lead_id, target_node_id)
    node = await _node_row(workspace_id, target_node_id)
    lead, contact = await _lead_with_contact(workspace_id, lead_id)
    if lead and node:
        await _fire_node(workspace_id, lead, contact, node, correlation_id)


async def _ancestor_visited_for_each(
    workspace_id: str, parent: dict, for_each_id: str
) -> tuple[bool, str | None]:
    """Walk parent_lead_id upward; return (True, root_id) if any ancestor was
    spawned by THIS for_each node (cycle in the canvas wiring). Also returns
    the root parent_id (top of the chain) regardless, so callers can use it
    for the per-root descendant cap."""
    current_origin = parent.get("origin_node_id")
    if current_origin and str(current_origin) == for_each_id:
        return True, str(parent["id"])
    cur = parent
    root_id = str(parent["id"])
    for _ in range(MAX_ANCESTOR_WALK_DEPTH):
        parent_id = cur.get("parent_lead_id")
        if not parent_id:
            return False, root_id
        async with system_scope():
            cur = await fetch_one(
                "SELECT id, parent_lead_id, origin_node_id FROM omni_leads "
                "WHERE id=$1 AND workspace_id=$2",
                str(parent_id),
                workspace_id,
            )
        if not cur:
            return False, root_id
        root_id = str(cur["id"])
        if cur.get("origin_node_id") and str(cur["origin_node_id"]) == for_each_id:
            return True, root_id
    log.warning(
        "ancestor walk for lead %s exceeded depth %d — treating as cycle",
        parent.get("id"),
        MAX_ANCESTOR_WALK_DEPTH,
    )
    return True, root_id


async def _descendant_count_for_root(workspace_id: str, root_id: str) -> int:
    """Count total leads in the lineage rooted at root_id (recursive CTE).
    Used to enforce MAX_DESCENDANTS_PER_ROOT."""
    async with system_scope():
        row = await fetch_one(
            """
            WITH RECURSIVE lineage(id) AS (
                SELECT id FROM omni_leads WHERE id=$1 AND workspace_id=$2
                UNION ALL
                SELECT l.id FROM omni_leads l
                JOIN lineage ON l.parent_lead_id = lineage.id
                WHERE l.workspace_id=$2
            )
            SELECT count(*) AS n FROM lineage
            """,
            root_id,
            workspace_id,
        )
    return int((row or {}).get("n") or 0)


async def _fan_out(workspace_id: str, parent: dict, for_each_node: dict, correlation_id: str | None) -> None:
    """A lead reached a flow.for_each node. Read the collection from the
    parent's custom_fields and spawn one child lead per element on the `each`
    edge. The parent parks (status='waiting') at the for_each node until the
    join barrier releases it. Empty collection -> walk done/empty immediately.

    Refuses to fan out when the canvas has a cycle (an ancestor was spawned
    by this same for_each) or when the root lineage already exceeds the
    per-root descendant cap. In both cases the parent is routed down the
    done/empty edge so the workflow terminates cleanly instead of melting."""
    cfg = for_each_node.get("config") or {}
    items_key = cfg.get("items_key") or "items"
    item_field = cfg.get("item_field") or "item"
    # `or 500` would turn an explicit max_items=0 into 500 — a footgun when an
    # operator wants to disable a fan-out arm. Treat a missing/None value as
    # the default, but honour 0 (and any explicit int) literally.
    _raw_max = cfg.get("max_items")
    max_items = 500 if _raw_max is None else max(0, int(_raw_max))
    for_each_id = str(for_each_node["id"])

    # DEPLOY-001 / E2E-001: a redelivered OR concurrent transition must not
    # double-spawn children. The old in-memory guard (check current_node_id +
    # status + fanout_total on the read-back row) had a TOCTOU race: 4 copies of
    # the source's result redelivered ~simultaneously all passed the guard before
    # any committed the parking UPDATE, so the for_each fanned out 4×5=20 children
    # for a max_items:5 collection. Replace it with an ATOMIC CLAIM: set a sentinel
    # fanout_total=-1 only WHERE fanout_total IS NULL, gated by RETURNING. Exactly
    # one transition wins the claim and proceeds; the rest get no row and no-op.
    # The claim sentinel is fanout_total: a lead that has NOT yet fanned out at
    # this node sits at the column's NOT NULL DEFAULT 0 (seed leads) — so the
    # "unclaimed" predicate is fanout_total=0, NOT `IS NULL` (an earlier cut used
    # IS NULL, which never matched a seed lead and silently no-op'd EVERY fan-out:
    # E2E-003). Claiming flips it to the -1 sentinel; the real count overwrites it
    # at parking. Concurrent/redelivered claims then see != 0 and lose the race.
    async with system_scope():
        claimed = await fetch_one(
            "UPDATE omni_leads SET fanout_total=-1, current_node_id=$1, status='waiting', "
            "updated_at=NOW() WHERE id=$2 AND workspace_id=$3 AND fanout_total=0 RETURNING id",
            for_each_id,
            str(parent["id"]),
            workspace_id,
        )
    if not claimed:
        log.info("fan_out skipped: lead %s already claimed/fanned at %s (redelivery/concurrent)", parent.get("id"), for_each_id)
        return

    # E2E-002 (read-after-write): the `parent` arg is the snapshot the transition
    # carried in. Under at-least-once redelivery, the delivery that WINS the claim
    # may carry a snapshot taken before the source's company-list mutation landed
    # (observed: 35 companies in the DB but fanout_total=0, zero children). Re-read
    # custom_fields FRESH now — the claim above serializes us, and each delivery
    # applies its own mutation in handle_transition before routing here, so the
    # committed row always has the collection. This makes items read-after-write
    # consistent regardless of how many times the source result was redelivered.
    async with system_scope():
        fresh = await fetch_one(
            "SELECT custom_fields FROM omni_leads WHERE id=$1 AND workspace_id=$2",
            str(parent["id"]),
            workspace_id,
        )
    if fresh and fresh.get("custom_fields") is not None:
        cf = fresh["custom_fields"]
        if isinstance(cf, str):
            cf = json.loads(cf)
        parent = {**parent, "custom_fields": cf}

    cycle_hit, root_id = await _ancestor_visited_for_each(workspace_id, parent, for_each_id)
    if cycle_hit:
        log.error(
            "fan_out refused: cycle detected at for_each=%s for lead=%s (root=%s)",
            for_each_id,
            parent.get("id"),
            root_id,
        )
        items = []
    else:
        descendants = await _descendant_count_for_root(workspace_id, root_id)
        if descendants >= MAX_DESCENDANTS_PER_ROOT:
            log.error(
                "fan_out refused: per-root descendant cap %d reached for root=%s at for_each=%s",
                MAX_DESCENDANTS_PER_ROOT,
                root_id,
                for_each_id,
            )
            items = []
        else:
            items = (parent.get("custom_fields") or {}).get(items_key) or []
            if not isinstance(items, list):
                items = []
            # E2E-001: defensively de-duplicate identical elements before the cap.
            # A source that returns the same company/person twice (or a replayed
            # mutation that appended a dup) must not spawn N identical children —
            # that wastes paid screens and inflates the join barrier. Dedup by a
            # stable JSON key, preserving first-seen order.
            items = _dedup_items(items)
            items = items[:max_items]
            # Cap each fan-out so a single rogue collection can't blow past
            # the per-root limit in one shot.
            remaining = MAX_DESCENDANTS_PER_ROOT - descendants
            if len(items) > remaining:
                log.warning(
                    "fan_out clamped: %d items -> %d to respect per-root cap (root=%s)",
                    len(items),
                    remaining,
                    root_id,
                )
                items = items[:remaining]

    each_edge = await _outgoing_edge(workspace_id, for_each_id, "each")
    parent_id = str(parent["id"])

    # E2E-002 (delivery ordering): if we won the claim but the collection is still
    # empty AND there's a real `each` arm, the source's collection mutation almost
    # certainly hasn't landed yet (the Flink orchestrator delivers the mutation
    # envelope and the for_each-routing transition separately + at-least-once, so
    # the claim-winner can arrive first). RELEASE the claim (fanout_total back to
    # NULL) so the later, collection-bearing delivery re-claims and fans out for
    # real — instead of silently consuming the claim and routing to done/empty,
    # which strands a full scrape with zero leads. A genuinely-empty collection
    # just re-claims, re-reads empty, and falls through to done on a later pass;
    # the staleness guard below caps that. Guarded by an attempt counter in
    # custom_fields so a truly-empty source can't spin forever.
    if not items and each_edge:
        cf = dict(parent.get("custom_fields") or {})
        attempts = int(cf.get("_fanout_retry", 0))
        if attempts < FANOUT_EMPTY_RETRY_LIMIT:
            async with system_scope():
                await execute(
                    # Reset to the unclaimed sentinel (0, the column default) — NOT
                    # NULL — so a later collection-bearing delivery re-claims via
                    # the fanout_total=0 predicate above (E2E-003).
                    "UPDATE omni_leads SET fanout_total=0, status='active', "
                    "custom_fields = COALESCE(custom_fields,'{}'::jsonb) || $1::jsonb, "
                    "updated_at=NOW() WHERE id=$2 AND workspace_id=$3",
                    json.dumps({"_fanout_retry": attempts + 1}),
                    parent_id,
                    workspace_id,
                )
            log.info(
                "fan_out released claim for lead %s at %s: collection empty, awaiting mutation (retry %d/%d)",
                parent_id, for_each_id, attempts + 1, FANOUT_EMPTY_RETRY_LIMIT,
            )
            return

    if not items or not each_edge:
        # SEQ-FANOUT: release the -1 claim sentinel before routing on. Leaving
        # it set meant this lead could never claim ANY later fan-out node (the
        # claim predicate is fanout_total=0) — every sequential for_each after
        # the first silently never fanned out.
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET fanout_total=0, fanout_done=0, updated_at=NOW() "
                "WHERE id=$1 AND workspace_id=$2",
                parent_id,
                workspace_id,
            )
        done_edge = await _outgoing_edge(workspace_id, for_each_id, "done") or await _outgoing_edge(
            workspace_id, for_each_id, "empty"
        )
        if done_edge:
            await _advance_and_fire(workspace_id, str(parent["id"]), str(done_edge["target_node_id"]), correlation_id)
        else:
            await _terminalize_lead(workspace_id, str(parent["id"]), "completed", correlation_id)
        return

    each_target = str(each_edge["target_node_id"])

    async with system_scope():
        await execute(
            "UPDATE omni_leads SET current_node_id=$1, status='waiting', fanout_total=$2, "
            "fanout_done=0, updated_at=NOW() WHERE id=$3 AND workspace_id=$4",
            for_each_id,
            len(items),
            parent_id,
            workspace_id,
        )

    each_node = await _node_row(workspace_id, each_target)
    for element in items:
        child_id = str(uuid.uuid4())
        child_fields = dict(parent.get("custom_fields") or {})
        child_fields[item_field] = element
        async with system_scope():
            await execute(
                """
                INSERT INTO omni_leads
                    (id, workspace_id, contact_id, workflow_id, current_node_id, status,
                     custom_fields, parent_lead_id, origin_node_id)
                VALUES ($1, $2, $3, $4, $5, 'active', $6, $7, $8)
                """,
                child_id,
                workspace_id,
                parent.get("contact_id"),
                parent.get("workflow_id"),
                each_target,
                json.dumps(child_fields),
                parent_id,
                for_each_id,
            )
        child, contact = await _lead_with_contact(workspace_id, child_id)
        if child and each_node:
            await _fire_node(workspace_id, child, contact, each_node, correlation_id)

    log.info("fanned out lead %s -> %d children at %s", parent_id, len(items), for_each_id)


def _dedup_items(items: list) -> list:
    """Drop duplicate fan-out elements, preserving first-seen order. Keyed by a
    canonical JSON serialisation so dict elements (company/person rows) dedup by
    value. Non-serialisable elements fall back to identity (never dropped)."""
    seen: set[str] = set()
    out: list = []
    for el in items:
        try:
            key = json.dumps(el, sort_keys=True, default=str)
        except (TypeError, ValueError):
            out.append(el)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(el)
    return out


async def _outgoing_edges(workspace_id: str, source_node_id: str) -> list[dict]:
    """All edges leaving a node (source_handle + target_node_id). Used by race
    to spawn one child per branch arm."""
    async with system_scope():
        return await fetch_all(
            "SELECT source_handle, target_node_id FROM omni_workflow_edges "
            "WHERE workspace_id=$1 AND source_node_id=$2 ORDER BY source_handle",
            workspace_id,
            source_node_id,
        )


async def _race_fan_out(workspace_id: str, parent: dict, race_node: dict, correlation_id: str | None) -> None:
    """A lead reached flow.race. Spawn one child per ``branch_*`` edge leaving the
    race node; each child walks its arm in parallel. The parent parks
    (status='waiting', fanout_total=#arms). The FIRST child to reach the matching
    flow.join wins (see _join_arrive's race branch): the parent advances and the
    losing siblings are cancelled. Reuses the same lineage columns
    (parent_lead_id / origin_node_id) as for_each so the join machinery is shared.

    RACE-1: idempotency is an ATOMIC CLAIM, identical to _fan_out's. The old
    in-memory guard (re-read the row, check status=='waiting') was a TOCTOU: the
    caller's unconditional _advance_lead had just flipped the parent back to
    'active' on every redelivery — so the guard never matched, every redelivery
    fanned out a second set of arms, AND the trample broke the join's first-
    arm-wins claim (which requires status='waiting'): once trampled, NO arm
    could ever win and the parent hung forever. The claim (fanout_total 0 → -1,
    one winner via RETURNING) + the caller no longer pre-advancing fan-out
    targets fixes both."""
    race_id = str(race_node["id"])
    parent_id = str(parent["id"])
    async with system_scope():
        claimed = await fetch_one(
            "UPDATE omni_leads SET fanout_total=-1, current_node_id=$1, status='waiting', "
            "updated_at=NOW() WHERE id=$2 AND workspace_id=$3 AND fanout_total=0 RETURNING id",
            race_id,
            parent_id,
            workspace_id,
        )
    if not claimed:
        log.info("race_fan_out skipped: lead %s already claimed/raced at %s (redelivery/concurrent)", parent_id, race_id)
        return

    # Only the branch_* arms are race participants (the `timeout` handle is the
    # parent's own escape, not a child arm).
    arms = [
        e for e in await _outgoing_edges(workspace_id, race_id)
        if str(e["source_handle"]).startswith("branch_")
    ]
    if not arms:
        # Misconfigured race with no arms — release the claim sentinel so a
        # future fan-out node can claim, then route to timeout (or terminal).
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET fanout_total=0, fanout_done=0, updated_at=NOW() "
                "WHERE id=$1 AND workspace_id=$2",
                parent_id,
                workspace_id,
            )
        timeout_edge = await _outgoing_edge(workspace_id, race_id, "timeout")
        if timeout_edge:
            await _advance_and_fire(workspace_id, parent_id, str(timeout_edge["target_node_id"]), correlation_id)
        else:
            await _terminalize_lead(workspace_id, parent_id, "completed", correlation_id)
        log.warning("race %s has no branch_* arms; parent routed to timeout/leaf", race_id)
        return

    async with system_scope():
        await execute(
            "UPDATE omni_leads SET current_node_id=$1, status='waiting', fanout_total=$2, "
            "fanout_done=0, updated_at=NOW() WHERE id=$3 AND workspace_id=$4",
            race_id,
            len(arms),
            parent_id,
            workspace_id,
        )

    for arm in arms:
        target_id = str(arm["target_node_id"])
        child_id = str(uuid.uuid4())
        child_fields = dict(parent.get("custom_fields") or {})
        async with system_scope():
            await execute(
                """
                INSERT INTO omni_leads
                    (id, workspace_id, contact_id, workflow_id, current_node_id, status,
                     custom_fields, parent_lead_id, origin_node_id)
                VALUES ($1, $2, $3, $4, $5, 'active', $6, $7, $8)
                """,
                child_id,
                workspace_id,
                parent.get("contact_id"),
                parent.get("workflow_id"),
                target_id,
                json.dumps(child_fields),
                parent_id,
                race_id,
            )
        child, contact = await _lead_with_contact(workspace_id, child_id)
        arm_node = await _node_row(workspace_id, target_id)
        if child and arm_node:
            await _fire_node(workspace_id, child, contact, arm_node, correlation_id)

    # Schedule the timeout: a delayed synthetic result for the PARENT on the
    # race's `timeout` handle. When it fires, handle_transition only honours it
    # if the parent is still parked at this race (no arm has won) — a winner
    # flips the parent to 'active'/advances it, so the late timeout no-ops.
    cfg = race_node.get("config") or {}
    timeout_hours = cfg.get("timeout_hours")
    timeout_hours = 168 if timeout_hours is None else int(timeout_hours)
    await _emit_synthetic_result(
        workspace_id, parent_id, race_id, "timeout", correlation_id,
        delay_seconds=float(timeout_hours) * 3600.0,
    )

    log.info("raced lead %s -> %d parallel arms at %s (timeout %dh)", parent_id, len(arms), race_id, timeout_hours)


async def _terminalize_lead(
    workspace_id: str,
    lead_id: str,
    status: str,
    correlation_id: str | None,
    *,
    join_arrival: bool = False,
) -> bool:
    """Move a lead to a terminal status ATOMICALLY and account it at its
    parent's fan-out barrier (Decision B / SM-5).

    The UPDATE's status-predicate is the once-only claim: exactly one call ever
    terminalizes a lead, no matter how many times its transition is redelivered.
    Only the claiming call COUNTS at the barrier; a redelivered (already
    terminal) call still re-attempts the barrier RELEASE check with count=False
    — that recovers a worker crash between the increment and the release (the
    uncommitted offset redelivers the child's transition; recount would corrupt,
    but a release re-check is claim-gated and idempotent).

    Every terminal path must come through here — leaf completion, node errors,
    goal/end, dead-on-arrival — because a fan-out child that goes terminal
    ANYWHERE other than flow.join used to vanish without decrementing the join
    barrier, hanging its parent in 'waiting' forever (SM-5: guaranteed under
    any child failure). Nested fan-outs cascade naturally: a parent terminalized
    here notifies ITS parent's barrier in turn."""
    async with system_scope():
        row = await fetch_one(
            "UPDATE omni_leads SET status=$1, current_node_id=NULL, updated_at=NOW() "
            "WHERE id=$2 AND workspace_id=$3 AND status NOT IN "
            "('completed','errored','cancelled','converted','ended','suppressed','invalid') "
            "RETURNING parent_lead_id, origin_node_id, workflow_id, custom_fields",
            status,
            lead_id,
            workspace_id,
        )
    if row:
        if row.get("parent_lead_id") and row.get("origin_node_id"):
            await _barrier_arrive(
                workspace_id,
                str(row["parent_lead_id"]),
                str(row["origin_node_id"]),
                str(lead_id),
                correlation_id,
                join_arrival=join_arrival,
                count=True,
            )
        elif row.get("workflow_id"):
            # A ROOT/run-lead just completed (no parent_lead_id = it's the
            # campaign's seed, not a fan-out child) — one full sourcing pass is
            # done. EMIT A FACT and stop: the goal-pursuit control loop lives in
            # a dedicated consumer (app.execution.objective_worker), NOT inline
            # here. The transition worker must not run a feedback loop inside its
            # once-only terminalize claim — that's the safety-critical hot path.
            # Emitting onto omni.events makes the loop event-sourced (durable,
            # replayable, archived for tracing) instead of a synchronous
            # side-effect that a crash could lose. Gated on the claim, so the
            # fact fires exactly once per completion. Best-effort publish: a bus
            # hiccup must never wedge the claim (the projection is already
            # committed; the worst case is one run isn't re-evaluated).
            try:
                await bus.publish_event(
                    workspace_id=workspace_id,
                    event_type="campaign.run.completed",
                    entity_type="lead",
                    entity_id=str(lead_id),
                    payload={
                        "workflow_id": str(row["workflow_id"]),
                        "root_lead_id": str(lead_id),
                        "terminal_status": status,
                        "run_source_count": int(
                            (row.get("custom_fields") or {}).get("_run_source_count") or 1
                        ),
                        "run_source_index": int(
                            (row.get("custom_fields") or {}).get("_run_source_index") or 0
                        ),
                    },
                    correlation_id=correlation_id,
                )
            except Exception:  # noqa: BLE001
                log.exception("failed to emit campaign.run.completed for workflow %s", row.get("workflow_id"))
        return True
    # Already terminal — redelivery. Re-attempt the release check only.
    async with system_scope():
        prior = await fetch_one(
            "SELECT parent_lead_id, origin_node_id FROM omni_leads WHERE id=$1 AND workspace_id=$2",
            lead_id,
            workspace_id,
        )
    if prior and prior.get("parent_lead_id") and prior.get("origin_node_id"):
        await _barrier_arrive(
            workspace_id,
            str(prior["parent_lead_id"]),
            str(prior["origin_node_id"]),
            str(lead_id),
            correlation_id,
            join_arrival=join_arrival,
            count=False,
        )
    return False


async def _barrier_arrive(
    workspace_id: str,
    parent_id: str,
    origin_node_id: str,
    child_id: str,
    correlation_id: str | None,
    *,
    join_arrival: bool,
    count: bool,
) -> None:
    """Account one child's terminalization at the parent's fan-out barrier.

    Origin semantics: flow.race releases on the FIRST join-arrival (and cancels
    the losers); flow.for_each waits for ALL children — counting failures too,
    or one errored child hangs the barrier forever (SM-5).

    Every parent UPDATE here is pinned to ``current_node_id=origin_node_id``:
    the barrier may only mutate a parent that is still parked at THIS fan-out
    node. Without the pin, a ghost redelivery from an earlier fan-out could
    increment (or release!) a barrier the same lead opened at a LATER node —
    possible now that counters reset on release to support sequential fan-outs.

    Release claims reset fanout_total/fanout_done to 0 (the _fan_out/_race
    claim's 'unclaimed' sentinel) — without the reset, a lead that finished one
    fan-out could never claim a second one (SEQ-FANOUT: every sequential
    for_each after the first silently never fanned out)."""
    origin = await _node_row(workspace_id, origin_node_id)
    origin_type = (origin or {}).get("node_type")

    if origin_type == "flow.race":
        if join_arrival:
            # First-arm-wins: atomic claim — only the first arrival flips the
            # parent out of 'waiting'. Redelivered/late arrivals see no row.
            async with system_scope():
                parent = await fetch_one(
                    "UPDATE omni_leads SET status='active', fanout_total=0, fanout_done=0, "
                    "updated_at=NOW() WHERE id=$1 AND workspace_id=$2 AND status='waiting' "
                    "AND current_node_id=$3 RETURNING id",
                    parent_id,
                    workspace_id,
                    origin_node_id,
                )
            if not parent:
                return  # a sibling already won (or race resolved) — loser just ended
            async with system_scope():
                await execute(
                    "UPDATE omni_leads SET status='cancelled', current_node_id=NULL, updated_at=NOW() "
                    "WHERE workspace_id=$1 AND parent_lead_id=$2 AND origin_node_id=$3 "
                    "AND id<>$4 AND status NOT IN ('completed','errored','cancelled','converted','ended')",
                    workspace_id,
                    parent_id,
                    origin_node_id,
                    child_id,
                )
            done_edge = await _outgoing_edge(workspace_id, origin_node_id, "done")
            if done_edge:
                await _advance_and_fire(workspace_id, parent_id, str(done_edge["target_node_id"]), correlation_id)
                log.info("race won by %s; parent %s -> %s, siblings cancelled", child_id, parent_id, done_edge["target_node_id"])
            else:
                await _terminalize_lead(workspace_id, parent_id, "completed", correlation_id)
                log.info("race won by %s; parent %s released (no done edge) -> completed", child_id, parent_id)
            return
        # A race arm that ended WITHOUT reaching the join (errored / leaf /
        # cancelled-elsewhere). It can't win — but it must still be accounted,
        # or a race whose every arm fails waits for the (up to 168h) timeout.
        if count:
            async with system_scope():
                row = await fetch_one(
                    "UPDATE omni_leads SET fanout_done=fanout_done+1, updated_at=NOW() "
                    "WHERE id=$1 AND workspace_id=$2 AND status='waiting' AND current_node_id=$3 "
                    "RETURNING fanout_done, fanout_total",
                    parent_id,
                    workspace_id,
                    origin_node_id,
                )
        else:
            async with system_scope():
                row = await fetch_one(
                    "SELECT fanout_done, fanout_total FROM omni_leads "
                    "WHERE id=$1 AND workspace_id=$2 AND status='waiting' AND current_node_id=$3",
                    parent_id,
                    workspace_id,
                    origin_node_id,
                )
        total = (row or {}).get("fanout_total") or 0
        if not row or total <= 0 or (row.get("fanout_done") or 0) < total:
            return
        # Every arm ended, none won — escape via the operator's timeout edge,
        # else the race itself failed.
        async with system_scope():
            claimed = await fetch_one(
                "UPDATE omni_leads SET status='active', fanout_total=0, fanout_done=0, "
                "updated_at=NOW() WHERE id=$1 AND workspace_id=$2 AND status='waiting' "
                "AND current_node_id=$3 RETURNING id",
                parent_id,
                workspace_id,
                origin_node_id,
            )
        if not claimed:
            return
        timeout_edge = await _outgoing_edge(workspace_id, origin_node_id, "timeout")
        if timeout_edge:
            await _advance_and_fire(workspace_id, parent_id, str(timeout_edge["target_node_id"]), correlation_id)
            log.warning("race %s: all arms ended without a winner; parent %s -> timeout edge", origin_node_id, parent_id)
        else:
            await _terminalize_lead(workspace_id, parent_id, "errored", correlation_id)
            log.error("race %s: all arms failed and no timeout edge wired; parent %s errored", origin_node_id, parent_id)
        return

    # flow.for_each barrier: wait for ALL children (successes AND failures).
    if count:
        async with system_scope():
            row = await fetch_one(
                "UPDATE omni_leads SET fanout_done=fanout_done+1, updated_at=NOW() "
                "WHERE id=$1 AND workspace_id=$2 AND current_node_id=$3 "
                "RETURNING fanout_done, fanout_total",
                parent_id,
                workspace_id,
                origin_node_id,
            )
    else:
        async with system_scope():
            row = await fetch_one(
                "SELECT fanout_done, fanout_total FROM omni_leads "
                "WHERE id=$1 AND workspace_id=$2 AND current_node_id=$3",
                parent_id,
                workspace_id,
                origin_node_id,
            )
    total = (row or {}).get("fanout_total") or 0
    if not row or total <= 0 or (row.get("fanout_done") or 0) < total:
        return  # barrier not yet satisfied (or parent gone/moved on)
    async with system_scope():
        claimed = await fetch_one(
            "UPDATE omni_leads SET status='active', fanout_total=0, fanout_done=0, "
            "updated_at=NOW() WHERE id=$1 AND workspace_id=$2 AND status='waiting' "
            "AND current_node_id=$3 RETURNING id",
            parent_id,
            workspace_id,
            origin_node_id,
        )
    if not claimed:
        return  # already released (redelivered final arrival)
    done_edge = await _outgoing_edge(workspace_id, origin_node_id, "done")
    if done_edge:
        await _advance_and_fire(workspace_id, parent_id, str(done_edge["target_node_id"]), correlation_id)
        log.info("join released parent %s -> %s", parent_id, done_edge["target_node_id"])
    else:
        await _terminalize_lead(workspace_id, parent_id, "completed", correlation_id)
        log.info("join released parent %s (no done edge) -> completed", parent_id)


async def _join_arrive(workspace_id: str, child: dict, correlation_id: str | None) -> None:
    """A child lead reached a flow.join. End the child and account it at the
    parent's barrier. All once-only/idempotency/crash-recovery semantics live
    in _terminalize_lead/_barrier_arrive (JOIN-IDEMPOTENCY, E2E-001: counting
    DISTINCT children — one increment per child, ever — is the barrier
    contract; redeliveries re-attempt only the claim-gated release)."""
    await _terminalize_lead(workspace_id, str(child["id"]), "completed", correlation_id, join_arrival=True)


# Fixed-duration unit table for flow.delay (mirrors the node's own table).
_DELAY_UNIT_SECONDS = {"minutes": 60, "hours": 3600, "days": 86400}


async def _workflow_timezone(workspace_id: str, workflow_id: str | None) -> str:
    if not workflow_id:
        return "UTC"
    async with system_scope():
        row = await fetch_one(
            "SELECT timezone FROM omni_workflows WHERE id=$1 AND workspace_id=$2",
            workflow_id,
            workspace_id,
        )
    return (row or {}).get("timezone") or "UTC"


async def _workflow_schedule(workspace_id: str, workflow_id: str | None) -> tuple[Any, Any]:
    """(start_at, end_at) for a workflow — both may be None (always-on, B6)."""
    if not workflow_id:
        return None, None
    async with system_scope():
        row = await fetch_one(
            "SELECT start_at, end_at FROM omni_workflows WHERE id=$1 AND workspace_id=$2",
            workflow_id,
            workspace_id,
        )
    if not row:
        return None, None
    return row.get("start_at"), row.get("end_at")


async def _workflow_send_controls(workspace_id: str, workflow_id: str | None) -> dict[str, Any]:
    """The campaign's per-send controls: business-hours window (earliest/latest
    hour + days_of_week, in the workflow tz), daily cap, and the cap counter
    (sends_today / day_anchor). All optional — an unconfigured campaign is
    always-on / uncapped. Read once per send so the gate has a single snapshot."""
    if not workflow_id:
        return {}
    async with system_scope():
        row = await fetch_one(
            "SELECT timezone, earliest_hour, latest_hour, days_of_week, "
            "daily_cap, sends_today, day_anchor, "
            "send_spacing_seconds, send_spacing_jitter_pct, next_send_at "
            "FROM omni_workflows WHERE id=$1 AND workspace_id=$2",
            workflow_id, workspace_id,
        )
    return dict(row) if row else {}


async def _dedupe_send(
    workspace_id: str,
    lead: dict,
    contact: dict | None,
    node: dict,
    node_type: str,
    workflow_id: str | None,
    correlation_id: str | None,
) -> bool:
    """DEDUP-SEND-001: hold a send to a contact we've already messaged.

    Opt-in per node (``dedupe_action`` defaults ``off`` → returns False, no
    behaviour change). When on, consults the durable send ledger
    (``omni_send_outcomes``, one row per confirmed send across ALL channels) for a
    prior ``status='sent'`` to this contact on this channel; ``dedupe_scope``
    chooses whether to look across all campaigns (``channel``) or only this
    workflow (``campaign``).

    On a prior touch:
      * ``skip_step`` — route the lead onward via the ``already_messaged`` handle
        (skip THIS send, run the rest of the sequence). Unwired → ends honestly.
      * ``end_lead``  — terminalize the lead 'ended' (never re-touch this person).

    Returns True when the send was handled here (caller must return without
    sending), False when the send may proceed. Only applies to person-addressable
    channels; a contact-less lead (no contact_id) can't be deduped → proceeds."""
    if node_type not in _PERSON_MESSAGE_CHANNELS:
        return False
    cfg = node.get("config") or {}
    action = str(cfg.get("dedupe_action") or "off").lower()
    if action not in ("skip_step", "end_lead"):
        return False
    contact_id = lead.get("contact_id") or (contact or {}).get("id")
    if not contact_id:
        # No contact row to dedupe against (a discovered person pre-contact) —
        # nothing to compare a prior send to. Proceed with the send.
        return False

    channel = node_type.split(".", 1)[-1]  # "channel.linkedin_dm" -> "linkedin_dm"
    # Outcomes recorded before migration 053 used the combined token "linkedin"
    # for every LinkedIn action. Those rows can't say WHICH action they were, so
    # a linkedin_* dedupe check conservatively matches them too: historically
    # touched contacts stay suppressed, while new outcomes dedupe per-action
    # (an invite no longer blocks a DM).
    channels = [channel, "linkedin"] if channel.startswith("linkedin_") else [channel]
    scope = str(cfg.get("dedupe_scope") or "channel").lower()
    # SEQ-DEDUP-001: dedupe suppresses re-contacting someone ANOTHER lead/campaign
    # already messaged — NOT a sequence's own follow-ups. Without excluding this
    # lead's own prior sends, M1's send blocks M2 (same contact, same channel) and
    # every follow-up in a sequence is silently skipped. Exclude the current lead.
    this_lead_id = str(lead["id"])
    async with system_scope():
        if scope == "campaign" and workflow_id:
            row = await fetch_one(
                "SELECT 1 FROM omni_send_outcomes "
                "WHERE workspace_id=$1 AND contact_id=$2 AND channel = ANY($3::text[]) "
                "AND workflow_id=$4 AND status='sent' AND lead_id <> $5 LIMIT 1",
                workspace_id, str(contact_id), channels, workflow_id, this_lead_id,
            )
        else:
            row = await fetch_one(
                "SELECT 1 FROM omni_send_outcomes "
                "WHERE workspace_id=$1 AND contact_id=$2 AND channel = ANY($3::text[]) "
                "AND status='sent' AND lead_id <> $4 LIMIT 1",
                workspace_id, str(contact_id), channels, this_lead_id,
            )
    if not row:
        return False  # never messaged by ANOTHER lead on this channel — proceed.

    log.info(
        "lead %s: DEDUP-SEND-001 skip — contact %s already messaged on %s (scope=%s, action=%s)",
        lead["id"], contact_id, channel, scope, action,
    )
    if action == "end_lead":
        await _terminalize_lead(workspace_id, str(lead["id"]), "ended", correlation_id)
        return True

    # skip_step: route the already_messaged handle. Advance to the wired target if
    # any; otherwise the lead falls off the graph here and ends honestly
    # (_leaf_terminal_status maps already_messaged -> 'ended').
    edge = await _outgoing_edge(workspace_id, str(node["id"]), "already_messaged")
    if edge:
        await _advance_and_fire(
            workspace_id, str(lead["id"]), str(edge["target_node_id"]), correlation_id
        )
    else:
        await _terminalize_lead(workspace_id, str(lead["id"]), "ended", correlation_id)
    return True


async def _reply_gate_send(
    workspace_id: str,
    lead: dict,
    node: dict,
    node_type: str,
    correlation_id: str | None,
) -> bool:
    """REPLY-GATE-001: the HARD reply-stop, checked LIVE at the moment of sending.

    The reply poller (unipile_sync_worker) halts a waiting lead within its poll
    interval, but that leaves a race: a reply can land in the gap before the next
    sweep, and if the operator approves the follow-up in that same gap the
    follow-up ships AFTER the human already answered — exactly what gets a seat
    flagged. This gate removes the race by re-checking Unipile's AUTHORITATIVE
    thread state at the instant of the send: if the newest message in the thread
    is inbound (is_sender==0), the contact has replied since our last message, so
    we DO NOT send — we record the reply and halt the sequence. Poll cadence
    becomes irrelevant to the send decision; the poller is just the "end the wait
    early" optimization, this is the hard stop.

    Applies only to a LinkedIn DM with an already-open thread
    (custom_fields.chat_id, set by the first DM) — a first DM has no thread, so
    there is nothing to have replied to. Fail-OPEN on a Unipile read error: the
    poller + human approval gate are backstops, and a Unipile outage would fail
    the send itself anyway. Returns True when it SUPPRESSED the send (caller must
    not send)."""
    if node_type != "channel.linkedin_dm":
        return False
    chat_id = (lead.get("custom_fields") or {}).get("chat_id")
    if not chat_id:
        return False  # first DM opening the thread — nothing prior to reply to
    try:
        client = await UnipileClient.for_workspace(workspace_id)
        resp = await client.list_chat_messages(str(chat_id), limit=1)
    except (UnipileError, UnipileNotConfigured) as e:
        log.warning(
            "[reply-gate] lead %s: could not verify thread %s (%s) — proceeding; poller is the backstop",
            lead["id"], chat_id, e,
        )
        return False
    items = resp.get("items") if isinstance(resp, dict) else None
    if not items:
        return False
    newest = items[0]
    # is_sender: 1 = our seat sent it, 0 = inbound. Require an EXPLICIT inbound
    # flag — never guess a missing field into a reply, never read our own send as one.
    if newest.get("is_sender") != 0:
        return False  # newest is our own outbound — no pending reply, proceed
    # The contact has replied since our last message → suppress this send + stop.
    contact_id = lead.get("contact_id")
    msg_id = newest.get("id")
    if contact_id:
        # Record the reply + wake any OTHER waiting leads for this contact (a
        # sibling sequence). Idempotent on the provider message id, so the poller
        # catching the same reply later collapses to one message.received.
        await inbound_reply.process_reply(
            workspace_id, str(contact_id), newest.get("text") or "",
            channel="linkedin", source_message_id=str(msg_id) if msg_id else None,
            correlation_id=correlation_id,
        )
    await _terminalize_lead(workspace_id, str(lead["id"]), "completed", correlation_id)
    log.info(
        "[reply-gate] lead %s: send SUPPRESSED — contact replied (newest thread msg inbound); sequence halted",
        lead["id"],
    )
    return True


async def _gate_send(
    workspace_id: str,
    lead: dict,
    node: dict,
    workflow_id: str | None,
    correlation_id: str | None,
) -> bool:
    """Hold or allow an outbound send against the CAMPAIGN's window + daily cap.

    Returns True when the lead was HELD (parked 'waiting' + a delayed __retry__
    scheduled to re-evaluate this same node) — the caller must then return without
    sending. Returns False when the send may proceed. The lead is never DROPPED;
    a capped/out-of-window send is deferred, exactly like the B6 schedule hold.

    Account-level caps are enforced earlier, at selection (build_command's
    pick_lru excludes over-cap seats); this is the campaign-level throttle on top
    — a send must clear BOTH. The increment happens on the confirmed send in
    handle_transition, so a held/failed send never consumes capacity."""
    controls = await _workflow_send_controls(workspace_id, workflow_id)
    if not controls:
        return False

    tz_name = controls.get("timezone") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now_local = datetime.now(tz)

    # (1) business-hours window — hold until the next in-window moment.
    earliest = controls.get("earliest_hour")
    latest = controls.get("latest_hour")
    if send_policy.window_is_configured(earliest, latest, controls.get("days_of_week")):
        days = controls.get("days_of_week")
        hold = send_policy.compute_window_hold_seconds(now_local, int(earliest), int(latest), days)
        if hold > 0:
            await _hold_send(workspace_id, lead, node, correlation_id, hold, reason="window")
            return True

    # (2) campaign daily cap — count in the workflow's business day. A rolled-over
    # counter (day_anchor != today) reads as 0; at/over cap holds until midnight.
    daily_cap = controls.get("daily_cap")
    if daily_cap and int(daily_cap) > 0:
        today_local = now_local.date()
        if send_policy.is_over_cap(
            int(controls.get("sends_today") or 0), int(daily_cap),
            controls.get("day_anchor"), today_local,
        ):
            hold = send_policy.next_reset_seconds(now_local, "day")
            await _hold_send(workspace_id, lead, node, correlation_id, hold, reason="daily_cap")
            return True

    # (3) SEND-SPACE-001 — inter-send spacing. The finest-grained throttle: once
    # inside the window and under cap, trickle sends out with a jittered gap so a
    # cohort approved/released together doesn't burst from one seat. Fails OPEN —
    # any error proceeds unspaced (never halts a send).
    try:
        if await _spacing_hold(workspace_id, lead, node, workflow_id, controls, correlation_id):
            return True
    except Exception:  # noqa: BLE001 — spacing must never halt a send
        log.exception("send-spacing errored for lead %s; proceeding unspaced", lead.get("id"))

    return False


async def _spacing_hold(
    workspace_id: str,
    lead: dict,
    node: dict,
    workflow_id: str | None,
    controls: dict,
    correlation_id: str | None,
) -> bool:
    """Hold this send so a cohort trickles out with a jittered gap. True = HELD.

    Reserve-once, release-on-retry: the first pass atomically advances the
    campaign's next_send_at by one jittered gap and records THIS send's slot on
    the lead (custom_fields._spacing_send_at); the delayed __retry__ re-enters
    here, sees the slot has arrived, clears it, and lets the send proceed. The
    per-lead marker makes redelivery idempotent — a redelivered first pass is
    treated as a retry and never re-reserves."""
    spacing = int(controls.get("send_spacing_seconds") or 0)
    if spacing <= 0 or not workflow_id:
        return False

    now = datetime.now(UTC)
    cf = lead.get("custom_fields") or {}
    if isinstance(cf, str):
        try:
            cf = json.loads(cf)
        except (TypeError, ValueError):
            cf = {}

    existing = cf.get("_spacing_send_at")
    if existing:
        try:
            slot = datetime.fromisoformat(str(existing))
        except (TypeError, ValueError):
            slot = None
        if slot is not None:
            if slot.tzinfo is None:
                slot = slot.replace(tzinfo=UTC)
            remaining = (slot - now).total_seconds()
            if remaining > 1.0:
                # A retry fired ahead of the reserved slot — keep holding.
                await _hold_send(workspace_id, lead, node, correlation_id, remaining, reason="spacing")
                return True
            # SPACE-STALE-001: a slot only means "your turn" for as long as the
            # send it was reserved for is still the one happening. A marker
            # outlives its send whenever the lead leaves this node another way —
            # an approval, a reply gate, a graph edit, an operator recovery — and
            # nothing ever cleared it. On the lead's NEXT send that abandoned
            # marker read as "slot reached", so the send released immediately
            # and never reserved a new one: spacing silently did not apply.
            # Measured on 2026-08-20 — ten Campaign 2 invites went out two
            # seconds apart against a 600s setting, every one of them carrying a
            # marker days old, and the campaign clock advanced by a single gap.
            # Only a slot near its reserved moment is genuinely reached; an older
            # one is abandoned and has to queue again like any other send.
            if remaining > -float(spacing):
                await _clear_spacing_slot(workspace_id, str(lead["id"]))
                return False
            log.info(
                "lead %s: abandoned spacing slot from %s (%.0fs stale) — re-queuing",
                lead["id"], slot.isoformat(), -remaining,
            )
            await _clear_spacing_slot(workspace_id, str(lead["id"]))
            # fall through and reserve a fresh slot below

    # First pass: reserve this send's slot by advancing the campaign clock.
    jitter = int(controls.get("send_spacing_jitter_pct") or 0)
    gap = send_policy.jittered_gap_seconds(float(spacing), jitter, random.uniform(-1.0, 1.0))
    assigned = await _reserve_spacing_slot(workspace_id, workflow_id, gap)
    if assigned is None:
        return False  # workflow row vanished — fail open (send now)
    if assigned.tzinfo is None:
        assigned = assigned.replace(tzinfo=UTC)
    hold = (assigned - now).total_seconds()
    if hold <= 1.0:
        return False  # first in the cohort — clock advanced, send now
    await _set_spacing_slot(workspace_id, str(lead["id"]), assigned)
    await _hold_send(workspace_id, lead, node, correlation_id, hold, reason="spacing")
    return True


async def _reserve_spacing_slot(
    workspace_id: str, workflow_id: str, gap_seconds: float
) -> datetime | None:
    """Atomically advance omni_workflows.next_send_at by one gap and return the
    slot assigned to THIS send (the pre-advance value, clamped to now). The row
    lock serialises concurrent reservations so each send gets a distinct slot."""
    async with system_scope():
        row = await fetch_one(
            """
            UPDATE omni_workflows
            SET next_send_at = GREATEST(COALESCE(next_send_at, NOW()), NOW())
                               + make_interval(secs => $3),
                updated_at = NOW()
            WHERE id = $1 AND workspace_id = $2
            RETURNING next_send_at - make_interval(secs => $3) AS assigned_slot
            """,
            workflow_id, workspace_id, float(gap_seconds),
        )
    return row["assigned_slot"] if row else None


async def _set_spacing_slot(workspace_id: str, lead_id: str, slot: datetime) -> None:
    """Record this send's reserved slot on the lead so the delayed retry releases
    at the right moment (and a redelivered first pass is treated as a retry)."""
    async with system_scope():
        await execute(
            "UPDATE omni_leads SET custom_fields = "
            "COALESCE(custom_fields,'{}'::jsonb) || jsonb_build_object('_spacing_send_at', $3::text) "
            "WHERE id=$1 AND workspace_id=$2",
            lead_id, workspace_id, slot.isoformat(),
        )


async def _clear_spacing_slot(workspace_id: str, lead_id: str) -> None:
    """Drop the spacing marker once the slot is reached so the next send node for
    this lead reserves a fresh slot."""
    async with system_scope():
        await execute(
            "UPDATE omni_leads SET custom_fields = "
            "(COALESCE(custom_fields,'{}'::jsonb) - '_spacing_send_at') "
            "WHERE id=$1 AND workspace_id=$2",
            lead_id, workspace_id,
        )


async def _hold_send(
    workspace_id: str,
    lead: dict,
    node: dict,
    correlation_id: str | None,
    hold_seconds: float,
    reason: str,
) -> None:
    """Park a lead 'waiting' and schedule a delayed __retry__ that re-fires this
    same node once the hold elapses — the B6 pattern, reused for cap/window. The
    dedupe marker is keyed on (node, reset bucket) so a redelivered hold collapses
    but a genuinely later retry (next bucket) still fires (send_policy.cap_hold_marker)."""
    log.info(
        "lead %s: send held %.0fs (%s) at node %s",
        lead["id"], hold_seconds, reason, node["id"],
    )
    await _advance_lead(workspace_id, str(lead["id"]), str(node["id"]), status="waiting")
    reset_ts = datetime.now(UTC).timestamp() + hold_seconds
    await _emit_synthetic_result(
        workspace_id, str(lead["id"]), str(node["id"]), "__retry__",
        correlation_id, delay_seconds=hold_seconds,
        extra_metadata=send_policy.cap_hold_marker(str(node["id"]), reset_ts),
    )


async def _workflow_local_date(workspace_id: str, workflow_id: str | None):
    """'Today' in the workflow's timezone — the business-day basis for the
    campaign daily cap. Shared by _gate_send (cap check) and the increment so
    both agree on when the day rolls over."""
    tz_name = await _workflow_timezone(workspace_id, workflow_id)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


async def _increment_send_counters(
    workspace_id: str,
    sending_account_id: str,
    workflow_id: str | None,
    command_id: str,
) -> None:
    """Bump the sending account's (and campaign's) rate counters on a confirmed
    send, exactly once. The claim ledger (omni_send_count_claims, command-keyed)
    makes the increment idempotent under Kafka/Flink at-least-once redelivery: the
    INSERT … ON CONFLICT DO NOTHING wins on the first delivery only; a redelivery
    finds the claim and skips. The counter UPDATEs reset-on-rollover atomically
    (CASE on the anchor) so a new day/hour starts the count at 1 — the same lazy
    reset send_policy.effective_count models.

    A command_id is required (it's the dedupe key); a synthetic/missing one is a
    bug upstream — skip rather than double-count every redelivery."""
    if not command_id:
        log.warning("send-count: no command_id for account %s; skipping increment", sending_account_id)
        return

    claim_id = send_policy.increment_claim_id(command_id)
    async with system_scope():
        claimed = await fetch_one(
            "INSERT INTO omni_send_count_claims (claim_id) VALUES ($1) "
            "ON CONFLICT (claim_id) DO NOTHING RETURNING claim_id",
            claim_id,
        )
        if not claimed:
            log.info("send-count: %s already counted; skipping duplicate", claim_id)
            return

        now = datetime.now(UTC)
        utc_today = now.date()
        hour_bucket = now.replace(minute=0, second=0, microsecond=0)
        # Account counters: daily + hourly, each reset when its anchor rolls over.
        # Anchored to the UTC business day — the SAME basis pick_lru uses when it
        # excludes over-cap seats at selection (build_command), so selection and
        # increment agree on which day a send counts toward.
        await execute(
            "UPDATE omni_sending_accounts SET "
            "sends_today = CASE WHEN day_anchor = $2 THEN sends_today + 1 ELSE 1 END, "
            "day_anchor = $2, "
            "sends_this_hour = CASE WHEN hour_anchor = $3 THEN sends_this_hour + 1 ELSE 1 END, "
            "hour_anchor = $3, "
            "last_used_at = NOW(), updated_at = NOW() "
            "WHERE id = $1 AND workspace_id = $4",
            sending_account_id, utc_today, hour_bucket, workspace_id,
        )
        # Campaign daily counter — only when the send is attributed to a workflow.
        # Anchored to the workflow's TIMEZONE business day so the increment and
        # _gate_send's cap check (which uses workflow-tz "today") agree on the
        # reset boundary — otherwise a counter written in UTC and checked in a
        # local tz would disagree near midnight and reset at the wrong time.
        if workflow_id:
            tz_today = await _workflow_local_date(workspace_id, workflow_id)
            await execute(
                "UPDATE omni_workflows SET "
                "sends_today = CASE WHEN day_anchor = $2 THEN sends_today + 1 ELSE 1 END, "
                "day_anchor = $2, updated_at = NOW() "
                "WHERE id = $1 AND workspace_id = $3",
                workflow_id, tz_today, workspace_id,
            )


async def _compute_flow_delay_seconds(workspace_id: str, node: dict, lead: dict | None = None) -> float:
    """Seconds a flow.delay / flow.wait_until node should hold the lead.

    flow.delay: amount × unit, optionally ±jitter_pct% (deterministic per
    lead+node — anti-detection, see send_policy.jittered_seconds).
    flow.wait_until: seconds until the next moment inside the configured
    business-hours window (earliest_hour ≤ local hour < latest_hour, on an
    allowed weekday), evaluated in the workflow's timezone. 0 if the window is
    open right now."""
    from datetime import timedelta

    cfg = node.get("config") or {}
    node_type = node.get("node_type")

    if node_type == "flow.delay":
        amount = int(cfg.get("amount") or 0)
        unit = cfg.get("unit") or "hours"
        base = float(max(0, amount) * _DELAY_UNIT_SECONDS.get(unit, 3600))
        jitter_pct = int(cfg.get("jitter_pct") or 0)
        if jitter_pct > 0 and lead is not None:
            seed_key = f"{lead.get('id')}:{node.get('id')}"
            return send_policy.jittered_seconds(base, jitter_pct, seed_key)
        return base

    # flow.wait_until
    earliest = int(cfg.get("earliest_hour", 9))
    latest = int(cfg.get("latest_hour", 17))
    days = cfg.get("days_of_week") or [0, 1, 2, 3, 4]
    try:
        tz = ZoneInfo(await _workflow_timezone(workspace_id, node.get("workflow_id")))
    except Exception:  # noqa: BLE001 — bad tz string → UTC
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    # Search forward up to 8 days for the first minute the window is open.
    for day_offset in range(0, 8):
        d = now + timedelta(days=day_offset)
        if d.weekday() not in days:
            continue
        window_open = d.replace(hour=earliest, minute=0, second=0, microsecond=0)
        window_close = d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=latest)
        if day_offset == 0 and now >= window_open and now < window_close:
            return 0.0  # already inside the window
        if d >= now and window_open >= now:
            return max(0.0, (window_open - now).total_seconds())
    return 0.0  # no matching day found in a week → don't hold


# Intent-event suffixes the dispatcher recognises (must match dispatcher._is_intent).
_INTENT_SUFFIXES = (".queued", ".requested")


def _is_intent_event(event_type: str) -> bool:
    return bool(event_type) and event_type.endswith(_INTENT_SUFFIXES)


def _classify_emitted_events(events: list[dict]) -> str:
    """Classify what a non-muscle node's emitted events mean for advancement:

      'projection_only' — no intent events; the events are facts for the
          projector (e.g. contact.tag_added). The lead should advance locally
          via a synthetic result, exactly like a condition/flow node.
      'routable_intent' — every intent event is dispatcher-routable (carries
          channel=='http_call'; the only route left for a non-muscle node). The
          muscle result will drive the next transition; do nothing here.
      'dead_on_arrival' — emits an intent the dispatcher can't route. The lead
          would stall silently (CONTRACT-001) — caller errors it instead.
    """
    intents = [e for e in events if _is_intent_event(e.get("event_type") or "")]
    if not intents:
        return "projection_only"
    if all((e.get("payload") or {}).get("channel") == "http_call" for e in intents):
        return "routable_intent"
    return "dead_on_arrival"


async def _already_sent_this_node(workspace_id: str, lead_id: str, node_id: str) -> bool:
    """SEND-ONCE-001: has THIS lead already CONFIRMED a send on THIS node?

    A LinkedIn invite/DM is a once-per-lead action, but the invite node can be
    re-entered by a stale hold/retry redelivery or by an orchestrator ``__retry__``
    emitted for a send that already reported ``sent`` — each re-entry re-dispatches
    the intent, so the seat burns another provider API call for one logical send.
    LinkedIn dedupes the message itself, but the repeated invite calls are a
    ban-risk pattern (observed ~3x/lead on C2 before this guard).

    Distinct from DEDUP-SEND-001 (``_dedupe_send``), which suppresses re-contacting
    a person ANOTHER lead already messaged and deliberately EXCLUDES the lead's own
    sends (so M1 doesn't block M2). This guards the lead's OWN re-entry of the SAME
    node. A DM sequence is unaffected — M1/M2/M3 are distinct node ids. A failed
    send leaves no ``sent`` row, so a genuine retry still proceeds."""
    async with system_scope():
        row = await fetch_one(
            "SELECT 1 FROM omni_send_outcomes "
            "WHERE workspace_id=$1 AND lead_id=$2 AND node_id=$3 AND status='sent' LIMIT 1",
            workspace_id, lead_id, node_id,
        )
    return row is not None


async def _resume_after_confirmed_send(
    workspace_id: str, lead: dict, node: dict, correlation_id: str | None
) -> bool:
    """SEND-ONCE-002: dropping a duplicate dispatch must not STRAND the lead.

    SEND-ONCE-001 refuses to re-dispatch a node this lead already sent. That is
    right for the common case — a stale redelivery arriving AFTER the lead moved
    on — but it was a bare ``return``, so a lead still parked ON the send node
    stayed there forever: every later re-fire hits the same guard, and no other
    path advances it. Observed live 2026-08-14: 13 C1/C2 leads whose invite or DM
    had genuinely reached a real prospect but whose sequence never resumed. The 8
    invite cases could never reach ``event.invite_accepted``, so even if those
    people accepted, no DM would ever have been sent.

    A lead sitting on a send node that already has a confirmed ``sent`` outcome is
    always an anomaly — waiting for acceptance or a reply happens on
    ``event.invite_accepted`` / ``condition.replied``, never on the send node — so
    the recovery is unambiguous: route it down the same ``sent`` edge a real
    success takes, or terminalize honestly at a leaf.

    Returns True when the lead was stranded and has been resumed; False when it
    had already advanced (an ordinary stale redelivery, correctly dropped).
    """
    if str(lead.get("current_node_id") or "") != str(node["id"]):
        return False
    sent_edge = await _outgoing_edge(workspace_id, str(node["id"]), "sent")
    if sent_edge:
        await _advance_and_fire(
            workspace_id, str(lead["id"]), str(sent_edge["target_node_id"]), correlation_id
        )
    else:
        await _terminalize_lead(
            workspace_id, str(lead["id"]), _leaf_terminal_status("sent"), correlation_id
        )
    return True


async def _fire_node(workspace_id: str, lead: dict, contact: dict | None, node: dict, correlation_id: str | None) -> None:
    """Run the target node's execute() and route its output.

    Side-effecting nodes emit intent events -> dispatcher -> muscle.
    Condition/flow nodes return a handle with no muscle hop -> we publish a
    synthetic result so the orchestrator emits the next transition.
    """
    # SPINE-1 backstop: mint the run identity HERE if it never existed, so every
    # event/ctx/synthetic this fire produces shares ONE correlation_id. Without
    # a single mint point, each node's own `ctx.correlation_id or uuid4()`
    # fallback fired independently and fan-out children fragmented the trace.
    correlation_id = correlation_id or str(uuid.uuid4())
    node_type = node["node_type"]
    try:
        _manifest, execute_fn = noderegistry.get(node_type)
    except KeyError:
        log.warning("target node type %r not in registry; stopping lead", node_type)
        await _terminalize_lead(workspace_id, str(lead["id"]), "errored", correlation_id)
        return

    # CONTRACT-006: surface the contact's most recent inbound (reply) timestamp
    # so condition.replied can evaluate against real data. The node itself has no
    # DB handle — the worker is the place with one (same pattern as has_tag
    # reading custom_fields.tags). Cheap single-row lookup, only when needed.
    last_inbound_at = None
    if node_type == "condition.replied" and lead.get("contact_id"):
        # CMP8: honour the node's optional `channel` filter — "did they reply on
        # email specifically?" must not match a LinkedIn reply. The node has no DB
        # handle, so the worker reads its config and filters the query.
        replied_channel = (node.get("config") or {}).get("channel")
        async with system_scope():
            if replied_channel:
                row = await fetch_one(
                    "SELECT MAX(occurred_at) AS last_inbound FROM omni_messages "
                    "WHERE workspace_id=$1 AND contact_id=$2 AND direction='inbound' AND channel=$3",
                    workspace_id,
                    lead["contact_id"],
                    replied_channel,
                )
            else:
                row = await fetch_one(
                    "SELECT MAX(occurred_at) AS last_inbound FROM omni_messages "
                    "WHERE workspace_id=$1 AND contact_id=$2 AND direction='inbound'",
                    workspace_id,
                    lead["contact_id"],
                )
        last_inbound_at = (row or {}).get("last_inbound")

    # Company knowledge-graph resolution for crm.resolve_company. The node has no
    # DB handle, so the worker resolves+dedups the company here and injects the
    # result into custom_fields.company_resolution (same pattern as replied).
    node_custom_fields = dict(lead.get("custom_fields") or {})
    if node_type == "crm.resolve_company":
        cfg = node.get("config") or {}
        item_field = cfg.get("item_field") or "item"
        company_row = node_custom_fields.get(item_field) or {}
        raw_name = (company_row.get("company_name") or "").strip()
        if raw_name:
            description = company_row.get("description") or ""
            industry = company_row.get("industry") or company_row.get("sector") or ""
            employee_count = company_row.get("employee_count")
            async with system_scope():
                resolved = await company_kg.resolve_company(
                    workspace_id,
                    raw_name,
                    industry=industry or None,
                    employee_count=employee_count,
                    domain=company_row.get("company_url") or None,
                )
                # Local filter (blocklist / employee cap / enterprise / org type).
                passed, reason = await company_kg.filter_company(
                    workspace_id,
                    resolved.name,
                    description=description,
                    industry=industry,
                    employee_count=employee_count,
                )
                if not passed and resolved.screening_status != "rejected":
                    await company_kg.set_screening_status(workspace_id, resolved.id, "rejected")
                # Signal scoring from this job's title/description.
                title = company_row.get("title") or company_row.get("job_title") or ""
                role_count = int(company_row.get("role_count") or 1)
                total, signals = company_kg.score_signals(title, description, role_count=role_count)
                if signals:
                    await company_kg.persist_signals(workspace_id, resolved.id, signals, "naukri")
            node_custom_fields["company_resolution"] = {
                "company_id": resolved.id,
                "name": resolved.name,
                "screening_status": "rejected" if not passed else resolved.screening_status,
                "people_discovered": resolved.people_discovered,
                "created": resolved.created,
                "filter_passed": passed,
                "filter_reason": reason,
                "signal_score": total,
            }

    ctx = noderegistry.NodeContext(
        workspace_id=workspace_id,
        workflow_id=str(node.get("workflow_id") or lead.get("workflow_id") or ""),
        node_id=str(node["id"]),
        config=node.get("config") or {},
        lead={
            **(contact or {}),
            "id": str(lead["id"]),
            "contact_id": lead.get("contact_id"),
            "custom_fields": node_custom_fields,
            "last_inbound_at": last_inbound_at.isoformat() if last_inbound_at else None,
        },
        correlation_id=correlation_id,
    )
    result = await execute_fn(ctx)

    # Decision B (SM-2): a node that reports an error must NOT advance past its
    # own failure. Nodes signal local failure via result.error (e.g. add_tag's
    # TAG_MISSING_CONTACT, create_contact's CONTACT_REQUIRES_EMAIL_OR_LINKEDIN,
    # wait_until's invalid window) — previously this field was never inspected
    # here, so the lead sailed on as if the node succeeded and the error was
    # logged nowhere. Route the operator's on_error edge if wired; otherwise
    # terminalize 'errored' (which also accounts a fan-out child at its parent's
    # barrier instead of hanging it). The node's events are intentionally NOT
    # published on the error path — an errored node's side-effects don't ship.
    if result.error:
        err_edge = await _outgoing_edge(workspace_id, str(node["id"]), "on_error")
        if err_edge:
            log.warning(
                "node %s (%s) errored for lead %s: %s — routing on_error edge",
                node["id"], node_type, lead["id"], result.error,
            )
            await _advance_and_fire(workspace_id, str(lead["id"]), str(err_edge["target_node_id"]), correlation_id)
        else:
            log.error(
                "node %s (%s) errored for lead %s: %s — no on_error edge; lead errored",
                node["id"], node_type, lead["id"], result.error,
            )
            await _terminalize_lead(workspace_id, str(lead["id"]), "errored", correlation_id)
        return

    # B6 — campaign schedule window at the outbound-send seam. A workflow may
    # carry start_at/end_at; an outbound send before start_at is HELD until then
    # (via the orchestrator processing-time timer — the same Flink timer
    # flow.delay uses), and after end_at the lead ENDS (campaign over). Both NULL
    # = always-on. Internal/non-send nodes are never gated. Evaluated before DNC
    # so a held send doesn't even reach the suppression query.
    if node_type in _OUTBOUND_SEND_CHANNELS:
        # SEND-ONCE-001: at-most-once send per (lead, node). A re-fire — a stale
        # hold/retry redelivery, or an orchestrator __retry__ emitted for a send
        # that already reported 'sent' — must NOT re-dispatch the intent. Each
        # re-dispatch burns another provider API call for one logical send
        # (LinkedIn dedupes the message, but the repeated invite calls are a
        # ban-risk pattern — observed ~3x/lead on C2). The confirmed-send ledger
        # is the durable witness; this runs FIRST so a duplicate short-circuits
        # before any schedule/dedupe/gate work and never re-publishes. A HELD send
        # wrote no 'sent' row, so the legitimate hold->retry->send still proceeds;
        # only a re-entry AFTER a confirmed send is dropped.
        if await _already_sent_this_node(workspace_id, str(lead["id"]), str(node["id"])):
            if await _resume_after_confirmed_send(workspace_id, lead, node, correlation_id):
                log.info(
                    "SEND-ONCE-002: lead %s was stranded on already-sent node %s (%s) — "
                    "resumed on 'sent' instead of re-dispatching",
                    lead["id"], node["id"], node_type,
                )
            else:
                log.info(
                    "SEND-ONCE-001: lead %s already sent node %s (%s) — dropping duplicate re-fire",
                    lead["id"], node["id"], node_type,
                )
            return
        workflow_id = str(node.get("workflow_id") or lead.get("workflow_id") or "") or None
        start_at, end_at = await _workflow_schedule(workspace_id, workflow_id)
        now = datetime.now(UTC)
        if end_at is not None and now >= end_at:
            log.info("lead %s: campaign %s ended (end_at=%s) — no send", lead["id"], workflow_id, end_at)
            await _terminalize_lead(workspace_id, str(lead["id"]), "ended", correlation_id)
            return
        if start_at is not None and now < start_at:
            hold_seconds = (start_at - now).total_seconds()
            log.info("lead %s: campaign %s not started — holding %.0fs to start_at", lead["id"], workflow_id, hold_seconds)
            # Park 'waiting' and schedule a delayed __retry__ that RE-FIRES this
            # same channel node once start_at passes (re-evaluating this gate,
            # which then falls through to the real send). The __retry__ dedupe
            # marker is keyed on (node, start_at) so a redelivered hold collapses
            # but a later genuine retry is unaffected.
            await _advance_lead(workspace_id, str(lead["id"]), str(node["id"]), status="waiting")
            await _emit_synthetic_result(
                workspace_id, str(lead["id"]), str(node["id"]), "__retry__",
                correlation_id, delay_seconds=hold_seconds,
                extra_metadata={
                    "command_id": f"sched-hold:{node['id']}",
                    "retry_attempt": int(start_at.timestamp()),
                },
            )
            return

        # DEDUP-SEND-001: skip a send to a contact already messaged on this
        # channel (opt-in per node; default off). Runs BEFORE the cap/window gate
        # and DNC — a send we're going to skip shouldn't consume a cap evaluation
        # or a suppression query. Routes the already_messaged handle (skip_step)
        # or terminalizes the lead (end_lead); returns True when it handled it.
        if await _dedupe_send(
            workspace_id, lead, contact, node, node_type, workflow_id, correlation_id
        ):
            return

        # REPLY-GATE-001: the HARD reply-stop. Before a LinkedIn follow-up DM
        # ships, re-check the thread's authoritative state — if the contact has
        # replied since our last message, suppress the send and halt. This closes
        # the poller's ≤interval race (a reply landing right as the send fires):
        # the send decision itself refuses, regardless of poll latency or an
        # operator approving in the gap.
        if await _reply_gate_send(
            workspace_id, lead, node, node_type, correlation_id
        ):
            return

        # Rate-limit + business-hours gate (campaign-level). Sits between the B6
        # absolute schedule (above, which already resolved workflow_id) and the
        # DNC check (below): a send held here for cap/window shouldn't even reach
        # suppression. Holds the lead (never drops) by re-firing this node after
        # the window opens / cap resets.
        if await _gate_send(workspace_id, lead, node, workflow_id, correlation_id):
            return

    # T1 — DNC enforcement at the outbound-send seam. Before any channel intent
    # ships, re-check the recipient against the workspace suppression list. A
    # suppressed recipient must never be messaged on ANY channel (unsubscribe /
    # competitor / do-not-contact compliance), even if a stale workflow still
    # routes to them. The lead terminates 'suppressed' (a distinct terminal
    # status, visible in Leads/Analytics) and the intent is NOT published.
    #
    # DNC-SKIP-001: match on the RECIPIENT IDENTITY, not only contact_id. A
    # send-channel lead may carry the recipient in its own custom_fields (a
    # discovered person before a contact row exists, or a misbuilt graph routing a
    # company-stage lead to a channel) — those must still be suppression-checked.
    if node_type in _OUTBOUND_SEND_CHANNELS:
        recipient = _suppression_identity(contact, lead)
        # Deliverability P0: email sends consult the durable verification cache.
        # Default rollout policy blocks only known-invalid recipients; campaigns
        # can opt into require_safe or provider-backed require_verified.
        if node_type == "channel.email":
            email = (recipient or {}).get("email")
            policy = (node.get("config") or {}).get("verification_policy") or "block_invalid"
            verification = await email_verification.get_verification(workspace_id, str(email or ""))
            allowed, verification_reason = email_verification.send_decision(verification, policy)
            if not allowed:
                log.warning(
                    "lead %s blocked at %s: email verification policy=%s reason=%s",
                    lead["id"], node["id"], policy, verification_reason,
                )
                await bus.publish_event(
                    workspace_id=workspace_id,
                    event_type="email.send_blocked",
                    entity_type="lead",
                    entity_id=str(lead["id"]),
                    payload={
                        "node_id": str(node["id"]),
                        "policy": policy,
                        "reason": verification_reason,
                        "email": str(email or "").lower(),
                    },
                    correlation_id=correlation_id,
                )
                await _terminalize_lead(
                    workspace_id, str(lead["id"]), "invalid", correlation_id
                )
                return
        async with system_scope():
            blocked, reason = await suppression.is_suppressed(workspace_id, recipient)
        if blocked:
            log.warning(
                "lead %s suppressed at %s (%s) — %s; no send dispatched",
                lead["id"], node["id"], node_type, reason,
            )
            await _terminalize_lead(workspace_id, str(lead["id"]), "suppressed", correlation_id)
            return

    # Publish any intent events the node emitted (channels/sources/http_call).
    if result.events:
        envelopes = []
        for ev in result.events:
            payload = dict(ev.get("payload") or {})
            payload.setdefault("node_id", str(node["id"]))
            payload.setdefault("lead_id", str(lead["id"]))
            envelopes.append(
                {
                    "id": str(uuid.uuid4()),
                    "workspace_id": workspace_id,
                    "event_type": ev["event_type"],
                    "entity_type": ev.get("entity_type", "lead"),
                    "entity_id": ev.get("entity_id") or str(lead["id"]),
                    "payload": payload,
                    "actor_user_id": None,
                    "correlation_id": correlation_id,
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
            )
        await bus.publish_events(envelopes)

    # M3: accrue the company knowledge-graph people cache. When a person reaches
    # crm.create_contact inside the people fan-out, the lead carries the person
    # (custom_fields.item) and the resolved company (custom_fields.company_resolution).
    # Cache the person against that company and mark the company people-discovered,
    # so a future run hits crm.resolve_company's `known` branch and skips paid
    # re-discovery (the KG moat that was previously inert — cache_person had no
    # caller). The node has no DB handle, so the worker does it (same pattern as
    # the resolve_company injection above).
    # CONTACT-CAP-002: crm.create_contact reports goal_capped when the campaign's
    # contact target is already met (it did NOT emit contact.created, so no orphan
    # contact). Terminalize the lead through _terminalize_lead — NOT a bare status
    # write or a side-channel lead.sequence_ended event — so a capped fan-out CHILD
    # still decrements its parent's join barrier (SM-5; a side-channel end would
    # strand the parent in 'waiting' forever). Stamp the goal_cap marker for the
    # Leads/Analytics views. This is the single cap enforcement point (the
    # duplicate projector cap was removed).
    if node_type == "crm.create_contact" and (result.telemetry or {}).get("goal_capped"):
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET custom_fields = COALESCE(custom_fields,'{}'::jsonb) || "
                "jsonb_build_object('goal_cap', jsonb_build_object('metric','contacts','reason','contact_target_reached')), "
                "updated_at=NOW() WHERE id=$1 AND workspace_id=$2",
                str(lead["id"]),
                workspace_id,
            )
        await _terminalize_lead(workspace_id, str(lead["id"]), "ended", correlation_id)
        log.info("lead %s: contact goal cap reached — ended (no contact created)", lead["id"])
        return

    if node_type == "crm.create_contact" and not result.error:
        person = node_custom_fields.get("item") or {}
        resolution = node_custom_fields.get("company_resolution") or {}
        company_id = resolution.get("company_id")
        linkedin_url = person.get("linkedin_url") or (contact or {}).get("linkedin_url")
        if company_id and linkedin_url:
            person_name = " ".join(
                p for p in (person.get("first_name"), person.get("last_name")) if p
            ).strip() or person.get("name") or ""
            async with system_scope():
                await company_kg.cache_person(
                    workspace_id,
                    str(company_id),
                    name=person_name,
                    title=person.get("title") or person.get("headline"),
                    linkedin_url=str(linkedin_url),
                    source=person.get("source") or "discovery",
                )
                await company_kg.mark_people_discovered(workspace_id, str(company_id))
            log.info("KG: cached person for company %s (people_discovered=true)", company_id)

    # CONTRACT-005: a node that parks (flow.human_approval) suspends the lead.
    # Its events were published above (approval.requested -> approvals queue);
    # the lead now WAITS and must not advance. It resumes when the resolve
    # endpoint emits approval.resolved, which arrives as a transition off this
    # node's chosen handle.
    if result.park:
        await _advance_lead(workspace_id, str(lead["id"]), str(node["id"]), status="waiting")
        log.info("lead %s parked at %s (%s)", lead["id"], node["id"], node_type)
        # EVENT-PARK-001: an event.* node parks to await an external signal (open/
        # click/invite-accepted) which the resume bridge (services.event_resume,
        # called from tracking.py / webhooks_in.py) delivers as a transition on the
        # success handle. But the signal may never come — so schedule a timeout
        # escape: a delayed transition on the `timeout` handle (the same processing-
        # time-timer mechanism flow.race's timeout uses). Without this the lead would
        # strand forever if never opened/clicked. The success-handle resume and this
        # timeout race; whichever fires first while the lead is still 'waiting' at
        # this node wins (the loser sees status!=waiting and no-ops).
        timeout_seconds = (result.telemetry or {}).get("timeout_seconds")
        if timeout_seconds:
            await _emit_synthetic_result(
                workspace_id, str(lead["id"]), str(node["id"]), "timeout",
                correlation_id, delay_seconds=float(timeout_seconds),
                extra_metadata={
                    "command_id": f"event-timeout:{node['id']}",
                    "retry_attempt": 0,
                },
            )
            log.info("lead %s: scheduled %ss timeout escape for %s", lead["id"], timeout_seconds, node_type)
        return

    # Decide how the lead advances past this node:
    #   * muscle channel (node_type in NODE_CHANNEL) → a command was/will be
    #     dispatched off the intent event; the muscle's result drives the next
    #     transition. Nothing to do here.
    #   * non-muscle node → classify its emitted events:
    #       - projection_only (no intents, or none at all): a condition/flow
    #         node that chose a handle, or a CRM mutation that emitted facts for
    #         the projector (e.g. contact.tag_added). Advance locally via a
    #         synthetic result.
    #       - routable_intent: every intent is dispatcher-routable (http_call);
    #         the muscle result drives the next transition. Do nothing.
    #       - dead_on_arrival: an intent the dispatcher can't route. The lead
    #         would stall silently (CONTRACT-001). Make it LOUD — error the lead.
    if commands.NODE_CHANNEL.get(node_type) is not None:
        return
    # H1: flow.goal / flow.end are TERMINAL — the lead exits here. Set a distinct
    # terminal status (converted vs ended) directly so a goal-conversion is
    # distinguishable from a dead-end in the Leads view + Analytics, instead of
    # both collapsing to the generic 'completed' the leaf path would assign. No
    # synthetic result is emitted (there is no outgoing edge to follow).
    if node_type in ("flow.goal", "flow.end"):
        terminal_status = "converted" if node_type == "flow.goal" else "ended"
        # _terminalize (not a bare status write): a fan-out CHILD reaching
        # goal/end must still arrive at its parent's join barrier (SM-5), and
        # the claim makes redelivered goal-fires idempotent.
        claimed = await _terminalize_lead(workspace_id, str(lead["id"]), terminal_status, correlation_id)
        log.info("lead %s reached %s -> status=%s", lead["id"], node_type, terminal_status)
        # B7: a conversion is an event worth surfacing on its own — emit
        # lead.converted so the operator is told without having to wire a
        # crm.hot_lead_alert by hand. Gated on `claimed` so a redelivered
        # goal-fire never double-alerts (the claim is the idempotency key).
        if node_type == "flow.goal" and claimed:
            await bus.publish_event(
                workspace_id=workspace_id,
                event_type="lead.converted",
                entity_type="lead",
                entity_id=str(lead["id"]),
                payload={
                    "contact_id": str(lead.get("contact_id")) if lead.get("contact_id") else None,
                    "workflow_id": str(lead.get("workflow_id")) if lead.get("workflow_id") else None,
                    "node_id": str(node["id"]),
                },
                correlation_id=correlation_id,
            )
        return
    # CMP9/CMP10: flow.delay / flow.wait_until must actually HOLD the lead. They
    # advance on the same handle as a projection-only node, but with a non-zero
    # delay so the orchestrator's processing-time timer fires the transition
    # later (the mechanism flow.race's timeout uses). Without this they emitted
    # delay only as telemetry and advanced immediately — a "wait 3 days" fired
    # instantly. The lead parks 'waiting' until the timer releases it.
    if node_type in ("flow.delay", "flow.wait_until"):
        delay_seconds = await _compute_flow_delay_seconds(workspace_id, node, lead)
        if delay_seconds > 0:
            await _advance_lead(workspace_id, str(lead["id"]), str(node["id"]), status="waiting")
        await _emit_synthetic_result(
            workspace_id, str(lead["id"]), str(node["id"]), result.handle, correlation_id,
            delay_seconds=delay_seconds,
        )
        log.info("lead %s holding at %s for %.0fs", lead["id"], node_type, delay_seconds)
        return
    kind = _classify_emitted_events(result.events)
    if kind == "projection_only":
        await _emit_synthetic_result(workspace_id, str(lead["id"]), str(node["id"]), result.handle, correlation_id)
    elif kind == "dead_on_arrival":
        log.error(
            "node %s (%s) emitted unroutable intent event(s) %s — no muscle channel/handler; "
            "marking lead %s errored instead of stalling silently (CONTRACT-001)",
            node["id"],
            node_type,
            [e.get("event_type") for e in result.events],
            lead["id"],
        )
        await _terminalize_lead(workspace_id, str(lead["id"]), "errored", correlation_id)


async def _emit_synthetic_result(
    workspace_id: str,
    lead_id: str,
    node_id: str,
    handle: str,
    correlation_id: str | None,
    delay_seconds: float = 0.0,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """For non-muscle nodes, publish an ExecutionResult-shaped envelope to
    outreach.results so the Flink orchestrator emits the next transition.

    ``delay_seconds`` > 0 schedules the transition for later via the
    orchestrator's processing-time timer (the same mechanism flow.delay uses).
    The orchestrator only delays ``sent`` results, so a delayed synthetic uses
    status='sent'; an immediate one uses 'skipped' (ran, no side effect).
    ``extra_metadata`` is merged into the result metadata — used by the B6
    schedule-hold to carry the (command_id, retry_attempt) the __retry__ re-fire
    path dedupes on."""
    metadata = {
        "workspace_id": workspace_id,
        "node_id": node_id,
        "next_handle": handle,
        "accumulated_delay_seconds": delay_seconds,
        # LEDGER-TRUTH-001: this result did not come from the muscle. A DELAYED
        # synthetic has to claim status='sent' because the orchestrator only
        # applies its timer to 'sent' results, but nothing was actually sent.
        # Without this marker _emit_send_outcome recorded a phantom 'sent' row
        # in omni_send_outcomes for a hold, which (a) inflated every "messages
        # sent" number and (b) poisoned the SEND-ONCE-001 guard, whose query is
        # `status='sent' AND node_id=...` — the mechanism behind the 13 stranded
        # leads of SEND-ONCE-002.
        "synthetic": True,
        # DATAFLOW-001: carry the run identity forward. Without this the
        # orchestrator emits the next transition with correlation_id=None and
        # the downstream node mints a fresh id (`ctx.correlation_id or uuid4`),
        # forking the trace at every condition/flow/synthetic hop.
        "correlation_id": correlation_id,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    result = {
        "command_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "lead_id": lead_id,
        "status": "sent" if delay_seconds > 0 else "skipped",
        "error": None,
        "is_retriable": False,
        "telemetry": {},
        "metadata": metadata,
        "event_type": "result_task",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    # publish to outreach.results via the raw producer
    await bus._producer.send_and_wait(bus.RESULTS_TOPIC, value=result, key=lead_id)  # type: ignore[union-attr]


_ENRICHMENT_IDENTITY_FIELDS = (
    "email",
    "first_name",
    "last_name",
    "company",
    "headline",
    "linkedin_url",
    "phone",
)


def _clean_enrichment_fields(value: object) -> dict[str, str]:
    """Accept only explicit contact identity fields and non-empty strings."""
    if not isinstance(value, dict):
        return {}
    clean: dict[str, str] = {}
    for field in _ENRICHMENT_IDENTITY_FIELDS:
        raw = value.get(field)
        if isinstance(raw, str) and raw.strip():
            clean[field] = raw.strip()
    return clean


def _clean_enrichment_custom_fields(value: object) -> dict[str, object]:
    """Accept simple provider facts that do not belong in contact identity columns."""
    if not isinstance(value, dict):
        return {}
    clean: dict[str, object] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key or len(key) > 120:
            continue
        if isinstance(raw_value, str) and raw_value.strip():
            clean[key] = raw_value.strip()
        elif isinstance(raw_value, (int, float, bool)) and not isinstance(raw_value, bool):
            clean[key] = raw_value
        elif isinstance(raw_value, bool):
            clean[key] = raw_value
        elif isinstance(raw_value, dict):
            clean[key] = raw_value
    return clean


def _enrichment_history(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


async def _apply_enrichment_mutation(
    workspace_id: str,
    lead_id: str,
    envelope: object,
) -> None:
    """Apply one provider result with fill-missing/overwrite and provenance.

    The muscle is not allowed to name database columns directly. It returns one
    typed ``enrichment`` envelope; this function whitelists identity fields,
    locks the lead/contact rows, deduplicates by command id, and records exactly
    which values were received and applied.
    """
    if not isinstance(envelope, dict):
        return
    fields = _clean_enrichment_fields(envelope.get("fields"))
    custom_fields = _clean_enrichment_custom_fields(envelope.get("custom_fields"))
    provider = str(envelope.get("provider") or "unknown")[:80]
    attempt_id = str(envelope.get("attempt_id") or "")[:120]
    merge_policy = "overwrite" if envelope.get("merge_policy") == "overwrite" else "fill_missing"
    observed_at = str(envelope.get("observed_at") or datetime.now(UTC).isoformat())
    provider_metadata = envelope.get("metadata")
    if not isinstance(provider_metadata, dict):
        provider_metadata = {}

    async with system_scope():
        async with acquire() as conn:
            async with conn.transaction():
                lead = await conn.fetchrow(
                    """
                    SELECT contact_id, custom_fields
                    FROM omni_leads
                    WHERE id=$1 AND workspace_id=$2
                    FOR UPDATE
                    """,
                    lead_id,
                    workspace_id,
                )
                if not lead:
                    return

                lead_cf = dict(lead["custom_fields"] or {})
                if custom_fields:
                    lead_cf.update(custom_fields)
                lead_history = _enrichment_history(lead_cf.get("enrichment_history"))
                if attempt_id and any(
                    isinstance(item, dict) and item.get("attempt_id") == attempt_id
                    for item in lead_history
                ):
                    return

                applied: dict[str, str] = {}
                contact_id = lead["contact_id"]
                contact_found = False
                if contact_id:
                    contact = await conn.fetchrow(
                        """
                        SELECT email, first_name, last_name, company, headline,
                               linkedin_url, phone, custom_fields
                        FROM omni_contacts
                        WHERE id=$1 AND workspace_id=$2
                        FOR UPDATE
                        """,
                        contact_id,
                        workspace_id,
                    )
                    if contact:
                        contact_found = True
                        for field, value in fields.items():
                            current = contact[field]
                            if merge_policy == "overwrite" or not (
                                isinstance(current, str) and current.strip()
                            ):
                                applied[field] = value

                        contact_cf = dict(contact["custom_fields"] or {})
                        contact_history = _enrichment_history(contact_cf.get("enrichment_history"))
                        record = {
                            "attempt_id": attempt_id,
                            "provider": provider,
                            "observed_at": observed_at,
                            "merge_policy": merge_policy,
                            "fields_received": sorted(fields),
                            "fields_applied": sorted(applied),
                            "metadata": provider_metadata,
                        }
                        contact_history.append(record)
                        contact_cf["enrichment_history"] = contact_history

                        assignments: list[str] = []
                        args: list[object] = []
                        for field, value in applied.items():
                            args.append(value)
                            assignments.append(f"{field}=${len(args)}")
                        args.append(json.dumps(contact_cf))
                        assignments.append(f"custom_fields=${len(args)}::jsonb")
                        args.extend([contact_id, workspace_id])
                        await conn.execute(
                            f"UPDATE omni_contacts SET {', '.join(assignments)}, updated_at=NOW() "
                            f"WHERE id=${len(args) - 1} AND workspace_id=${len(args)}",
                            *args,
                        )
                if not contact_found:
                    # Before crm.create_contact exists, keep learned identity on
                    # the lead. commands._lead_context lifts these fields into the
                    # next provider command so an ordered stack can build on them.
                    for field, value in fields.items():
                        current = lead_cf.get(field)
                        if merge_policy == "overwrite" or not (
                            isinstance(current, str) and current.strip()
                        ):
                            lead_cf[field] = value
                            applied[field] = value

                record = {
                    "attempt_id": attempt_id,
                    "provider": provider,
                    "observed_at": observed_at,
                    "merge_policy": merge_policy,
                    "fields_received": sorted(fields),
                    "fields_applied": sorted(applied),
                    "metadata": provider_metadata,
                }
                lead_history.append(record)
                lead_cf["enrichment_history"] = lead_history
                await conn.execute(
                    """
                    UPDATE omni_leads
                    SET custom_fields=$1::jsonb, updated_at=NOW()
                    WHERE id=$2 AND workspace_id=$3
                    """,
                    json.dumps(lead_cf),
                    lead_id,
                    workspace_id,
                )


# THREAD-MEMORY-001. Deterministic namespace for an OUTBOUND omni_messages row
# derived from the command that sent it, mirroring how inbound replies key off
# the provider's message id. Redelivery collapses onto the same row instead of
# writing the message twice.
_SENT_MSG_NS = uuid.UUID("2b9c7f41-6a3d-4e58-9f10-7c8d5e2a4b60")

# CHANNEL-VOCAB-001. Two tables, two questions, two vocabularies:
#
#   omni_send_outcomes answers "which ACTION fired" — linkedin_invite,
#   linkedin_dm, linkedin_inmail are all distinct rows and must stay distinct
#   (DEDUP-SEND-001 keys on it; an invite must not suppress a DM).
#
#   omni_messages answers "which CONVERSATION is this part of". A prospect sees
#   one LinkedIn thread; a reply cannot even say which action it answers, which
#   is why all three inbound writers hardcode "linkedin" and condition.replied
#   documents its filter as "(email, linkedin, …)".
#
# Writing the action token into omni_messages would put two names for one
# conversation in the same table: the reply says "linkedin", our send says
# "linkedin_dm", and every consumer that groups a thread by channel splits it in
# two. So the action token is normalised on the way in, and kept in metadata for
# anyone who needs to know which node actually sent it.
_CONVERSATION_CHANNEL = {
    "linkedin_dm": "linkedin",
    "linkedin_inmail": "linkedin",
    "linkedin_invite": "linkedin",
    "linkedin_profile_view": "linkedin",
    "linkedin": "linkedin",
}


def _conversation_channel(action_channel: str | None) -> str:
    """The thread a send belongs to, from the action that sent it.

    Anything unmapped passes through unchanged: email, sms, whatsapp, instagram
    and telegram are already one action per conversation, and an unrecognised
    channel is better recorded honestly than coerced into the wrong thread."""
    token = str(action_channel or "").strip().lower()
    if not token:
        return "unknown"
    return _CONVERSATION_CHANNEL.get(token, token)


async def _record_sent_message(
    workspace_id: str,
    lead_id: str,
    sent: Any,
    command_id: str | None,
    action_channel: str | None = None,
) -> None:
    """Persist a message we actually delivered into ``omni_messages``.

    THREAD-MEMORY-001. The table has carried ``direction IN ('inbound','outbound')``
    since migration 021 but only ever held inbound rows, so nothing in the system
    could answer "what have we already said to this person". ai.compose was
    therefore writing every follow-up blind, and the sent copy survived only in
    LinkedIn itself.

    Only a CONFIRMED delivery reaches here: the muscle emits this alongside the
    chat id, after the NOCHAT-002 guard has already turned a 2xx-with-no-chat-id
    into a skip. A message that never left does not get logged as one.

    The row id is derived from the command id, so a redelivered transition
    collapses onto the same row (there is no command dedupe in front of this)."""
    if not isinstance(sent, dict) or not command_id:
        return
    body = str(sent.get("body") or "").strip()
    if not body:
        return
    async with system_scope():
        lead = await fetch_one(
            "SELECT contact_id, workflow_id FROM omni_leads WHERE id=$1 AND workspace_id=$2",
            lead_id,
            workspace_id,
        )
        if not lead or not lead.get("contact_id"):
            # A discovered person with no contact row yet has nothing to thread
            # the message onto. Nothing to record, and nothing to fail over.
            return
        await execute(
            """
            INSERT INTO omni_messages
                (id, workspace_id, contact_id, channel, direction, body, metadata, occurred_at)
            VALUES ($1, $2, $3, $4, 'outbound', $5, $6::jsonb, NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            str(uuid.uuid5(_SENT_MSG_NS, str(command_id))),
            workspace_id,
            str(lead["contact_id"]),
            _conversation_channel(action_channel),
            body,
            json.dumps({
                "lead_id": str(lead_id),
                "workflow_id": str(lead["workflow_id"]) if lead.get("workflow_id") else None,
                "command_id": str(command_id),
                "chat_id": sent.get("chat_id") or None,
                # the ACTION that sent it, which the conversation token drops
                "action_channel": str(action_channel or "") or None,
            }),
        )


async def _apply_lead_mutations(
    workspace_id: str,
    lead_id: str,
    mutations: dict,
    command_id: str | None = None,
    action_channel: str | None = None,
) -> None:
    """Merge typed muscle-supplied mutations into lead/contact state.

    ``custom_fields`` remains the generic lead-data channel. Enrichment is a
    separate typed envelope because it may update whitelisted contact columns;
    arbitrary muscle-supplied column names are never interpolated.

    ``command_id`` is only needed by mutations that must be idempotent under
    redelivery. This function runs on EVERY delivered transition — there is no
    command-level dedupe in front of it, and Kafka at-least-once redelivery is
    routine — so anything that appends rather than overwrites has to key off it."""
    if not mutations:
        return
    cf = mutations.get("custom_fields")
    if isinstance(cf, dict) and cf:
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET custom_fields = COALESCE(custom_fields,'{}'::jsonb) || $1::jsonb, "
                "updated_at = NOW() WHERE id=$2 AND workspace_id=$3",
                json.dumps(cf),
                lead_id,
                workspace_id,
            )

    await _apply_enrichment_mutation(workspace_id, lead_id, mutations.get("enrichment"))
    await _record_sent_message(
        workspace_id, lead_id, mutations.get("sent_message"), command_id, action_channel
    )

    # CONTRACT-003: persist tag mutations into custom_fields.tags (a JSONB string
    # array). condition.has_tag reads the same location. The ADD_TAG/REMOVE_TAG
    # muscle handlers return lead_mutations.{add_tag|remove_tag: <tag>}; apply
    # them set-wise so re-delivery is idempotent.
    add_tag = mutations.get("add_tag")
    remove_tag = mutations.get("remove_tag")
    if isinstance(add_tag, str) and add_tag:
        async with system_scope():
            await execute(
                """
                UPDATE omni_leads SET custom_fields = jsonb_set(
                    COALESCE(custom_fields,'{}'::jsonb), '{tags}',
                    (
                        SELECT COALESCE(jsonb_agg(DISTINCT t), '[]'::jsonb)
                        FROM jsonb_array_elements_text(
                            COALESCE(custom_fields->'tags','[]'::jsonb) || to_jsonb($1::text)
                        ) AS t
                    ), true
                ), updated_at = NOW()
                WHERE id=$2 AND workspace_id=$3
                """,
                add_tag,
                lead_id,
                workspace_id,
            )
    if isinstance(remove_tag, str) and remove_tag:
        async with system_scope():
            await execute(
                """
                UPDATE omni_leads SET custom_fields = jsonb_set(
                    COALESCE(custom_fields,'{}'::jsonb), '{tags}',
                    (
                        SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
                        FROM jsonb_array_elements_text(COALESCE(custom_fields->'tags','[]'::jsonb)) AS t
                        WHERE t <> $1::text
                    ), true
                ), updated_at = NOW()
                WHERE id=$2 AND workspace_id=$3
                """,
                remove_tag,
                lead_id,
                workspace_id,
            )

    # CONTRACT-3: persist the Unipile handlers' session/marker mutations. The
    # muscle returns lead_mutations like {chat_id|ig_chat_id|tg_chat_id: "<id>"}
    # when send_chat opens a NEW chat, plus marker flips (invited_at /
    # inmail_sent_at: "now") — keys that mirrored columns on the LEGACY leads
    # table. omni_leads has no such columns, and this function used to ignore
    # every key but custom_fields/add_tag/remove_tag, silently dropping them:
    # the opened chat_id never persisted, so EVERY subsequent message opened
    # another brand-new chat instead of continuing the thread. Store them in
    # custom_fields (idempotent jsonb merge); channel nodes read them back from
    # there when rendering the next send's payload.
    markers: dict[str, str] = {}
    for k in ("chat_id", "ig_chat_id", "tg_chat_id", "provider_id", "invited_at", "inmail_sent_at"):
        v = mutations.get(k)
        if isinstance(v, str) and v:
            markers[k] = datetime.now(UTC).isoformat() if v == "now" else v
    if markers:
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET custom_fields = COALESCE(custom_fields,'{}'::jsonb) || $1::jsonb, "
                "updated_at = NOW() WHERE id=$2 AND workspace_id=$3",
                json.dumps(markers),
                lead_id,
                workspace_id,
            )


# PIPELINE-METRICS-001: the omni_pipeline_metrics table + its projector consumer
# (_project_pipeline_metric) + the Analytics "Lead-gen efficiency & cost" panel all
# existed, but NOTHING ever emitted the pipeline.metric event that feeds them — the
# producer leg was never built, so the table was always empty and the panel always
# read "No source runs yet". This emits one delta per source result, keyed by the
# run's correlation_id (ON CONFLICT(run_id) in the projector accumulates), counting
# what the source actually produced. Best-effort: a metrics hiccup must never wedge
# the spine, so every failure is swallowed.
_SOURCE_COMPANY_KEYS = ("companies", "agencies", "items")
_SOURCE_PEOPLE_KEYS = ("people", "persons", "contacts")


def _count_collection(custom_fields: dict, keys: tuple[str, ...]) -> int:
    for k in keys:
        v = custom_fields.get(k)
        if isinstance(v, list):
            return len(v)
    return 0


async def _emit_pipeline_metric(
    workspace_id: str,
    node_type: str,
    run_id: str | None,
    telemetry: dict,
    lead_mutations: dict,
    correlation_id: str | None,
) -> None:
    """Emit a pipeline.metric delta for a SOURCE node's result. run_id = the run's
    correlation_id so the projector accumulates every source in the run into one row.
    Counts come telemetry-first (the muscle's own count) with a fallback to the size
    of the collection the source wrote into custom_fields."""
    if not node_type.startswith("source.") or not run_id:
        return
    cf = (lead_mutations or {}).get("custom_fields") or {}
    companies = int(telemetry.get("companies_extracted") or 0) or _count_collection(cf, _SOURCE_COMPANY_KEYS)
    people = int(telemetry.get("people_found") or telemetry.get("people_extracted") or 0) or _count_collection(
        cf, _SOURCE_PEOPLE_KEYS
    )
    if companies == 0 and people == 0:
        return  # nothing produced — don't write an empty row
    collector = node_type.removeprefix("source.")
    try:
        # 'start' (idempotent) stamps the run + collector; 'delta' carries the counts.
        await bus.publish_event(
            workspace_id=workspace_id,
            event_type="pipeline.metric",
            entity_type="run",
            entity_id=run_id,
            payload={"kind": "start", "collector_source": collector},
            correlation_id=correlation_id,
        )
        await bus.publish_event(
            workspace_id=workspace_id,
            event_type="pipeline.metric",
            entity_type="run",
            entity_id=run_id,
            payload={
                "kind": "delta",
                "collector_source": collector,
                "companies_collected": companies,
                "people_found": people,
                "serper_calls": int(telemetry.get("serper_calls") or 0),
                "claude_calls": int(telemetry.get("claude_calls") or 0),
            },
            correlation_id=correlation_id,
        )
    except Exception:  # noqa: BLE001
        log.exception("failed to emit pipeline.metric for run %s (%s)", run_id, collector)


# LinkedIn sub-action lives in the node config / queued intent, surfaced on the
# result metadata as "mode". Other channels have no sub-mode.
def _send_provider_ids(meta: dict, lead_mutations: dict) -> dict:
    """The provider's own handles for this send, for threading + reconciliation:
    chat_id (DM thread), invitation_id (invite), message_id, provider_id. The
    muscle returns these in lead_mutations (chat_id/provider_id) and result
    details (invitation_id/message_id)."""
    telemetry = meta.get("telemetry") if isinstance(meta.get("telemetry"), dict) else {}
    details = meta.get("details") if isinstance(meta.get("details"), dict) else telemetry
    mutations = lead_mutations or {}
    if isinstance(mutations, dict) and isinstance(mutations.get("custom_fields"), dict):
        mutations = mutations["custom_fields"]
    out: dict[str, str] = {}
    for key in ("chat_id", "ig_chat_id", "tg_chat_id", "provider_id", "invitation_id", "message_id"):
        val = mutations.get(key) or details.get(key)
        if val:
            out[key] = str(val)
    return out


async def _emit_send_outcome(
    workspace_id: str,
    node_type: str,
    lead_id: str,
    lead_row: dict,
    meta: dict,
    lead_mutations: dict,
    correlation_id: str | None,
    firing_node_id: str | None = None,
) -> None:
    """OBSERVABILITY-001: a durable, per-lead, cross-queryable record of EVERY
    outbound send attempt (all channels, not just email) — status, the failure
    REASON, and the provider's handles (chat_id / invitation_id). Without this
    a LinkedIn invite/DM outcome (e.g. a 403 reason) evaporated. Emits a
    `send.outcome` the projector writes to omni_send_outcomes, idempotent on
    (command_id, attempt). Mirrors how enrichment records enrichment_history.

    Also re-emits the email-only `sender.delivery_result` (the deliverability
    transport-health rollup the existing projector/Analytics consume) so that
    surface is unchanged."""
    if node_type not in _OUTBOUND_SEND_CHANNELS:
        return
    # LEDGER-TRUTH-001: only a real provider attempt belongs in the send ledger.
    # A synthetic result is the spine talking to itself (a hold, a delay, a
    # re-fire); recording it as a send makes the ledger claim messages that were
    # never attempted.
    if meta.get("synthetic"):
        return
    status = str(meta.get("status") or "").lower()
    if status not in {"sent", "failed", "skipped"}:
        return
    command_id = str(meta.get("command_id") or "")
    attempt = int(meta.get("retry_attempt") or 0)
    error_detail = str(meta.get("error") or "") or None
    # The muscle's error string is "<code> HTTP <status>: <body>" shaped; keep the
    # whole thing as detail and lift a short code for filtering.
    error_code = (error_detail.split(":", 1)[0].strip()[:120] if error_detail else None)
    try:
        await bus.publish_event(
            workspace_id=workspace_id,
            event_type="send.outcome",
            entity_type="lead",
            entity_id=str(lead_id),
            payload={
                "command_id": command_id,
                "attempt": attempt,
                "channel": node_type.split(".", 1)[-1],
                "mode": meta.get("mode") or (meta.get("telemetry") or {}).get("event"),
                "status": status,
                "lead_id": str(lead_id),
                "contact_id": str(lead_row.get("contact_id")) if lead_row.get("contact_id") else None,
                "workflow_id": str(lead_row.get("workflow_id")) if lead_row.get("workflow_id") else None,
                # SEND-ONCE-001 keys its at-most-once guard on this. The muscle
                # doesn't reliably echo node_id, so fall back to the FIRING node
                # (source_node_id) — the node that produced this outcome — so the
                # ledger row is always attributable to its send node.
                "node_id": str(meta.get("node_id") or firing_node_id or "") or None,
                "sending_account_id": str(meta.get("sending_account_id") or "") or None,
                "provider": meta.get("provider") or (meta.get("telemetry") or {}).get("provider"),
                "provider_status_code": meta.get("provider_status_code") or (meta.get("telemetry") or {}).get("provider_status_code"),
                "error_code": error_code,
                "error_detail": error_detail,
                "provider_ids": _send_provider_ids(meta, lead_mutations),
                "retriable": bool(meta.get("is_retriable")),
            },
            correlation_id=correlation_id,
        )
    except Exception:  # noqa: BLE001 — observability must never wedge the spine
        log.exception("failed to emit send.outcome for lead %s", lead_id)

    # Preserve the email transport-health rollup (unchanged consumers).
    account_id = meta.get("sending_account_id")
    if node_type == "channel.email" and account_id and status in {"sent", "failed"}:
        result_key = f"{command_id}:{attempt}:{status}:{error_code or ''}"
        try:
            await bus.publish_event(
                workspace_id=workspace_id,
                event_type="sender.delivery_result",
                entity_type="sending_account",
                entity_id=str(account_id),
                payload={
                    "result_key": result_key,
                    "command_id": command_id,
                    "status": status,
                    "error_code": error_code,
                    "retriable": bool(meta.get("is_retriable")),
                },
                correlation_id=correlation_id,
            )
        except Exception:  # noqa: BLE001
            log.exception("failed to emit sender.delivery_result for account %s", account_id)


async def _handle_manual_reply_transition(meta: dict, handle: str) -> None:
    """Finalize an inbox one-shot send without advancing a campaign lead.

    Manual replies use a synthetic lead id so a reply can never move or
    terminalize the real campaign lead.  The inbox route creates a durable
    ``queued`` outcome before publishing; this function atomically claims that
    row, records the muscle result, and counts a confirmed send against the
    sending seat.  The queued-row claim makes the path idempotent under Kafka
    redelivery.
    """
    command_id = str(meta.get("command_id") or "")
    if not command_id:
        log.error("manual reply transition without command_id; dropping")
        return

    async with system_scope():
        queued = await fetch_one(
            "SELECT workspace_id, contact_id, workflow_id, channel, sending_account_id "
            "FROM omni_send_outcomes "
            "WHERE command_id=$1 AND attempt=0 AND mode='manual_reply' AND status='queued' "
            "ORDER BY occurred_at DESC LIMIT 1",
            command_id,
        )
    if not queued:
        log.info("manual reply %s already finalized or unknown; skipping", command_id)
        return

    row = dict(queued)
    workspace_id = str(row["workspace_id"])
    echoed_workspace_id = meta.get("workspace_id")
    if echoed_workspace_id and str(echoed_workspace_id) != workspace_id:
        log.error(
            "manual reply workspace mismatch: command=%s echoed=%s actual=%s — refusing",
            command_id,
            echoed_workspace_id,
            workspace_id,
        )
        return

    raw_status = str(meta.get("status") or "").lower()
    status = raw_status if raw_status in {"sent", "failed", "skipped"} else "failed"
    error_detail = str(meta.get("error") or "") or None
    if handle == "__retry__" and status == "failed" and not error_detail:
        error_detail = "manual reply provider failure (automatic replay is disabled)"
    error_code = error_detail.split(":", 1)[0].strip()[:120] if error_detail else None
    telemetry = meta.get("telemetry") if isinstance(meta.get("telemetry"), dict) else {}
    provider_status_code = meta.get("provider_status_code") or telemetry.get("provider_status_code")
    try:
        provider_status_code = int(provider_status_code) if provider_status_code is not None else None
    except (TypeError, ValueError):
        provider_status_code = None
    lead_mutations = meta.get("lead_mutations") if isinstance(meta.get("lead_mutations"), dict) else {}
    provider_ids = _send_provider_ids(meta, lead_mutations)

    # Persist returned thread handles on the real conversation's lead(s), but
    # deliberately leave their journey status/current node untouched.
    mutation_fields = lead_mutations.get("custom_fields")
    if not isinstance(mutation_fields, dict):
        mutation_fields = {
            key: value
            for key, value in lead_mutations.items()
            if key in {"chat_id", "ig_chat_id", "tg_chat_id", "provider_id"} and value
        }
    if mutation_fields and row.get("contact_id"):
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET custom_fields=COALESCE(custom_fields,'{}'::jsonb) || $1::jsonb, "
                "updated_at=NOW() WHERE workspace_id=$2 AND contact_id=$3 "
                "AND ($4::uuid IS NULL OR workflow_id=$4)",
                json.dumps(mutation_fields),
                workspace_id,
                row["contact_id"],
                row.get("workflow_id"),
            )

    account_id = str(row.get("sending_account_id") or "") or None
    if status == "sent" and account_id:
        # A human reply consumes seat capacity, but must not mutate an active
        # campaign's automation cap.  Passing workflow_id=None is intentional.
        await _increment_send_counters(workspace_id, account_id, None, command_id)

    # Finalize only after the idempotent side effects above.  If either raises,
    # the queued row remains retryable; duplicate delivery is safe because the
    # counter has its own command-id claim and JSONB merge is idempotent.
    async with system_scope():
        finalized = await fetch_one(
            "UPDATE omni_send_outcomes SET status=$1, provider=$2, provider_status_code=$3, "
            "error_code=$4, error_detail=$5, provider_ids=$6::jsonb, retriable=$7, "
            "occurred_at=NOW() "
            "WHERE workspace_id=$8 AND command_id=$9 AND attempt=0 "
            "AND mode='manual_reply' AND status='queued' RETURNING id",
            status,
            meta.get("provider") or telemetry.get("provider"),
            provider_status_code,
            error_code,
            error_detail,
            json.dumps(provider_ids),
            bool(meta.get("is_retriable")),
            workspace_id,
            command_id,
        )
    if not finalized:
        return

    try:
        await bus.publish_event(
            workspace_id=workspace_id,
            event_type="send.outcome",
            entity_type="contact",
            entity_id=str(row.get("contact_id") or command_id),
            payload={
                "command_id": command_id,
                "attempt": 0,
                "channel": row.get("channel"),
                "mode": "manual_reply",
                "status": status,
                "lead_id": None,
                "contact_id": str(row["contact_id"]) if row.get("contact_id") else None,
                "workflow_id": str(row["workflow_id"]) if row.get("workflow_id") else None,
                "node_id": None,
                "sending_account_id": account_id,
                "provider": meta.get("provider") or telemetry.get("provider"),
                "provider_status_code": provider_status_code,
                "error_code": error_code,
                "error_detail": error_detail,
                "provider_ids": provider_ids,
                "retriable": bool(meta.get("is_retriable")),
            },
            correlation_id=meta.get("correlation_id"),
        )
    except Exception:  # noqa: BLE001 — the durable row is already finalized
        log.exception("failed to emit manual reply outcome for command %s", command_id)


async def _claim_parked_node(workspace_id: str, lead_id: str, node_id: str) -> bool:
    """RACE-PARK-001: atomically claim a parked ('waiting') lead at exactly
    `node_id`, flipping it waiting→active. Returns True only for the ONE caller
    that wins the row.

    A lead parked at an event.* / flow.race node is a target for two concurrent
    transitions that share the same source node but route differently:
      - the awaited signal's resume (e.g. invite-accepted webhook → 'accepted'),
      - the EVENT-PARK-001 / race timeout escape → 'timeout'.
    Both must not advance the lead — that double-sends down two branches. The
    timeout path's prior check-then-act (read status, then cancel siblings /
    reset barriers) left a window where it could run those side effects on a
    lead the resume had already legitimately advanced. This single atomic claim
    closes it: whoever flips waiting→active first owns the parked node; the
    loser claims nothing and no-ops. Idempotent under Kafka redelivery."""
    async with system_scope():
        won = await fetch_one(
            "UPDATE omni_leads SET status='active', updated_at=NOW() "
            "WHERE id=$1 AND workspace_id=$2 AND status='waiting' "
            "AND current_node_id IS NOT DISTINCT FROM $3 RETURNING id",
            lead_id,
            workspace_id,
            str(node_id),
        )
    return won is not None


async def handle_transition(t: dict) -> None:
    lead_id = t.get("lead_id")
    handle = t.get("handle") or "default"
    source_node_id = t.get("source_node_id")
    meta = t.get("metadata") or {}
    echoed_workspace_id = meta.get("workspace_id")
    # SPINE-1: mint the run identity ONCE per transition if upstream lost it —
    # everything this handling touches (fired nodes, fan-out children,
    # synthetics) shares one correlation_id instead of each minting its own.
    correlation_id = meta.get("correlation_id") or str(uuid.uuid4())
    lead_mutations = meta.get("lead_mutations") or {}
    if source_node_id == "inbox-reply":
        await _handle_manual_reply_transition(meta, handle)
        return
    if not (lead_id and source_node_id):
        return

    # DATAFLOW-003: the muscle echoes workspace_id through its metadata, but the
    # muscle is not trusted to assert tenancy. The lead row is the source of
    # truth — derive workspace_id from it by lead_id, and only trust the echoed
    # value as a cross-check. A mismatch means a tenancy bug or a tampered
    # result; refuse the transition rather than acting in the echoed tenant.
    async with system_scope():
        row = await fetch_one(
            # DEDUP-DATA-001: contact_id MUST be selected — _emit_send_outcome reads
            # lead_row["contact_id"] to stamp the send ledger, and DEDUP-SEND-001's
            # guard matches prior sends on it. Omitting it wrote every outcome with a
            # NULL contact_id, so dedupe could never find a prior send and was inert.
            "SELECT workspace_id, status, contact_id, parent_lead_id, origin_node_id, workflow_id "
            "FROM omni_leads WHERE id=$1",
            lead_id,
        )
    workspace_id = str(row["workspace_id"]) if row else None
    if not workspace_id:
        log.warning("transition for unknown lead=%s; dropping", lead_id)
        return
    if echoed_workspace_id and str(echoed_workspace_id) != workspace_id:
        log.error(
            "transition workspace mismatch: lead=%s echoed=%s actual=%s — refusing",
            lead_id,
            echoed_workspace_id,
            workspace_id,
        )
        return

    # Decision A: the terminal-state guard. A finished lead (completed/errored/
    # cancelled/converted/ended) must never be advanced, re-fired, or resurrected
    # by a late or redelivered transition — Kafka at-least-once and the Flink
    # AT_LEAST_ONCE sink make such deliveries routine. Without this, __retry__
    # re-fired errored leads (SM-1) and in-flight muscle results resurrected
    # cancelled race losers (SM-6). One carve-out: a terminal CHILD's redelivered
    # transition still re-attempts its parent's claim-gated barrier RELEASE
    # (count=False — never recounts). That is the crash-recovery path: a worker
    # dying between the barrier increment and the release leaves the offset
    # uncommitted, so the redelivery is exactly what recovers the release.
    if (row.get("status") or "") in TERMINAL_STATUSES:
        if row.get("parent_lead_id") and row.get("origin_node_id"):
            tgt = await _target_node(workspace_id, str(source_node_id), handle)
            await _barrier_arrive(
                workspace_id,
                str(row["parent_lead_id"]),
                str(row["origin_node_id"]),
                str(lead_id),
                correlation_id,
                join_arrival=bool(tgt and tgt.get("node_type") == "flow.join"),
                count=False,
            )
        log.info(
            "transition for terminal lead %s (status=%s, handle=%s) dropped",
            lead_id, row.get("status"), handle,
        )
        return

    # Apply any column mutations the muscle returned (e.g. a source handler
    # writing custom_fields[companies]) before deciding where to go next, so a
    # for_each or downstream node sees the freshly merged data.
    if lead_mutations:
        await _apply_lead_mutations(
            workspace_id,
            lead_id,
            lead_mutations,
            command_id=meta.get("command_id"),
            action_channel=meta.get("channel"),
        )

    # PIPELINE-METRICS-001: a source node's result feeds the lead-gen efficiency
    # rollup. We know the firing node from source_node_id; emit one metric delta
    # for the run (best-effort, never wedges the spine).
    firing_node = await _node_row(workspace_id, str(source_node_id))
    if firing_node and str(firing_node.get("node_type") or "").startswith("source."):
        await _emit_pipeline_metric(
            workspace_id,
            str(firing_node["node_type"]),
            correlation_id,
            meta.get("telemetry") or {},
            lead_mutations,
            correlation_id,
        )
    if firing_node:
        await _emit_send_outcome(
            workspace_id,
            str(firing_node.get("node_type") or ""),
            str(lead_id),
            dict(row),
            meta,
            lead_mutations,
            correlation_id,
            firing_node_id=str(firing_node.get("id") or source_node_id or "") or None,
        )

    # Rate-counter increment on a CONFIRMED send. A real outbound result carries
    # status='sent' and (when a per-seat account was resolved) the stamped
    # sending_account_id. Increment that account's + the campaign's daily/hourly
    # counters here — on the confirmed send, NOT at dispatch — so a failed/held
    # send never consumes capacity. Exactly-once via the omni_send_count_claims
    # ledger keyed on the command_id (Kafka/Flink redelivery bumps once).
    if (meta.get("status") or "").lower() == "sent" and meta.get("sending_account_id"):
        await _increment_send_counters(
            workspace_id, str(meta["sending_account_id"]),
            str(row.get("workflow_id") or "") or None,
            str(meta.get("command_id") or ""),
        )

    # FLINK-001: the orchestrator emits handle="__retry__" after a retriable
    # failure's backoff timer fires. This is NOT an edge — re-fire the SAME node
    # the lead failed on (source_node_id) so the command is genuinely redriven.
    # RETRY-DUP: the retry transition itself is at-least-once; an unguarded
    # re-fire would dispatch the SAME muscle command twice (duplicate send). The
    # (command_id, attempt) marker claim makes each retry fire exactly once.
    if handle == "__retry__":
        marker = f"{meta.get('command_id')}:{meta.get('retry_attempt')}"
        async with system_scope():
            claimed = await fetch_one(
                "UPDATE omni_leads SET custom_fields = jsonb_set(COALESCE(custom_fields,'{}'::jsonb), "
                "'{_retry_marker}', to_jsonb($1::text), true), updated_at=NOW() "
                "WHERE id=$2 AND workspace_id=$3 "
                "AND (custom_fields->>'_retry_marker') IS DISTINCT FROM $1 RETURNING id",
                marker,
                lead_id,
                workspace_id,
            )
        if not claimed:
            log.info("retry %s for lead %s already redriven; dropping duplicate", marker, lead_id)
            return
        node = await _node_row(workspace_id, source_node_id)
        lead, contact = await _lead_with_contact(workspace_id, lead_id)
        if node and lead:
            log.info("redriving lead %s at node %s (retry %s)", lead_id, source_node_id, marker)
            await _fire_node(workspace_id, lead, contact, node, correlation_id)
        else:
            log.warning("retry for lead %s: node/lead gone; dropping", lead_id)
        return

    # Delayed `timeout` transition — fired by flow.race's timeout arm OR an
    # event.* node's EVENT-PARK-001 timeout escape. Either way it only fires the
    # `timeout` handle if the lead is STILL parked here: a race winner (or the
    # event's success-handle resume) already flipped it 'active' and advanced it,
    # so a late timeout is a stale no-op. The race case additionally cancels any
    # still-running sibling arms (the cancel query keys on parent_lead_id=this
    # lead, so an event node with no children is an empty no-op).
    # SM-4: no intermediate `active + current_node_id=NULL` write here — the
    # positional claim below moves the parent waiting→active→target atomically,
    # so a crash mid-timeout leaves a state a redelivery can resume from.
    if handle == "timeout":
        # RACE-PARK-001: claim the parked node atomically (waiting→active). This
        # is the SAME claim the success-signal resume contends for: exactly one
        # of {timeout, resume} wins the row, so the lead can never advance down
        # both the timeout arm AND the accepted/replied arm (a double-send). The
        # old check-then-act read 'waiting' then ran the cancel/barrier side
        # effects in a window where a concurrent resume had already advanced the
        # lead. Only the claim WINNER runs those side effects + the advance.
        if not await _claim_parked_node(workspace_id, str(lead_id), str(source_node_id)):
            log.info("timeout for lead %s ignored — already resolved/resumed", lead_id)
            return
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET status='cancelled', current_node_id=NULL, updated_at=NOW() "
                "WHERE workspace_id=$1 AND parent_lead_id=$2 AND origin_node_id=$3 "
                "AND status NOT IN ('completed','errored','cancelled','converted','ended')",
                workspace_id,
                lead_id,
                str(source_node_id),
            )
        # Release the race's barrier counters so a later fan-out can claim.
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET fanout_total=0, fanout_done=0, updated_at=NOW() "
                "WHERE id=$1 AND workspace_id=$2",
                lead_id,
                workspace_id,
            )

    # RACE-PARK-001 (resume side): a success-signal resume (invite-accepted /
    # reply / open / click) arriving at a STILL-parked lead must also win the
    # single claim before advancing — otherwise a resume and a timeout that both
    # observe 'waiting' could each advance. If the lead is parked here and we
    # don't win the claim, another transition already resolved this node; drop.
    # (Non-parked leads — normal active advances — skip this; their positional
    # claim below is the guard.)
    elif (row.get("status") or "") == "waiting":
        if not await _claim_parked_node(workspace_id, str(lead_id), str(source_node_id)):
            log.info(
                "resume (%s) for lead %s lost the parked-node claim — already resolved; dropping",
                handle, lead_id,
            )
            return

    target = await _target_node(workspace_id, source_node_id, handle)
    if not target:
        # Leaf reached on this handle — the lead's journey is done. Terminalize
        # (claim + barrier accounting): a fan-out CHILD completing at a leaf
        # must still arrive at its parent's join barrier (SM-5's sibling hole —
        # an arm that never reaches flow.join used to hang the parent forever).
        # SPINE-LEAF-001: the status reflects the HANDLE — on_error→errored,
        # empty→ended — so a failed/empty run isn't recorded as success.
        leaf_status = _leaf_terminal_status(handle)
        await _terminalize_lead(workspace_id, lead_id, leaf_status, correlation_id)
        log.info("lead %s reached leaf at node %s/%s -> %s", lead_id, source_node_id, handle, leaf_status)
        return

    target_type = target["node_type"]

    # flow.join: a child arriving at the barrier is handled before any normal
    # advance — it ends the child and may release the parent. We resolve the
    # arriving lead's lineage first.
    if target_type == "flow.join":
        lead, _contact = await _lead_with_contact(workspace_id, lead_id)
        if lead:
            await _join_arrive(workspace_id, lead, correlation_id)
            log.info("lead %s arrived at join %s", lead_id, target["id"])
        return

    # RACE-1 (the trample): fan-out targets must NOT be pre-advanced. The old
    # unconditional _advance_lead here flipped a parked ('waiting') parent back
    # to 'active' on every redelivery — which both bypassed the race's
    # idempotency guard (double fan-out) and broke the join's first-arm-wins
    # claim (it requires status='waiting'; once trampled, no arm could ever
    # win). for_each/race own their parking via atomic claims.
    if target_type == "flow.for_each":
        lead, _contact = await _lead_with_contact(workspace_id, lead_id)
        if lead:
            await _fan_out(workspace_id, lead, target, correlation_id)
        return

    if target_type == "flow.race":
        lead, _contact = await _lead_with_contact(workspace_id, lead_id)
        if lead:
            await _race_fan_out(workspace_id, lead, target, correlation_id)
        return

    # Normal advance: a POSITIONAL CLAIM, not a blind UPDATE. The lead only
    # moves if it still sits where this transition expects (the source node) —
    # a redelivered or Flink-re-emitted transition for a lead that already
    # advanced claims nothing and is dropped, so the target node fires exactly
    # once per real advance (no duplicate intent → no duplicate muscle send).
    # This is the consumer-side defusal of the unkeyed transitions sink (RACE-7).
    async with system_scope():
        claimed = await fetch_one(
            "UPDATE omni_leads SET current_node_id=$1, status='active', updated_at=NOW() "
            "WHERE id=$2 AND workspace_id=$3 AND current_node_id IS NOT DISTINCT FROM $4 "
            "RETURNING id",
            str(target["id"]),
            lead_id,
            workspace_id,
            str(source_node_id),
        )
    if not claimed:
        log.info(
            "stale/duplicate transition for lead %s (%s/%s -> %s) dropped — lead has moved on",
            lead_id, source_node_id, handle, target["id"],
        )
        return
    lead, contact = await _lead_with_contact(workspace_id, lead_id)
    if not lead:
        return

    await _fire_node(workspace_id, lead, contact, target, correlation_id)
    log.info("advanced lead %s -> node %s (%s)", lead_id, target["id"], target_type)


async def run() -> None:
    await init_pool(settings.database_url)
    await assert_rls_enforcing_role()
    await bus.init_producer()
    noderegistry.discover()
    consumer = AIOKafkaConsumer(
        TRANSITIONS_TOPIC,
        bootstrap_servers=settings.kafka_brokers,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        # DEPLOY-001: manual commit-after-success (commit=True below). A timer
        # auto-commit could advance the offset mid-handle, dropping a transition
        # on crash; or redeliver after a rebalance and re-run _fan_out, double-
        # spawning children. We commit only after handle_transition returns, and
        # _fan_out is now idempotent on (parent, for_each_node). Keep replicas:1.
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    log.info("[transitions] consuming %s", TRANSITIONS_TOPIC)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await bus.consume_forever(consumer, handle_transition, name="transitions", stop_event=stop, commit=True)
    finally:
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
