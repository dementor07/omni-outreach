"""CAMPAIGN-AUTHOR-001 — shape validation for a proposed campaign graph.

The mirror of :func:`app.services.view_widgets.validate_candidate_view`, for the
other authorable surface.  This layer answers only "is this a well-formed graph
document" -- whether it is *safe* is a separate and much harder question, and it
is answered in :mod:`app.services.campaign_grounding` against live data.

Keeping the two apart matters: a proposal that is structurally perfect can still
delete a node that 34 real leads are parked on.  Passing here is necessary and
nowhere near sufficient.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

MAX_NODES = 120
MAX_EDGES = 240

_NODE_FIELDS = {"id", "node_type", "position_x", "position_y", "config"}
_EDGE_FIELDS = {"id", "source_node_id", "target_node_id", "source_handle", "target_handle"}


class CampaignCandidateError(ValueError):
    """A proposed graph that is not a well-formed document."""


def _uuid(value: Any, *, field: str, where: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CampaignCandidateError(f"{where} is missing {field}")
    try:
        return str(UUID(text))
    except (ValueError, AttributeError, TypeError) as exc:
        raise CampaignCandidateError(f"{where} has a {field} that is not a UUID: {text!r}") from exc


def _node(raw: Any, index: int) -> dict[str, Any]:
    where = f"node #{index + 1}"
    if not isinstance(raw, dict):
        raise CampaignCandidateError(f"{where} is not an object")
    unknown = set(raw) - _NODE_FIELDS
    if unknown:
        raise CampaignCandidateError(
            f"{where} carries unsupported fields: {', '.join(sorted(unknown))}"
        )
    node_type = str(raw.get("node_type") or "").strip()
    if not node_type:
        raise CampaignCandidateError(f"{where} is missing node_type")
    config = raw.get("config")
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise CampaignCandidateError(f"{where} has a config that is not an object")
    try:
        position_x = float(raw.get("position_x") or 0)
        position_y = float(raw.get("position_y") or 0)
    except (TypeError, ValueError) as exc:
        raise CampaignCandidateError(f"{where} has a non-numeric position") from exc
    return {
        # Node ids are preserved deliberately: a stable id is what lets the
        # review say "you removed THIS node" rather than "the graph changed".
        "id": _uuid(raw.get("id"), field="id", where=where),
        "node_type": node_type,
        "position_x": position_x,
        "position_y": position_y,
        "config": config,
    }


def _edge(raw: Any, index: int, node_ids: set[str]) -> dict[str, Any]:
    where = f"edge #{index + 1}"
    if not isinstance(raw, dict):
        raise CampaignCandidateError(f"{where} is not an object")
    unknown = set(raw) - _EDGE_FIELDS
    if unknown:
        raise CampaignCandidateError(
            f"{where} carries unsupported fields: {', '.join(sorted(unknown))}"
        )
    source = _uuid(raw.get("source_node_id"), field="source_node_id", where=where)
    target = _uuid(raw.get("target_node_id"), field="target_node_id", where=where)
    for role, node_id in (("source", source), ("target", target)):
        if node_id not in node_ids:
            raise CampaignCandidateError(
                f"{where} points its {role} at {node_id}, which is not a node in this graph"
            )
    edge_id = raw.get("id")
    handle = raw.get("source_handle")
    target_handle = raw.get("target_handle")
    return {
        "id": _uuid(edge_id, field="id", where=where) if edge_id else None,
        "source_node_id": source,
        "target_node_id": target,
        # The canvas edge contract: a rendered source handle id (including the
        # literal "default"), and a target handle that is normally null.
        "source_handle": str(handle) if handle is not None else None,
        "target_handle": str(target_handle) if target_handle is not None else None,
    }


def validate_candidate_graph(result: Any) -> dict[str, Any]:
    """Normalize a proposed ``{nodes, edges}`` document or explain the refusal."""
    if not isinstance(result, dict):
        raise CampaignCandidateError("the proposal must be a JSON object with nodes and edges")
    raw_nodes = result.get("nodes")
    raw_edges = result.get("edges")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise CampaignCandidateError("the proposal needs a non-empty 'nodes' array")
    if raw_edges is None:
        raw_edges = []
    if not isinstance(raw_edges, list):
        raise CampaignCandidateError("'edges' must be an array when present")
    if len(raw_nodes) > MAX_NODES:
        raise CampaignCandidateError(f"a campaign may hold at most {MAX_NODES} nodes")
    if len(raw_edges) > MAX_EDGES:
        raise CampaignCandidateError(f"a campaign may hold at most {MAX_EDGES} edges")

    nodes = [_node(raw, index) for index, raw in enumerate(raw_nodes)]
    seen: set[str] = set()
    for node in nodes:
        if node["id"] in seen:
            raise CampaignCandidateError(
                f"two nodes share the id {node['id']}; ids must be unique and stable"
            )
        seen.add(node["id"])
    edges = [_edge(raw, index, seen) for index, raw in enumerate(raw_edges)]

    wired: set[tuple[str, str, str | None]] = set()
    for edge in edges:
        key = (edge["source_node_id"], edge["target_node_id"], edge["source_handle"])
        if key in wired:
            raise CampaignCandidateError(
                "the same source handle is wired to the same target twice"
            )
        wired.add(key)
    return {"nodes": nodes, "edges": edges}
