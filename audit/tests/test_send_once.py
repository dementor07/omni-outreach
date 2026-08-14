"""SEND-ONCE-001 — at-most-once send per (lead, node).

Locks the guard that stopped C2 invites being re-dispatched ~3x/lead (a ban-risk
API-call storm). The invite node can be re-entered by a stale hold/retry
redelivery, or by an orchestrator ``__retry__`` emitted for a send that already
reported ``sent``; each re-entry re-published the channel intent, so the seat
burned another provider call for one logical invite. LinkedIn dedupes the message
itself, but the repeated invite CALLS are the ban vector.

The guard consults the confirmed-send ledger keyed on (workspace, lead, node) and
drops the duplicate re-fire — WITHOUT the ``lead_id <>`` exclusion DEDUP-SEND-001
uses (that guard is cross-lead re-contact; this one guards the lead's OWN
re-entry). Genuine retries (a failed send left no ``sent`` row) and DM sequences
(M1/M2/M3 are distinct node ids) are unaffected.

For the guard to match, the outcome must carry node_id — the muscle doesn't
reliably echo it, so _emit_send_outcome falls back to the firing node id.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

REPO = Path(__file__).resolve().parents[2]
TW_SRC = (REPO / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")


# ── the guard reads the ledger keyed on (workspace, lead, node), status='sent' ──


@pytest.mark.asyncio
async def test_guard_true_when_prior_confirmed_send(monkeypatch):
    from app.execution import transition_worker as tw

    async def fake_fetch_one(sql, *args):
        assert "status='sent'" in sql, "guard must only count CONFIRMED sends"
        assert "node_id=$3" in sql, "guard must key on the node"
        return {"?column?": 1}

    monkeypatch.setattr(tw, "fetch_one", fake_fetch_one)
    assert await tw._already_sent_this_node("ws", "lead1", "nodeA") is True


@pytest.mark.asyncio
async def test_guard_false_when_no_prior_send(monkeypatch):
    from app.execution import transition_worker as tw

    async def fake_fetch_one(sql, *args):
        return None  # a held or failed send left no 'sent' row → proceed

    monkeypatch.setattr(tw, "fetch_one", fake_fetch_one)
    assert await tw._already_sent_this_node("ws", "lead1", "nodeA") is False


@pytest.mark.asyncio
async def test_guard_keys_on_workspace_lead_node(monkeypatch):
    from app.execution import transition_worker as tw

    seen: dict = {}

    async def fake_fetch_one(sql, *args):
        seen["args"] = args
        return None

    monkeypatch.setattr(tw, "fetch_one", fake_fetch_one)
    await tw._already_sent_this_node("ws1", "leadX", "nodeY")
    assert seen["args"] == ("ws1", "leadX", "nodeY")


# ── the guard is NOT the cross-lead dedupe: it must include the lead's own sends ─


def test_guard_does_not_exclude_own_lead():
    """DEDUP-SEND-001 excludes the current lead (M1 must not block M2). SEND-ONCE
    must NOT — it guards the lead's own re-entry of the SAME node, so excluding
    the lead would defeat it entirely."""
    tree = ast.parse(TW_SRC)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_already_sent_this_node"
    )
    src = ast.get_source_segment(TW_SRC, fn)
    assert "lead_id=$2" in src
    assert "lead_id <>" not in src, "SEND-ONCE must not exclude the lead's own sends"


# ── _fire_node consults the guard on the outbound path, before dispatch ─────────


def test_fire_node_calls_guard():
    tree = ast.parse(TW_SRC)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_fire_node"
    )
    calls = {
        node.func.id for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_already_sent_this_node" in calls, "_fire_node must call the SEND-ONCE-001 guard"


# ── the outcome carries node_id so the guard can match ──────────────────────────


# ── SEND-ONCE-002: the drop must not STRAND the lead ───────────────────────────
#
# The original guard bare-returned. A lead still parked ON the send node then sat
# there forever, because every later re-fire hit the same guard. Live fallout:
# 13 C1/C2 leads whose invite/DM reached a real prospect but whose sequence never
# resumed — the 8 invite cases could never reach event.invite_accepted, so their
# acceptance would never have started a DM.


def _lead(node_id: str, current: str | None):
    return {"id": "lead1", "current_node_id": current, "workflow_id": "wf1"}, {"id": node_id}


@pytest.mark.asyncio
async def test_stranded_lead_advances_on_the_sent_edge(monkeypatch):
    """Parked ON the already-sent node → resume down the same edge a real send takes."""
    from app.execution import transition_worker as tw

    advanced: dict = {}

    async def fake_edge(ws, node_id, handle):
        assert handle == "sent", "recovery must use the success edge, not on_error"
        return {"target_node_id": "next-node"}

    async def fake_advance(ws, lead_id, target, corr):
        advanced.update(lead_id=lead_id, target=target)

    async def fail_terminalize(*a, **kw):
        raise AssertionError("must advance, not terminalize, when a sent edge exists")

    monkeypatch.setattr(tw, "_outgoing_edge", fake_edge)
    monkeypatch.setattr(tw, "_advance_and_fire", fake_advance)
    monkeypatch.setattr(tw, "_terminalize_lead", fail_terminalize)

    lead, node = _lead("nodeA", "nodeA")
    assert await tw._resume_after_confirmed_send("ws", lead, node, "corr") is True
    assert advanced == {"lead_id": "lead1", "target": "next-node"}


@pytest.mark.asyncio
async def test_stranded_lead_at_a_leaf_terminalizes_honestly(monkeypatch):
    """No sent edge → complete the lead rather than leave it parked."""
    from app.execution import transition_worker as tw

    ended: dict = {}

    async def fake_edge(ws, node_id, handle):
        return None

    async def fake_terminalize(ws, lead_id, status, corr):
        ended.update(lead_id=lead_id, status=status)

    monkeypatch.setattr(tw, "_outgoing_edge", fake_edge)
    monkeypatch.setattr(tw, "_terminalize_lead", fake_terminalize)

    lead, node = _lead("nodeA", "nodeA")
    assert await tw._resume_after_confirmed_send("ws", lead, node, "corr") is True
    # 'sent' is a success handle, so the honest leaf status is completed.
    assert ended == {"lead_id": "lead1", "status": "completed"}


@pytest.mark.asyncio
async def test_already_advanced_lead_is_left_alone(monkeypatch):
    """The ordinary stale redelivery: the lead moved on, so dropping is correct.

    This is the half that must NOT regress — re-advancing a lead that already
    progressed would drag it backwards through the graph.
    """
    from app.execution import transition_worker as tw

    async def fail(*a, **kw):
        raise AssertionError("a lead that already advanced must not be touched")

    monkeypatch.setattr(tw, "_outgoing_edge", fail)
    monkeypatch.setattr(tw, "_advance_and_fire", fail)
    monkeypatch.setattr(tw, "_terminalize_lead", fail)

    lead, node = _lead("nodeA", "some-later-node")
    assert await tw._resume_after_confirmed_send("ws", lead, node, "corr") is False


@pytest.mark.asyncio
async def test_terminal_lead_with_no_node_is_left_alone(monkeypatch):
    """current_node_id is NULL on a terminalized lead — never resurrect it."""
    from app.execution import transition_worker as tw

    async def fail(*a, **kw):
        raise AssertionError("a terminal lead must not be resumed")

    monkeypatch.setattr(tw, "_outgoing_edge", fail)
    monkeypatch.setattr(tw, "_advance_and_fire", fail)
    monkeypatch.setattr(tw, "_terminalize_lead", fail)

    lead, node = _lead("nodeA", None)
    assert await tw._resume_after_confirmed_send("ws", lead, node, "corr") is False


def test_fire_node_never_bare_returns_on_the_guard():
    """The guard branch must consult the recovery helper, not just return."""
    tree = ast.parse(TW_SRC)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_fire_node"
    )
    calls = {
        node.func.id for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_resume_after_confirmed_send" in calls, (
        "_fire_node must resume a stranded lead, not bare-return on the SEND-ONCE guard"
    )


@pytest.mark.asyncio
async def test_emit_send_outcome_falls_back_to_firing_node_id(monkeypatch):
    from app.execution import transition_worker as tw

    captured: dict = {}

    async def fake_publish_event(**kw):
        captured.update(kw)

    monkeypatch.setattr(tw.bus, "publish_event", fake_publish_event)
    await tw._emit_send_outcome(
        "ws", "channel.linkedin_invite", "lead1",
        {"contact_id": "c1", "workflow_id": "wf1"},
        {"status": "sent", "command_id": "cmd1"},  # muscle echoed NO node_id
        {}, "corr", firing_node_id="nodeZ",
    )
    assert captured["payload"]["node_id"] == "nodeZ"


@pytest.mark.asyncio
async def test_emit_send_outcome_prefers_muscle_node_id(monkeypatch):
    """If the muscle DID echo node_id, keep it (the fallback is only a backstop)."""
    from app.execution import transition_worker as tw

    captured: dict = {}

    async def fake_publish_event(**kw):
        captured.update(kw)

    monkeypatch.setattr(tw.bus, "publish_event", fake_publish_event)
    await tw._emit_send_outcome(
        "ws", "channel.linkedin_invite", "lead1",
        {"contact_id": "c1", "workflow_id": "wf1"},
        {"status": "sent", "command_id": "cmd1", "node_id": "muscle-node"},
        {}, "corr", firing_node_id="nodeZ",
    )
    assert captured["payload"]["node_id"] == "muscle-node"
