"""The briefs handed to an authoring agent, for every annotatable surface.

Both entry points that queue a proposal -- the Overview composer and a thread
instruction turn -- have to hand the agent exactly the same brief, or the two
paths drift and only one of them stays grounded.  So the brief is built here
once per target kind rather than inline at each call site.

A brief is data only.  It carries the frozen current state, the executable
grounding, the catalog of what may be used, and the contract the result must
satisfy.  It never carries credentials and never asks the agent to call
anything.
"""

from __future__ import annotations

from typing import Any

_VIEW_SAFETY = [
    "Return data only; do not call campaign, send, or integration endpoints.",
    "Do not request or include credentials.",
    "Omni will validate the candidate and require a human to apply it.",
]

_VIEW_GROUNDING_CONTRACT = [
    "Treat captured campaign IDs and widget query results as authoritative for this workspace.",
    "A campaign-labelled leads/send-outcomes widget must filter workflow_id to that exact campaign.",
    "A sent-message count must also filter send_outcomes.status to exactly 'sent'.",
    "Never label send_outcomes as delivered; this projection does not contain delivery receipts.",
    "Do not evade a requested correction by renaming a campaign widget to a global metric.",
    "Preserve unrequested widget semantics and stable widget IDs.",
]


def build_view_brief(
    current_payload: dict[str, Any],
    *,
    instruction: str,
    annotations: list[dict[str, str]],
    grounding: dict[str, Any],
    widget_catalog: dict[str, Any],
    origin: str,
    request_fingerprint: str,
) -> dict[str, Any]:
    """The ``view.author`` brief. Extracted verbatim from the Overview composer."""
    return {
        "task": (
            "Return one complete revised ViewSpec JSON object. Preserve everything "
            "that was not requested, including stable widget IDs."
        ),
        "current_view": current_payload,
        "whole_view_instruction": instruction.strip(),
        "widget_annotations": annotations,
        "grounding": grounding,
        "grounding_contract": list(_VIEW_GROUNDING_CONTRACT),
        "widget_catalog": widget_catalog,
        "output_contract": {
            "name": "1-80 characters",
            "description": "0-200 characters",
            "icon": "a catalogued icon or layout-dashboard",
            "layout": "1-12 validated widget objects with stable IDs where preserved",
        },
        "safety": list(_VIEW_SAFETY),
        "authoring_origin": origin,
        "request_fingerprint": request_fingerprint,
    }


_CAMPAIGN_GROUNDING_CONTRACT = [
    "Node IDs are stable identities. Reuse the existing id for a node you are keeping, "
    "even if you change its config — a new id reads as 'deleted and replaced' and will "
    "be reviewed as stranding every lead parked on it.",
    "Change only the nodes named in the annotations. Everything else must come back "
    "byte-identical, including positions.",
    "Live leads are standing on specific nodes right now; live_leads_by_node in the "
    "grounding is authoritative. Removing or retyping one of those nodes strands them.",
    "A campaign that is not in 'draft' status is running against real people. Prefer "
    "the smallest change that satisfies the annotation.",
    "Never remove a flow.human_approval that currently sits upstream of a channel node.",
    "Do not introduce a channel type this campaign has never used.",
]

_CAMPAIGN_SAFETY = [
    "Return the graph document only; do not call run, activate, audience, or send endpoints.",
    "Do not request or include credentials.",
    "Omni recomputes blast radius against live leads and requires a human to apply this.",
    "A proposal that strands live leads or opens an unapproved send path is refused, "
    "not stored for someone to click through.",
]


def build_campaign_brief(
    grounding: dict[str, Any],
    *,
    instruction: str,
    annotations: list[dict[str, str]],
    node_catalog: list[dict[str, Any]],
    origin: str,
    request_fingerprint: str,
) -> dict[str, Any]:
    """The ``campaign.author`` brief.

    Deliberately shaped like the view brief so a harness that already handles
    one needs no new control flow for the other: read the brief, produce the
    document named in ``output_contract``, complete the job.
    """
    workflow = grounding.get("workflow") or {}
    return {
        "task": (
            "Return one complete campaign graph as {\"nodes\": [...], \"edges\": [...]}. "
            "Preserve every node and edge that was not requested, including stable node "
            "IDs and canvas positions."
        ),
        "campaign": workflow,
        "current_graph": {
            "nodes": grounding.get("nodes") or [],
            "edges": grounding.get("edges") or [],
        },
        "node_annotations": annotations,
        "whole_campaign_instruction": instruction.strip(),
        "grounding": grounding,
        "grounding_contract": list(_CAMPAIGN_GROUNDING_CONTRACT),
        "node_catalog": node_catalog,
        "output_contract": {
            "nodes": (
                "every node as {id, node_type, position_x, position_y, config}; "
                "ids stable, no extra fields"
            ),
            "edges": (
                "every edge as {id, source_node_id, target_node_id, source_handle, "
                "target_handle}; source_handle must be a handle the node actually "
                "renders (including the literal \"default\"), target_handle is null"
            ),
        },
        "review_criteria": {
            "blast_radius": (
                "each removed or retyped node is counted against the live leads parked "
                "on it, recomputed at completion time"
            ),
            "gate_diff": (
                "approval coverage, per-node dedupe_action, and the set of channel types "
                "are diffed; losing any of them on a running campaign is a refusal"
            ),
            "consent": "changing a node that carries no annotation is a finding against you",
        },
        "safety": list(_CAMPAIGN_SAFETY),
        "authoring_origin": origin,
        "request_fingerprint": request_fingerprint,
    }
