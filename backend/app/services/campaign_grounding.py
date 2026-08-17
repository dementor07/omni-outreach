"""CAMPAIGN-AUTHOR-001 — executable review evidence for a proposed campaign graph.

The Overview review earns its trust by *running* the candidate queries and
diffing the rows.  A campaign cannot be dry-run: there is no way to execute a
proposed sequence and see what happens without messaging real people.  So the
evidence has to be different in kind.

Two things are computable, and between them they cover the failure modes that
actually hurt:

**Blast radius.**  ``omni_leads.current_node_id`` has no foreign key, and
``PUT /workflows/{id}/graph`` replaces the graph by DELETE-then-INSERT.  A lead
parked on a node the proposal removes keeps a dangling pointer, and
``transition_worker`` then drops it at ``if lead and node:`` with no log and no
terminal status -- the SEND-ONCE-002 stranding shape, reached through the canvas
instead of a send guard.  So every removed or retyped node is counted against
the live leads sitting on it *before* anyone can apply the change.

**Gate diff.**  Not every protection is graph-editable, and saying which is
which bounds the risk honestly:

===================  =====================================================
Graph-editable       ``flow.human_approval`` coverage, per-node
                     ``dedupe_action`` (DEDUP-SEND-001), which channels the
                     campaign can reach at all
Not graph-editable   DNC/suppression, SEND-ONCE-001 at-most-once, daily cap,
                     business-hours window, SEND-SPACE-001 spacing -- these
                     live in ``_fire_node`` and on ``omni_workflows`` columns,
                     so no graph proposal can switch them off
===================  =====================================================

Read-only.  This module executes no nodes, publishes no events, and sends
nothing.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any
from uuid import UUID

from app.db import fetch_all, fetch_one
from app.services.graph_validation import validate_graph

LIVE_LEAD_STATUSES = ("active", "waiting")

APPROVAL_NODE = "flow.human_approval"
CHANNEL_PREFIX = "channel."

BLOCKING = "blocking"
WARNING = "warning"
INFO = "info"

# A draft campaign has no live audience to endanger, so the strict rules that
# protect running campaigns would only be friction there.
MUTABLE_STATUSES = ("draft",)


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value


def _finding(
    severity: str, code: str, message: str, *, node_id: str | None = None, **extra: Any
) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "node_id": node_id, **extra}


def _index(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in nodes}


def _semantic(node: dict[str, Any]) -> tuple[str, str]:
    """What a node *means*, ignoring where it sits on the canvas.

    Dragging a box is not a change worth gating; changing what it does is.
    """
    config = _loads(node.get("config")) or {}
    return str(node.get("node_type") or ""), json.dumps(config, sort_keys=True)


def _entry_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    targets = {str(edge["target_node_id"]) for edge in edges}
    return [str(node["id"]) for node in nodes if str(node["id"]) not in targets]


def unapproved_channels(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> set[str]:
    """Channel nodes reachable from an entry without crossing a human approval.

    A proper dominator question: walk forward from the entries but refuse to
    expand *through* an approval node.  Any channel node still reached has at
    least one path on which nobody signs off before a message goes out.
    """
    by_id = _index(nodes)
    outgoing: dict[str, list[str]] = {}
    for edge in edges:
        outgoing.setdefault(str(edge["source_node_id"]), []).append(str(edge["target_node_id"]))

    seen: set[str] = set()
    queue = deque(_entry_nodes(nodes, edges))
    while queue:
        node_id = queue.popleft()
        if node_id in seen or node_id not in by_id:
            continue
        seen.add(node_id)
        if str(by_id[node_id].get("node_type") or "") == APPROVAL_NODE:
            continue  # everything downstream of here is approved
        for nxt in outgoing.get(node_id, []):
            if nxt not in seen:
                queue.append(nxt)
    return {
        node_id
        for node_id in seen
        if str(by_id[node_id].get("node_type") or "").startswith(CHANNEL_PREFIX)
    }


def gate_profile(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """The graph-editable protections, summarized for diffing."""
    channels = {
        str(node["id"]): str(node["node_type"])
        for node in nodes
        if str(node.get("node_type") or "").startswith(CHANNEL_PREFIX)
    }
    dedupe_on = {
        node_id
        for node_id in channels
        if str((_loads(_index(nodes)[node_id].get("config")) or {}).get("dedupe_action") or "off").lower()
        in ("skip_step", "end_lead")
    }
    return {
        "channel_nodes": channels,
        "channel_types": sorted(set(channels.values())),
        "approval_nodes": [
            str(node["id"]) for node in nodes if str(node.get("node_type") or "") == APPROVAL_NODE
        ],
        "unapproved_channel_nodes": sorted(unapproved_channels(nodes, edges)),
        "dedupe_enabled_nodes": sorted(dedupe_on),
    }


async def live_leads_by_node(workflow_id: UUID) -> dict[str, int]:
    rows = await fetch_all(
        """
        SELECT current_node_id AS node_id, count(*) AS leads
        FROM omni_leads
        WHERE workflow_id = $1
          AND current_node_id IS NOT NULL
          AND status = ANY($2::text[])
        GROUP BY 1
        """,
        workflow_id,
        list(LIVE_LEAD_STATUSES),
    )
    return {str(row["node_id"]): int(row["leads"]) for row in rows}


async def capture_campaign_grounding(workflow_id: UUID) -> dict[str, Any]:
    """Freeze the campaign's live shape as the 'before' side of the review."""
    workflow = await fetch_one("SELECT * FROM omni_workflows WHERE id=$1", workflow_id)
    if workflow is None:
        raise ValueError("campaign not found")
    nodes = [
        dict(row)
        for row in await fetch_all(
            "SELECT id, node_type, position_x, position_y, config "
            "FROM omni_workflow_nodes WHERE workflow_id=$1",
            workflow_id,
        )
    ]
    edges = [
        dict(row)
        for row in await fetch_all(
            "SELECT id, source_node_id, target_node_id, source_handle, target_handle "
            "FROM omni_workflow_edges WHERE workflow_id=$1",
            workflow_id,
        )
    ]
    for node in nodes:
        node["id"] = str(node["id"])
        node["config"] = _loads(node.get("config")) or {}
    for edge in edges:
        edge["id"] = str(edge["id"])
        edge["source_node_id"] = str(edge["source_node_id"])
        edge["target_node_id"] = str(edge["target_node_id"])

    parked = await live_leads_by_node(workflow_id)
    record = dict(workflow)
    return {
        "workflow": {
            "id": str(record["id"]),
            "name": record.get("name"),
            "status": record.get("status"),
            "timezone": record.get("timezone"),
            # Carried for context only: a graph proposal cannot change these.
            "daily_cap": record.get("daily_cap"),
            "earliest_hour": record.get("earliest_hour"),
            "latest_hour": record.get("latest_hour"),
            "days_of_week": record.get("days_of_week"),
        },
        "nodes": nodes,
        "edges": edges,
        "gates": gate_profile(nodes, edges),
        "live_leads_by_node": parked,
        "live_lead_total": sum(parked.values()),
    }


def _blast_radius(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    parked: dict[str, int],
) -> list[dict[str, Any]]:
    """Every semantically touched node, with the live leads standing on it."""
    before_by_id = _index(before)
    after_by_id = _index(after)
    rows: list[dict[str, Any]] = []
    for node_id, node in before_by_id.items():
        leads = parked.get(node_id, 0)
        if node_id not in after_by_id:
            rows.append(
                {
                    "node_id": node_id,
                    "node_type": str(node.get("node_type")),
                    "change": "removed",
                    "live_leads": leads,
                }
            )
            continue
        old_type, old_config = _semantic(node)
        new_type, new_config = _semantic(after_by_id[node_id])
        if old_type != new_type:
            rows.append(
                {
                    "node_id": node_id,
                    "node_type": new_type,
                    "previous_node_type": old_type,
                    "change": "retyped",
                    "live_leads": leads,
                }
            )
        elif old_config != new_config:
            rows.append(
                {
                    "node_id": node_id,
                    "node_type": new_type,
                    "change": "reconfigured",
                    "live_leads": leads,
                }
            )
    for node_id, node in after_by_id.items():
        if node_id not in before_by_id:
            rows.append(
                {
                    "node_id": node_id,
                    "node_type": str(node.get("node_type")),
                    "change": "added",
                    "live_leads": 0,
                }
            )
    rows.sort(key=lambda row: (-row["live_leads"], row["change"], row["node_id"]))
    return rows


def _consent_findings(
    radius: list[dict[str, Any]], annotated: set[str], protected: bool
) -> list[dict[str, Any]]:
    """lavish's rule: never edit what the human did not hand you.

    Added nodes are exempt -- a new node has no id to annotate.  Everything else
    that changed without being annotated is at least a warning, and on a live
    campaign a change to an unannotated *send* node is a refusal.
    """
    findings: list[dict[str, Any]] = []
    for row in radius:
        if row["change"] == "added" or row["node_id"] in annotated:
            continue
        is_channel = str(row["node_type"]).startswith(CHANNEL_PREFIX)
        severity = BLOCKING if (protected and is_channel) else WARNING
        findings.append(
            _finding(
                severity,
                "UNREQUESTED_NODE_CHANGE",
                f"{row['node_type']} was {row['change']} but was never annotated; "
                "the agent may only change what it was asked to change",
                node_id=row["node_id"],
                change=row["change"],
                live_leads=row["live_leads"],
            )
        )
    return findings


async def review_campaign_candidate(
    job_payload: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Broker-facing review contract for a completed ``campaign.author`` job."""
    before = job_payload.get("grounding")
    if not isinstance(before, dict) or "nodes" not in before:
        raise ValueError("campaign.author job payload is missing its grounding")
    workflow = before.get("workflow") or {}
    workflow_id = workflow.get("id")
    status = str(workflow.get("status") or "draft")
    protected = status not in MUTABLE_STATUSES

    before_nodes = list(before.get("nodes") or [])
    before_edges = list(before.get("edges") or [])
    after_nodes = list(candidate.get("nodes") or [])
    after_edges = list(candidate.get("edges") or [])

    # Blast radius is recomputed against live data rather than trusting the
    # frozen snapshot: leads keep moving while a proposal is being written, and
    # a stale count is exactly the number you do not want to gate on.
    parked = (
        await live_leads_by_node(UUID(str(workflow_id)))
        if workflow_id
        else dict(before.get("live_leads_by_node") or {})
    )

    findings: list[dict[str, Any]] = []
    connection_rows = await fetch_all("SELECT provider, name FROM omni_connections")
    structural = validate_graph(
        after_nodes,
        after_edges,
        connections={(str(row["provider"]), str(row["name"])) for row in connection_rows},
        has_audience=bool(before.get("live_lead_total")),
    )
    for issue in structural["issues"]:
        findings.append(
            _finding(
                BLOCKING if issue["severity"] == "error" and issue["scope"] == "structural"
                else WARNING if issue["severity"] == "error"
                else INFO,
                issue["code"],
                issue["message"],
                node_id=issue.get("node_id"),
            )
        )

    radius = _blast_radius(before_nodes, after_nodes, parked)
    for row in radius:
        if row["change"] in ("removed", "retyped") and row["live_leads"] > 0:
            findings.append(
                _finding(
                    BLOCKING if protected else WARNING,
                    "STRANDS_LIVE_LEADS",
                    f"{row['live_leads']} live lead(s) are parked on this "
                    f"{row['node_type']}; {row['change'][:-1]}ing it leaves them pointing at "
                    "a node that no longer exists, and they will stop advancing silently",
                    node_id=row["node_id"],
                    live_leads=row["live_leads"],
                    change=row["change"],
                )
            )

    before_gates = before.get("gates") or gate_profile(before_nodes, before_edges)
    after_gates = gate_profile(after_nodes, after_edges)
    lost_approval = sorted(
        set(after_gates["unapproved_channel_nodes"])
        - set(before_gates.get("unapproved_channel_nodes") or [])
    )
    for node_id in lost_approval:
        findings.append(
            _finding(
                BLOCKING if protected else WARNING,
                "APPROVAL_GATE_REMOVED",
                f"{after_gates['channel_nodes'].get(node_id, 'a channel node')} can now be "
                "reached without passing a human approval; messages would go out unreviewed",
                node_id=node_id,
            )
        )
    new_channels = sorted(
        set(after_gates["channel_types"]) - set(before_gates.get("channel_types") or [])
    )
    for channel in new_channels:
        findings.append(
            _finding(
                BLOCKING if protected else WARNING,
                "NEW_SEND_SURFACE",
                f"this proposal adds {channel}, a channel this campaign has never used; "
                "the existing audience never entered on that surface",
            )
        )
    lost_dedupe = sorted(
        set(before_gates.get("dedupe_enabled_nodes") or [])
        - set(after_gates["dedupe_enabled_nodes"])
    )
    for node_id in lost_dedupe:
        findings.append(
            _finding(
                WARNING,
                "DEDUPE_DISABLED",
                "DEDUP-SEND-001 was switched off on this send; contacts already "
                "messaged on this channel can be messaged again",
                node_id=node_id,
            )
        )

    annotated = {
        str(anchor.get("ref"))
        for anchor in job_payload.get("annotations") or []
        if isinstance(anchor, dict) and anchor.get("ref")
    }
    findings.extend(_consent_findings(radius, annotated, protected))

    blocking = [item for item in findings if item["severity"] == BLOCKING]
    return {
        # Kept for contract parity with the view review: every grounding query
        # this module runs must have executed for the result to mean anything.
        "all_queries_valid": True,
        "blocked_reason": blocking[0]["message"] if blocking else None,
        "ready_to_apply": not blocking,
        "campaign_status": status,
        "protected": protected,
        "findings": findings,
        "blast_radius": radius,
        "live_leads_total": sum(parked.values()),
        "gate_diff": {
            "before": before_gates,
            "after": after_gates,
            "approval_lost_on": lost_approval,
            "new_channel_types": new_channels,
            "dedupe_disabled_on": lost_dedupe,
            # Stated explicitly so a reviewer knows what this diff does NOT
            # cover, rather than inferring safety from silence.
            "not_graph_editable": [
                "DNC / suppression",
                "SEND-ONCE-001 at-most-once send",
                "daily cap",
                "business-hours window",
                "SEND-SPACE-001 inter-send spacing",
            ],
        },
        "structural": structural,
    }
