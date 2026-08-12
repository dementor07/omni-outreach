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
