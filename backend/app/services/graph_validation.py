"""Shared workflow-graph validation for the canvas and runtime."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.nodes import get

_TERMINAL_NODE_TYPES = {"flow.goal", "flow.end"}

# APOLLO-DATA nodes that require an ("apollo", connection_name) connection.
_APOLLO_NODES = {
    "source.apollo_people",
    "enrich.apollo_company",
    "source.apollo_jobs",
}

# UNIPILE-FULL nodes that require a ("unipile", connection_name) connection.
_UNIPILE_NODES = {
    "source.linkedin_search",
    "enrich.linkedin_company",
    "enrich.linkedin_member",
    # TAXONOMY-001: the four first-class LinkedIn actions (ex channel.linkedin).
    "channel.linkedin_invite",
    "channel.linkedin_dm",
    "channel.linkedin_inmail",
    "channel.linkedin_profile_view",
    "channel.linkedin_react_post",
    "channel.linkedin_comment_post",
    "channel.linkedin_endorse",
    "channel.linkedin_follow",
    "channel.message_react",
    "channel.invite_cancel",
}


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
    has_audience: bool = False,
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

        if connections is not None:
            # 1. Enrichment nodes
            if node_type == "ai.enrich":
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

            if node_type.startswith("linkfinder."):
                connection_name = str(config.get("connection_name") or "")
                if connection_name and ("linkfinder", connection_name) not in connections:
                    issues.append(
                        _issue(
                            "ENRICHMENT_CONNECTION_MISMATCH",
                            f"{connection_name!r} is not a connected linkfinder account.",
                            node_id=node_id,
                        )
                    )

            # 2. Serper sources
            if node_type in ("source.serper_search", "source.serper_people"):
                connection_name = str(config.get("connection_name") or "")
                if connection_name and ("serper", connection_name) not in connections:
                    issues.append(
                        _issue(
                            "SOURCE_CONNECTION_MISMATCH",
                            f"{connection_name!r} is not a connected serper account.",
                            node_id=node_id,
                        )
                    )

            if node_type.startswith("source.linkfinder_"):
                connection_name = str(config.get("connection_name") or "")
                if connection_name and ("linkfinder", connection_name) not in connections:
                    issues.append(
                        _issue(
                            "SOURCE_CONNECTION_MISMATCH",
                            f"{connection_name!r} is not a connected linkfinder account.",
                            node_id=node_id,
                        )
                    )

            # 2b. Apollo data-layer nodes (people search, company enrich, job
            # postings) all require an Apollo connection.
            if node_type in _APOLLO_NODES:
                connection_name = str(config.get("connection_name") or "")
                if connection_name and ("apollo", connection_name) not in connections:
                    issues.append(
                        _issue(
                            "SOURCE_CONNECTION_MISMATCH",
                            f"{connection_name!r} is not a connected apollo account.",
                            node_id=node_id,
                        )
                    )

            # 3. UNIPILE-FULL nodes (channels, native search, enrichment reads,
            # social actions) all use a Unipile connection.
            if node_type in _UNIPILE_NODES:
                connection_name = str(config.get("connection_name") or "")
                if connection_name and ("unipile", connection_name) not in connections:
                    issues.append(
                        _issue(
                            "ACTION_CONNECTION_MISMATCH",
                            f"{connection_name!r} is not a connected unipile account.",
                            node_id=node_id,
                        )
                    )

            if node_type == "channel.email":
                connection_name = str(config.get("connection_name") or "")
                if connection_name and ("smtp", connection_name) not in connections:
                    issues.append(
                        _issue(
                            "ACTION_CONNECTION_MISMATCH",
                            f"{connection_name!r} is not a connected smtp account.",
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
    if not roots:
        issues.append(
            _issue(
                "ENTRY_NODE_COUNT",
                "The campaign needs at least one starting step.",
            )
        )
    else:
        # OUTBOUND-FIRST-001: a campaign may start with a SOURCE (discovers its
        # own leads) OR an entry-capable outbound CHANNEL (reaches out to an
        # attached audience) — lead-gen, outbound, or any mix. A root is valid
        # when its manifest is entry_capable; an outbound (non-source) root
        # additionally needs an attached audience, since it has no upstream to
        # supply recipients. Non-entry roots (a condition/flow/crm with no
        # incoming edge) are a wiring mistake.
        outbound_roots = 0
        for root in roots:
            manifest = manifests.get(root)
            node_type = str(by_id[root].get("node_type") or "")
            if manifest is None:
                continue  # already flagged UNKNOWN_NODE_TYPE
            if not manifest.entry_capable:
                issues.append(
                    _issue(
                        "ENTRY_NOT_CAPABLE",
                        f"{manifest.display_name or manifest.type} can't start a campaign. "
                        "Begin with a source (to find leads) or an outbound step "
                        "(to reach an attached audience).",
                        node_id=root,
                    )
                )
                continue
            is_source = node_type.startswith("source.")
            if not is_source:
                outbound_roots += 1
                if not has_audience:
                    issues.append(
                        _issue(
                            "OUTBOUND_NEEDS_AUDIENCE",
                            f"{manifest.display_name or manifest.type} starts this campaign, "
                            "so it needs an audience to reach. Attach contacts to the campaign.",
                            node_id=root,
                        )
                    )
        source_roots = [
            r for r in roots
            if str(by_id[r].get("node_type") or "").startswith("source.")
        ]
        if len(source_roots) > 1 and outbound_roots == 0:
            issues.append(
                _issue(
                    "MULTI_SOURCE_START",
                    f"This run starts {len(source_roots)} sources together. Results keep source provenance and converge through downstream deduplication.",
                    severity="warning",
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

    if roots:
        reachable: set[str] = set()
        queue = deque(roots)
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
