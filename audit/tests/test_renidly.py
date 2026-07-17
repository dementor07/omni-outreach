"""RENIDLY-001 — Renidly identity-graph enrichment provider.

Locks the Python half of the contract the muscle depends on: the node emits the
SHARED ``ai.enrich.requested`` intent, tagged with ``enrich_source="renidly"``
and a ``renidly_mode`` the muscle can turn into an endpoint. Getting either tag
wrong is a silent void — the event would be published and never dispatched.

The URL/param/envelope logic is pure Rust and unit-tested beside it in
``backend-rust/src/handlers/enrich.rs``.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.nodes import NodeContext, discover, get  # noqa: E402

discover()

_NODE = "renidly.person_profile"


def _ctx(config: dict) -> NodeContext:
    return NodeContext(
        workspace_id="workspace",
        workflow_id="workflow",
        node_id="node",
        lead={"id": "lead-1", "linkedin_url": "https://www.linkedin.com/in/ryanroslansky"},
        config=config,
    )


def test_node_registered_with_handles_and_connection_capability():
    manifest, _ = get(_NODE)
    assert {h.name for h in manifest.output_handles} == {"default", "on_error"}
    # The connection capability binds the node to a `renidly` connection, which is
    # what mints the credential_ref the muscle redeems the api_key from.
    assert "connection:renidly" in manifest.capabilities


@pytest.mark.asyncio
async def test_execute_emits_the_enrich_intent_the_muscle_dispatches_on():
    _, execute = get(_NODE)
    result = await execute(_ctx({"connection_name": "renidly"}))

    event = result.events[0]
    # ai.enrich.requested is the intent the dispatcher already routes to the
    # muscle; handle_enrich then switches on enrich_source. A bespoke event type
    # here would publish into a void (cf. ENRICH-INTENT-001).
    assert event["event_type"] == "ai.enrich.requested"
    assert event["payload"]["enrich_source"] == "renidly"
    assert event["payload"]["renidly_mode"] == "person_profile"
    assert event["payload"]["connection_name"] == "renidly"
    assert result.handle == "default"


@pytest.mark.asyncio
async def test_optional_lookup_inputs_are_forwarded_only_when_set():
    _, execute = get(_NODE)

    bare = await execute(_ctx({"connection_name": "renidly"}))
    # Unset inputs must be ABSENT, not blank: the muscle falls back to the handle
    # in the lead's LinkedIn URL only when no handle/id key is present.
    assert "handle" not in bare.events[0]["payload"]
    assert "renidly_id" not in bare.events[0]["payload"]

    pinned = await execute(_ctx({"connection_name": "renidly", "handle": "someone", "renidly_id": "prsn_1"}))
    assert pinned.events[0]["payload"]["handle"] == "someone"
    assert pinned.events[0]["payload"]["renidly_id"] == "prsn_1"


def test_connection_name_is_required():
    from pydantic import ValidationError

    from app.nodes.enrich.renidly._common import PersonProfileConfig

    with pytest.raises(ValidationError):
        PersonProfileConfig(connection_name="")
