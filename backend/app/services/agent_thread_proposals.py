"""Turn queued instruction turns into one grounded, reviewable proposal.

A thread accepts turns continuously; a *proposal* is still one-at-a-time, because
two competing pending diffs for one target is a real conflict rather than a
limitation.  ``uq_agent_jobs_one_unapplied_proposal`` enforces that, and this
module is where the two rules meet: questions never come here at all, and
instructions queue behind whichever proposal is already open.

Everything downstream is the existing spine -- lease, claim, heartbeat, validate,
review, apply.  Nothing about the job broker changes to support a second target
kind, which is what migration 056 anticipated when it made ``kind`` generic.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from app.db import fetch_one
from app.services import agent_harness, agent_threads
from app.services.agent_anchors import TargetSnapshot, anchors_as_view_annotations, load_target
from app.services.authoring_briefs import build_campaign_brief, build_view_brief

JOB_KIND_BY_TARGET = {"view": "view.author", "workflow": "campaign.author"}


class ProposalError(ValueError):
    """A proposal that cannot be built from these turns."""


def _fingerprint(**parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _merge(turns: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    """Fold several queued instructions into one brief.

    Turns are folded in order and anchors are kept per-turn rather than merged
    into a set: two notes on the same node in different turns are two separate
    requests, and collapsing them silently drops one.
    """
    instructions: list[str] = []
    anchors: list[dict[str, str]] = []
    for turn in turns:
        body = str(turn.get("body") or "").strip()
        if body:
            instructions.append(body)
        for anchor in turn.get("anchors") or []:
            anchors.append({"ref": str(anchor["ref"]), "note": str(anchor["note"])})
    return "\n\n".join(instructions), anchors


async def _view_brief(
    snapshot: TargetSnapshot, instruction: str, anchors: list[dict[str, str]], fingerprint: str
) -> tuple[dict[str, Any], Any]:
    from app.services.view_grounding import capture_view_grounding
    from app.services.view_query import entity_catalog
    from app.services.view_widgets import widget_manifests

    row = await fetch_one("SELECT * FROM omni_views WHERE id=$1", snapshot.target_id)
    if row is None:
        raise ProposalError("view not found")
    record = dict(row)
    layout = record.get("layout") or []
    if isinstance(layout, str):
        layout = json.loads(layout)
    current = {
        "name": record.get("name"),
        "description": record.get("description"),
        "icon": record.get("icon"),
        "layout": layout,
    }
    grounding = await capture_view_grounding(current)
    brief = build_view_brief(
        current,
        instruction=instruction,
        annotations=anchors_as_view_annotations(anchors),
        grounding=grounding,
        widget_catalog={"widgets": widget_manifests(), **entity_catalog()},
        origin="harness",
        request_fingerprint=fingerprint,
    )
    # The thread's own anchor shape is carried alongside the view-flavoured one
    # so the consent check reads the same field for every target kind.
    brief["annotations"] = anchors
    return brief, record.get("updated_at")


def _node_catalog() -> list[dict[str, Any]]:
    from app.nodes import manifests

    catalog: list[dict[str, Any]] = []
    for manifest in manifests():
        if not manifest.visible_in_palette:
            continue
        catalog.append(
            {
                "type": manifest.type,
                "category": manifest.category.value,
                "summary": manifest.summary,
                "output_handles": [handle.name for handle in manifest.output_handles],
                "side_effect": manifest.side_effect.value,
                "entry_capable": manifest.entry_capable,
                "primary_fields": list(manifest.primary_fields),
            }
        )
    return catalog


async def _campaign_brief(
    snapshot: TargetSnapshot, instruction: str, anchors: list[dict[str, str]], fingerprint: str
) -> tuple[dict[str, Any], Any]:
    from app.services.campaign_grounding import capture_campaign_grounding

    grounding = await capture_campaign_grounding(snapshot.target_id)
    brief = build_campaign_brief(
        grounding,
        instruction=instruction,
        annotations=anchors,
        node_catalog=_node_catalog(),
        origin="harness",
        request_fingerprint=fingerprint,
    )
    brief["annotations"] = anchors
    return brief, snapshot.version


async def propose_from_turns(
    *,
    workspace_id: str,
    thread_id: UUID,
    turn_ids: list[UUID],
    harness_id: str,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Build one proposal from the named instruction turns and queue it."""
    thread = await agent_threads.get_thread(thread_id)
    if thread is None:
        raise ProposalError("conversation not found")
    if thread["status"] != "open":
        raise ProposalError("this conversation has ended")

    target_type = str(thread["target_type"])
    kind = JOB_KIND_BY_TARGET.get(target_type)
    if kind is None:
        raise ProposalError(f"{target_type} targets cannot be proposed against")

    turns = [
        turn
        for turn in await agent_threads.list_turns(thread_id, limit=500)
        if turn["id"] in set(turn_ids)
    ]
    if not turns:
        raise ProposalError("none of those turns belong to this conversation")
    non_instruction = [turn for turn in turns if turn["intent"] != "instruction"]
    if non_instruction:
        # The structural guarantee, restated where it is easiest to violate: a
        # question must never be the thing that produced a diff.
        raise ProposalError(
            "only instruction turns can produce a proposal; "
            f"{len(non_instruction)} of these are not instructions"
        )
    already = [turn for turn in turns if turn["status"] != "queued"]
    if already:
        raise ProposalError("some of those turns have already been answered or proposed against")

    snapshot = await load_target(target_type, thread["target_id"])
    instruction, anchors = _merge(turns)
    fingerprint = _fingerprint(
        thread=str(thread_id),
        turns=sorted(str(turn["id"]) for turn in turns),
        version=snapshot.version,
        harness=harness_id,
    )
    if target_type == "view":
        payload, version = await _view_brief(snapshot, instruction, anchors, fingerprint)
    else:
        payload, version = await _campaign_brief(snapshot, instruction, anchors, fingerprint)
    payload["thread"] = {
        "id": str(thread_id),
        "turn_ids": [str(turn["id"]) for turn in turns],
        "target_label": snapshot.label,
    }

    job = await agent_harness.create_job(
        workspace_id=workspace_id,
        kind=kind,
        target_type=target_type,
        target_id=thread["target_id"],
        target_version=version,
        payload=payload,
        created_by=created_by,
        requested_harness_id=harness_id,
        origin="harness",
    )
    await agent_threads.attach_proposal(
        thread_id=thread_id, turn_ids=[turn["id"] for turn in turns], job_id=job["id"]
    )
    return job
