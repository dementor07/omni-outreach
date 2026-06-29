"""DEDUP-SEND-001 + GATE-ENTRY-001 — proven live, locked here as regression.

These were verified end-to-end on the box first (a real /run enrolled a lead at a
LinkedIn entry node; the already-messaged contact's lead ENDED with no new send,
and a suppressed contact's lead terminated 'suppressed' with no send). This file
pins the wiring so a refactor can't silently un-hook either:

  - every PERSON-addressable channel (not slack/webhook_out) carries the opt-in
    dedupe config (default off) AND declares the `already_messaged` handle;
  - the runtime guard `_dedupe_send` decides skip/end from the durable send
    ledger and the node's action/scope (behaviour, not a string match);
  - GATE-ENTRY-001: the outbound-first entry path (seed_and_run_audience) fires
    the entry node THROUGH _fire_node — the one gated send path — rather than
    publishing the intent directly (which bypassed DNC/caps/window/dedupe).

Pure/static + a behavioural unit test of the guard with the DB calls stubbed.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

from app.nodes import discover, get

REPO = Path(__file__).resolve().parents[2]
RUN_SRC = (REPO / "backend/app/execution/run.py").read_text(encoding="utf-8")

_PERSON_CHANNELS = ["linkedin", "email", "sms", "whatsapp", "instagram", "telegram", "voice"]
_NON_PERSON = ["slack", "webhook_out"]

discover()


# ── every person channel carries the opt-in config + handle ──────────────────


@pytest.mark.parametrize("chan", _PERSON_CHANNELS)
def test_person_channel_has_dedupe_config_and_handle(chan):
    manifest, _fn = get(f"channel.{chan}")
    handles = {h.name for h in manifest.output_handles}
    assert "already_messaged" in handles, f"{chan}: missing already_messaged handle"
    props = manifest.config_schema.model_json_schema()["properties"]
    # opt-in: default off (zero behaviour change for saved graphs) + safe scope.
    assert props["dedupe_action"]["default"] == "off", f"{chan}: dedupe must default off"
    assert props["dedupe_scope"]["default"] == "channel", f"{chan}: scope must default channel"


@pytest.mark.parametrize("chan", _NON_PERSON)
def test_non_person_channel_has_no_dedupe(chan):
    # slack (team alert) + webhook_out (HTTP sink) carry no contact recipient —
    # deduping them would be a category error.
    manifest, _fn = get(f"channel.{chan}")
    props = manifest.config_schema.model_json_schema()["properties"]
    assert "dedupe_action" not in props, f"{chan}: must NOT carry dedupe config"


def test_person_channels_are_the_send_subset():
    from app.execution import transition_worker as tw

    want = {f"channel.{c}" for c in _PERSON_CHANNELS}
    assert tw._PERSON_MESSAGE_CHANNELS == want
    # the subset must be exactly the send channels minus the non-person ones.
    assert tw._PERSON_MESSAGE_CHANNELS <= tw._OUTBOUND_SEND_CHANNELS
    for c in _NON_PERSON:
        assert f"channel.{c}" not in tw._PERSON_MESSAGE_CHANNELS


def test_already_messaged_leaf_ends_honestly():
    # an unwired already_messaged skip ends 'ended', never a false 'completed'.
    from app.execution.transition_worker import _leaf_terminal_status

    assert _leaf_terminal_status("already_messaged") == "ended"


# ── behavioural: the guard decides from the ledger + config ──────────────────


@pytest.mark.asyncio
async def test_dedupe_guard_off_proceeds_without_a_ledger_read():
    """dedupe_action=off → guard returns False (send proceeds) and never queries
    the ledger. Proven by leaving fetch_one un-stubbed: a query would raise."""
    from app.execution import transition_worker as tw

    handled = await tw._dedupe_send(
        "ws", {"id": "l1", "contact_id": "c1"}, {"id": "c1"},
        {"id": "n1", "config": {"dedupe_action": "off"}},
        "channel.linkedin", "wf1", "corr",
    )
    assert handled is False


@pytest.mark.asyncio
async def test_dedupe_guard_end_lead_terminalizes_on_prior_send(monkeypatch):
    """A prior status='sent' in the ledger + action=end_lead → the guard
    terminalizes the lead and returns True (caller must not send)."""
    from app.execution import transition_worker as tw

    async def fake_fetch_one(*_a, **_k):
        return {"?column?": 1}  # a prior send exists

    terminalized: dict = {}

    async def fake_terminalize(ws, lead_id, status, corr):
        terminalized["status"] = status

    monkeypatch.setattr(tw, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(tw, "_terminalize_lead", fake_terminalize)

    handled = await tw._dedupe_send(
        "ws", {"id": "l1", "contact_id": "c1"}, {"id": "c1"},
        {"id": "n1", "config": {"dedupe_action": "end_lead", "dedupe_scope": "channel"}},
        "channel.linkedin", "wf1", "corr",
    )
    assert handled is True
    assert terminalized["status"] == "ended"


@pytest.mark.asyncio
async def test_dedupe_guard_no_prior_send_proceeds(monkeypatch):
    from app.execution import transition_worker as tw

    async def fake_fetch_one(*_a, **_k):
        return None  # never messaged

    monkeypatch.setattr(tw, "fetch_one", fake_fetch_one)
    handled = await tw._dedupe_send(
        "ws", {"id": "l1", "contact_id": "c1"}, {"id": "c1"},
        {"id": "n1", "config": {"dedupe_action": "skip_step"}},
        "channel.linkedin", "wf1", "corr",
    )
    assert handled is False


@pytest.mark.asyncio
async def test_contactless_lead_cannot_be_deduped(monkeypatch):
    # a discovered person before a contact row exists has no contact_id — there's
    # nothing to compare a prior send to, so the send proceeds (never blocks blind).
    from app.execution import transition_worker as tw

    handled = await tw._dedupe_send(
        "ws", {"id": "l1", "contact_id": None}, None,
        {"id": "n1", "config": {"dedupe_action": "end_lead"}},
        "channel.linkedin", "wf1", "corr",
    )
    assert handled is False


# ── GATE-ENTRY-001: the entry send goes through the gated path ───────────────


def test_seed_and_run_audience_fires_through_fire_node():
    """The outbound-first entry path must delegate firing to _fire_node (the one
    seam that owns DNC + cap/window + schedule + dedupe), NOT publish the intent
    directly. Pinned structurally: seed_and_run_audience imports _fire_node and
    calls it, and does NOT call bus.publish_event for the entry intent."""
    tree = ast.parse(RUN_SRC)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "seed_and_run_audience"
    )
    calls = {
        (node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id)
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert "_fire_node" in calls, "entry node must fire through _fire_node (gated path)"
    assert "publish_event" not in calls, (
        "seed_and_run_audience must NOT publish the entry intent directly — that "
        "bypassed DNC/caps/window/dedupe (GATE-ENTRY-001)"
    )


def test_source_seed_path_unchanged_no_fire_node():
    # seed_and_run (the SOURCE path) is intentionally NOT routed through _fire_node:
    # a source discovers entities and carries no recipient to gate. Pin that the
    # gate-entry change was scoped to the audience path only.
    tree = ast.parse(RUN_SRC)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "seed_and_run"
    )
    calls = {
        node.func.attr for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "publish_event" in calls, "the source path still publishes its discovery intent directly"
