"""Starter-template integrity proof.

A campaign template (app/canvas_templates.py) seeds a ready-to-run graph for
the cold-start "New campaign" flow. A template that references an unregistered
node_type, a config the node's schema rejects, or an edge on a handle the node
never emits would instantiate a broken/dead-ended workflow — and the failure
would only surface when an operator hit Run.

This test encodes the same checks the author runs by hand, as a regression
invariant: it caught (pre-merge) a verify->screen edge on a nonexistent "pass"
handle, a resolve_company edge on "default" (it emits new/known/rejected), a
serper_people config using a nonexistent field, and channel nodes whose
success handle is "sent" not "default".
"""

from __future__ import annotations

import os

# Test stack env (mirrors backend/tests/conftest.py) so importing app.* doesn't
# trip config's placeholder-secret guard. No DB connection is opened here.
os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest  # noqa: E402

from app.canvas_templates import TEMPLATES, list_templates  # noqa: E402
from app.nodes import discover, get  # noqa: E402

discover()

_TEMPLATE_IDS = list(TEMPLATES)


def test_catalog_nonempty_and_matches_registry() -> None:
    cat = list_templates()
    assert cat, "no starter templates registered"
    assert {c["id"] for c in cat} == set(TEMPLATES)
    for c in cat:
        assert c["name"] and c["summary"], f"template {c['id']} missing name/summary"


@pytest.mark.parametrize("tpl_id", _TEMPLATE_IDS)
def test_template_node_types_registered(tpl_id: str) -> None:
    tpl = TEMPLATES[tpl_id]
    for n in tpl.nodes:
        get(n.node_type)  # raises KeyError if not registered


@pytest.mark.parametrize("tpl_id", _TEMPLATE_IDS)
def test_template_configs_validate(tpl_id: str) -> None:
    tpl = TEMPLATES[tpl_id]
    for n in tpl.nodes:
        manifest, _ = get(n.node_type)
        # Raises pydantic ValidationError if the seeded config is invalid.
        manifest.config_schema(**n.config)


@pytest.mark.parametrize("tpl_id", _TEMPLATE_IDS)
def test_template_edges_reference_real_keys_and_handles(tpl_id: str) -> None:
    tpl = TEMPLATES[tpl_id]
    keys = {n.key for n in tpl.nodes}
    handles_by_key = {}
    for n in tpl.nodes:
        manifest, _ = get(n.node_type)
        handles_by_key[n.key] = {h.name for h in manifest.output_handles}
    for e in tpl.edges:
        assert e.source in keys, f"{tpl_id}: edge from unknown node {e.source!r}"
        assert e.target in keys, f"{tpl_id}: edge to unknown node {e.target!r}"
        assert e.source_handle in handles_by_key[e.source], (
            f"{tpl_id}: edge {e.source}->{e.target} on handle {e.source_handle!r} "
            f"which {e.source} never emits (has {sorted(handles_by_key[e.source])})"
        )


@pytest.mark.parametrize("tpl_id", _TEMPLATE_IDS)
def test_template_has_single_entry_capable_node(tpl_id: str) -> None:
    """A template must have exactly one node with no incoming edge (the entry),
    and that node must be ENTRY-CAPABLE. Post OUTBOUND-FIRST-001 that means a
    source.* (discovers its own audience) OR an outbound channel that starts the
    journey by messaging an attached audience — the manifest's own entry_capable
    property is the authority, not a name prefix."""
    tpl = TEMPLATES[tpl_id]
    targeted = {e.target for e in tpl.edges}
    entries = [n for n in tpl.nodes if n.key not in targeted]
    assert len(entries) == 1, f"{tpl_id}: expected 1 entry node, got {[e.key for e in entries]}"
    manifest, _ = get(entries[0].node_type)
    assert manifest.entry_capable, (
        f"{tpl_id}: entry node {entries[0].node_type} is not entry-capable "
        "(can't seed the run path)"
    )
