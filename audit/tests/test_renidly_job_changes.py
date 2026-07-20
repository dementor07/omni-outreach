"""RENIDLY-002 — the Renidly job-changes FAN-OUT lead source.

The source is a thin intent-emitter (the muscle's RenidlyJobChanges handler does
the HTTP call + normalises each person into custom_fields[people_key]). This
locks the Python contract the muscle depends on: the node emits
``source.renidly_job_changes.requested`` with the people_key + paging inputs, is
routed through NODE_CHANNEL (not dead-on-arrival), and carries the
``connection:renidly`` capability so a credential_ref is minted. The person-row
normalisation + envelope handling are pure Rust, unit-tested beside the handler
in ``backend-rust/src/handlers/renidly.rs``.
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

from app.core.events import ChannelType  # noqa: E402
from app.execution.commands import NODE_CHANNEL  # noqa: E402
from app.nodes import NodeContext, discover, get  # noqa: E402

discover()

_NODE = "source.renidly_job_changes"


def _ctx(config: dict) -> NodeContext:
    return NodeContext(workspace_id="ws", workflow_id="wf", node_id="n1", lead={"id": "l1"}, config=config)


def test_registered_as_a_fanout_source_routed_through_the_muscle():
    manifest, _ = get(_NODE)
    assert manifest.category.value == "source"
    assert manifest.entry_capable, "a source must be able to root a campaign"
    assert {h.name for h in manifest.output_handles} == {"default", "empty", "on_error"}
    assert "connection:renidly" in manifest.capabilities
    # RENIDLY-002: routed through the muscle (NOT a locally-resolved in-process
    # source) — the handler writes custom_fields[people_key] for flow.for_each.
    assert NODE_CHANNEL[_NODE] == ChannelType.RENIDLY_JOB_CHANGES


@pytest.mark.asyncio
async def test_emits_the_fanout_intent_with_paging_and_people_key():
    _, execute = get(_NODE)
    result = await execute(
        _ctx({"connection_name": "renidly", "limit": 3, "randomize_page": True, "max_page": 30})
    )
    assert result.handle == "default"
    event = result.events[0]
    assert event["event_type"] == "source.renidly_job_changes.requested"
    p = event["payload"]
    assert p["connection_name"] == "renidly"
    assert p["limit"] == 3
    assert p["randomize_page"] is True
    assert p["max_page"] == 30
    # people_key tells the muscle where to write the list flow.for_each reads.
    assert p["people_key"] == "people"


@pytest.mark.asyncio
async def test_defaults_are_demo_friendly():
    _, execute = get(_NODE)
    p = (await execute(_ctx({"connection_name": "renidly"}))).events[0]["payload"]
    assert p["limit"] == 3  # "three contacts at a time"
    assert p["page"] == 1
    assert p["randomize_page"] is False
    assert p["people_key"] == "people"


def test_connection_name_is_required():
    from pydantic import ValidationError

    from app.nodes.sources.renidly_job_changes import RenidlyJobChangesConfig

    with pytest.raises(ValidationError):
        RenidlyJobChangesConfig(connection_name="")
