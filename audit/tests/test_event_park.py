"""EVENT-PARK-001: event.* wait nodes must not strand leads forever.

The three event nodes (email_opened / link_clicked / invite_accepted) used to
return park=True while emitting a `wait.requested` event that NOTHING consumed,
and the worker scheduled NO timeout — so any lead reaching them hung forever.

These tests pin the fix:
  1. each node parks and declares a non-zero `timeout_seconds` in telemetry;
  2. no node emits the dead `wait.requested` event;
  3. the resume bridge maps the three real signals to the right node+handle;
  4. the worker's park branch schedules a `timeout` escape from `timeout_seconds`.
Static/functional checks (house style) — no DB, no Kafka.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.nodes import NodeContext, discover, get  # noqa: E402

TW_SRC = (ROOT / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
TRACK_SRC = (ROOT / "backend/app/routers/tracking.py").read_text(encoding="utf-8")

_EVENT_NODES = {
    "event.email_opened": ("opened", 72 * 3600),
    "event.link_clicked": ("clicked", 72 * 3600),
    "event.invite_accepted": ("accepted", 168 * 3600),
}


def _run(coro):
    return asyncio.run(coro)


def test_event_nodes_park_and_declare_timeout():
    """Each event node parks, declares timeout_seconds, and emits no events."""
    discover()
    for node_type, (success_handle, expected_timeout) in _EVENT_NODES.items():
        manifest, execute = get(node_type)
        handles = {h.name for h in manifest.output_handles}
        assert success_handle in handles and "timeout" in handles, (
            f"{node_type} must expose its success handle and a timeout handle"
        )
        ctx = NodeContext(
            workspace_id="ws", workflow_id="wf", node_id="n1",
            config={}, lead={"id": "lead-1", "custom_fields": {}}, correlation_id="corr",
        )
        result = _run(execute(ctx))
        assert result.park is True, f"{node_type} must park the lead"
        assert not result.events, (
            f"{node_type} still emits events (the dead wait.requested bug) — must emit none"
        )
        assert (result.telemetry or {}).get("timeout_seconds") == expected_timeout, (
            f"{node_type} must declare timeout_seconds so the worker can schedule a timeout escape"
        )


def test_no_node_emits_dead_wait_requested():
    """The wait.requested event (no consumer) must be gone from every event node."""
    for fname in ("email_opened.py", "link_clicked.py", "invite_accepted.py"):
        src = (ROOT / f"backend/app/nodes/events/{fname}").read_text(encoding="utf-8")
        assert "wait.requested" not in src, (
            f"{fname} still emits wait.requested — a no-consumer event that strands the lead"
        )


def test_resume_bridge_maps_signals_to_node_and_handle():
    """services.event_resume must map each signal to the correct (node, handle)."""
    from app.services import event_resume

    assert event_resume._SIGNAL_RESUME == {
        "email_opened": ("event.email_opened", "opened"),
        "link_clicked": ("event.link_clicked", "clicked"),
        "invite_accepted": ("event.invite_accepted", "accepted"),
        # MAILGUN-001: real delivery/bounce webhooks resume the matching event node.
        "email_delivered": ("event.email_delivered", "delivered"),
        "email_bounced": ("event.email_bounced", "bounced"),
    }


def test_tracking_router_calls_resume_bridge():
    """tracking.py must drive the resume bridge on an open/click hit, or a parked
    lead never wakes on the real signal."""
    assert "event_resume" in TRACK_SRC and "resume_on_signal" in TRACK_SRC, (
        "tracking.py no longer calls the EVENT-PARK-001 resume bridge"
    )


def test_worker_park_branch_schedules_timeout_escape():
    """The worker's park path must schedule a delayed `timeout` transition from the
    node's timeout_seconds — the escape that stops the lead stranding forever."""
    park_at = TW_SRC.find("if result.park:")
    assert park_at != -1
    # window from the park branch to the next decision block
    window = TW_SRC[park_at:park_at + 1600]
    assert 'timeout_seconds' in window, "park branch doesn't read timeout_seconds"
    assert '"timeout"' in window, "park branch doesn't fire the timeout handle"
    assert "_emit_synthetic_result(" in window and "delay_seconds=" in window, (
        "park branch doesn't schedule a delayed timeout transition"
    )


def test_timeout_handle_path_is_park_safe():
    """The handle=='timeout' path must guard on the lead still being parked here,
    so a timeout that races a success-resume is a safe no-op (not a double-advance).

    RACE-PARK-001 upgraded the old check-then-act `still_waiting` read to a single
    atomic waiting→active claim (_claim_parked_node) — exactly one of {timeout,
    resume} wins the row. The detailed claim invariants live in
    test_park_race_guard.py; here we just pin that the timeout path claims before
    it acts."""
    assert 'if handle == "timeout":' in TW_SRC
    seg = TW_SRC.split('if handle == "timeout":', 1)[1][:600]
    assert "_claim_parked_node(" in seg, (
        "timeout path lost its atomic parked-node claim (would double-fire vs success resume)"
    )
