"""Shared workflow-graph validation for the canvas and runtime."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.nodes import get

_TERMINAL_NODE_TYPES = {"flow.goal", "flow.end"}


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "error",
    scope: str = "config",
    node_id: str | None = None,
    edge_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "scope": scope,
        "node_id": node_id,
        "edge_id": edge_id,
    }


def validate_graph(
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    *,
    connections: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    node_rows = [dict(node) for node in nodes]
    edge_rows = [dict(edge) for edge in edges]
    issues: list[dict[str, Any]] = []

    if not node_rows:
        issues.append(_issue("EMPTY_GRAPH", "Add at least one step before running this campaign."))
        return _result(issues)

    node_ids = [str(node["id"]) for node in node_rows]
    duplicate_node_ids = [node_id for node_id, count in Counter(node_ids).items() if count > 1]
    for node_id in duplicate_node_ids:
        issues.append(
            _issue(
                "DUPLICATE_NODE_ID",
                "Two steps share the same identity. Remove and re-add one of them.",
                scope="structural",
                node_id=node_id,
            )
        )
    by_id = {str(node["id"]): node for node in node_rows}

    manifests: dict[str, Any] = {}
    for node in node_rows:
        node_id = str(node["id"])
        node_type = str(node.get("node_type") or "")
        try:
            manifest, _execute = get(node_type)
            manifests[node_id] = manifest
        except KeyError:
            issues.append(
                _issue(
                    "UNKNOWN_NODE_TYPE",
                    f"This step type ({node_type or 'unknown'}) is no longer available.",
                    scope="structural",
                    node_id=node_id,
                )
            )
            continue

        config = node.get("config") or {}
        try:
            manifest.config_schema.model_validate(config)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first.get("loc") or []) or "configuration"
            issues.append(
                _issue(
                    "INVALID_NODE_CONFIG",
                    f"{manifest.display_name or manifest.type}: {field} {first.get('msg', 'is invalid')}.",
                    node_id=node_id,
                )
            )

        if node_type == "condition.rules" and not config.get("rules"):
            issues.append(
                _issue(
                    "CONDITION_RULES_REQUIRED",
                    "Rules needs at least one complete rule.",
                    node_id=node_id,
                )
            )

        if node_type == "ai.enrich" and connections is not None:
            provider = str(config.get("enrich_source") or "")
            connection_name = str(config.get("connection_name") or "")
            if provider and connection_name and (provider, connection_name) not in connections:
                issues.append(
                    _issue(
                        "ENRICHMENT_CONNECTION_MISMATCH",
                        f"{connection_name!r} is not a connected {provider} account.",
                        node_id=node_id,
                    )
                )

    valid_edges: list[tuple[str, str, str]] = []
    routes: Counter[tuple[str, str]] = Counter()
    for edge in edge_rows:
        edge_id = str(edge.get("id") or "") or None
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        handle = str(edge.get("source_handle") or "default")
        if source not in by_id or target not in by_id:
            issues.append(
                _issue(
                    "DANGLING_EDGE",
                    "A connection points to a step that no longer exists.",
                    scope="structural",
                    edge_id=edge_id,
                )
            )
            continue
        if source == target:
            issues.append(
                _issue(
                    "SELF_LOOP",
                    "A step cannot connect back to itself.",
                    scope="structural",
                    node_id=source,
                    edge_id=edge_id,
                )
            )
        manifest = manifests.get(source)
        if manifest and handle not in {output.name for output in manifest.output_handles}:
            issues.append(
                _issue(
                    "UNKNOWN_SOURCE_HANDLE",
                    f"{manifest.display_name or manifest.type} has no {handle!r} output.",
                    scope="structural",
                    node_id=source,
                    edge_id=edge_id,
                )
            )
        routes[(source, handle)] += 1
        valid_edges.append((source, target, handle))

    for (source, handle), count in routes.items():
        if count > 1:
            manifest = manifests.get(source)
            label = manifest.display_name or manifest.type if manifest else "This step"
            issues.append(
                _issue(
                    "AMBIGUOUS_ROUTE",
                    f"{label} has {count} connections from {handle!r}; the runtime cannot choose deterministically.",
                    scope="structural",
                    node_id=source,
                )
            )

    incoming: Counter[str] = Counter(target for _source, target, _handle in valid_edges)
    roots = [node_id for node_id in node_ids if incoming[node_id] == 0]
    if len(roots) != 1:
        issues.append(
            _issue(
                "ENTRY_NODE_COUNT",
                f"The campaign needs exactly one starting step; found {len(roots)}.",
            )
        )
    elif not str(by_id[roots[0]].get("node_type") or "").startswith("source."):
        issues.append(
            _issue(
                "ENTRY_NOT_SOURCE",
                "The first step must be a source so the campaign has people or companies to process.",
                node_id=roots[0],
            )
        )

    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}
    for source, target, _handle in valid_edges:
        adjacency[source].append(target)
        indegree[target] = indegree.get(target, 0) + 1
    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(node_ids):
        issues.append(
            _issue(
                "GRAPH_CYCLE",
                "The journey contains a loop. Use explicit branches and terminal steps instead.",
                scope="structural",
            )
        )

    if len(roots) == 1:
        reachable: set[str] = set()
        queue = deque([roots[0]])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(adjacency[current])
        for node_id in set(node_ids) - reachable:
            issues.append(
                _issue(
                    "UNREACHABLE_NODE",
                    "This step cannot be reached from the campaign start.",
                    node_id=node_id,
                )
            )

    for node_id, manifest in manifests.items():
        node_type = str(by_id[node_id].get("node_type") or "")
        if node_type in _TERMINAL_NODE_TYPES:
            continue
        wired_handles = {handle for source, _target, handle in valid_edges if source == node_id}
        for handle in manifest.output_handles:
            if handle.name == "on_error" or handle.name in wired_handles:
                continue
            issues.append(
                _issue(
                    "UNWIRED_OUTPUT",
                    f"{manifest.display_name or manifest.type}: {handle.name!r} ends the journey because it is not connected.",
                    severity="warning",
                    node_id=node_id,
                )
            )

    return _result(issues)


def _result(issues: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [issue for issue in issues if issue["severity"] == "error"]
    structural_errors = [issue for issue in errors if issue["scope"] == "structural"]
    return {
        "valid_for_save": not structural_errors,
        "valid_for_run": not errors,
        "issues": issues,
        "error_count": len(errors),
        "warning_count": len(issues) - len(errors),
    }
