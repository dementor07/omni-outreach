"""AGENT-THREAD-001 — resolve and validate annotation anchors for any target.

A thread turn can be pinned to a specific part of the thing being discussed: a
widget on an Overview view, or a node on a campaign canvas.  Both surfaces need
the same three answers -- does this target exist, what is its current version,
and is this anchor real -- so they are answered in one place rather than twice.

Validating at the door matters more than it looks.  An anchor that names a
deleted widget or a node that was renamed away is not a harmless typo: it is an
instruction the agent will try to satisfy against something that is not there,
and the most likely way to satisfy it is to invent a replacement.  Rejecting the
turn is the honest outcome.

Read-only.  Nothing here mutates a view, a campaign, or a lead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.db import fetch_all, fetch_one

TARGET_KINDS: tuple[str, ...] = ("view", "workflow")

MAX_ANCHORS_PER_TURN = 12
MAX_ANCHOR_NOTE = 1000


class AnchorError(ValueError):
    """A target or anchor reference that cannot be honoured as written."""


@dataclass(frozen=True)
class TargetSnapshot:
    """What a turn is being written against, frozen at the moment it was posted."""

    target_type: str
    target_id: UUID
    label: str
    version: datetime | None
    # ref -> human-readable description, used both to validate anchors and to
    # give the agent something better than a bare UUID to reason about.
    anchors: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def describe(self, ref: str) -> str:
        return self.anchors.get(ref, ref)


def _widget_label(widget: dict[str, Any]) -> str:
    title = str(widget.get("title") or "").strip()
    kind = str(widget.get("type") or widget.get("widget") or "widget").strip()
    return f"{title} ({kind})" if title else kind


async def _load_view(target_id: UUID) -> TargetSnapshot:
    row = await fetch_one("SELECT * FROM omni_views WHERE id=$1", target_id)
    if row is None:
        raise AnchorError("view not found")
    record = dict(row)
    layout = record.get("layout") or []
    if isinstance(layout, str):  # asyncpg returns jsonb as str on some paths
        import json

        layout = json.loads(layout)
    anchors = {
        str(widget["id"]): _widget_label(widget)
        for widget in layout
        if isinstance(widget, dict) and widget.get("id")
    }
    return TargetSnapshot(
        target_type="view",
        target_id=target_id,
        label=str(record.get("name") or "view"),
        version=record.get("updated_at"),
        anchors=anchors,
        extra={"widget_count": len(anchors)},
    )


async def _load_workflow(target_id: UUID) -> TargetSnapshot:
    row = await fetch_one("SELECT * FROM omni_workflows WHERE id=$1", target_id)
    if row is None:
        raise AnchorError("campaign not found")
    record = dict(row)
    nodes = await fetch_all(
        "SELECT id, node_type, config FROM omni_workflow_nodes "
        "WHERE workflow_id=$1 ORDER BY position_y, position_x",
        target_id,
    )
    anchors: dict[str, str] = {}
    for node in nodes:
        config = node["config"]
        if isinstance(config, str):
            import json

            try:
                config = json.loads(config)
            except ValueError:
                config = {}
        name = str((config or {}).get("label") or (config or {}).get("name") or "").strip()
        node_type = str(node["node_type"])
        anchors[str(node["id"])] = f"{name} ({node_type})" if name else node_type
    return TargetSnapshot(
        target_type="workflow",
        target_id=target_id,
        label=str(record.get("name") or "campaign"),
        version=record.get("updated_at"),
        anchors=anchors,
        extra={
            # The review layer needs to know this before it will touch a send
            # node, so carry it on the snapshot rather than re-reading later.
            "status": str(record.get("status") or "draft"),
            "timezone": str(record.get("timezone") or "UTC"),
            "node_count": len(anchors),
        },
    )


async def load_target(target_type: str, target_id: UUID) -> TargetSnapshot:
    """Freeze the current shape of an annotatable target."""
    if target_type == "view":
        return await _load_view(target_id)
    if target_type == "workflow":
        return await _load_workflow(target_id)
    raise AnchorError(f"unsupported annotation target: {target_type!r}")


def validate_anchors(
    snapshot: TargetSnapshot, anchors: list[dict[str, Any]] | None
) -> list[dict[str, str]]:
    """Normalize anchors and reject any that no longer exist on the target.

    Mirrors :func:`app.services.view_architect.validate_annotation_targets`,
    generalized from widget ids to any target's anchor namespace.
    """
    normalized: list[dict[str, str]] = []
    incoming = anchors or []
    if len(incoming) > MAX_ANCHORS_PER_TURN:
        raise AnchorError(
            f"a single turn may carry at most {MAX_ANCHORS_PER_TURN} annotations; "
            f"got {len(incoming)}"
        )
    seen: set[str] = set()
    for anchor in incoming:
        if not isinstance(anchor, dict):
            raise AnchorError("each annotation must be an object with 'ref' and 'note'")
        ref = str(anchor.get("ref") or anchor.get("widget_id") or anchor.get("node_id") or "").strip()
        note = str(anchor.get("note") or "").strip()
        if not ref:
            raise AnchorError("an annotation is missing its target reference")
        if ref not in snapshot.anchors:
            raise AnchorError(
                f"annotation target {ref!r} is stale or not part of this "
                f"{snapshot.target_type}"
            )
        if not note:
            raise AnchorError(f"the annotation on {snapshot.describe(ref)} is empty")
        if ref in seen:
            raise AnchorError(
                f"{snapshot.describe(ref)} carries two annotations in one turn; "
                "combine them into a single note"
            )
        seen.add(ref)
        normalized.append({"ref": ref, "note": note[:MAX_ANCHOR_NOTE]})
    return normalized


def anchors_as_view_annotations(anchors: list[dict[str, str]]) -> list[dict[str, str]]:
    """Adapt thread anchors to the ``widget_annotations`` shape view jobs expect."""
    return [{"widget_id": anchor["ref"], "note": anchor["note"]} for anchor in anchors]
