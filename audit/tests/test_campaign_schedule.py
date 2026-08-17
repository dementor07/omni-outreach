"""B6 regression — campaign scheduling window (start_at / end_at).

A workflow may carry a send window. At the outbound-send seam (_fire_node):
  - now >= end_at  → the lead ENDS (campaign over), no send
  - now <  start_at → the lead is HELD via a delayed __retry__ synthetic (the
    Flink processing-time timer) that RE-FIRES this same channel node once the
    start passes — then the gate falls through to the real send
  - both NULL / inside the window → sends normally

The gate must sit BEFORE the T1 DNC check and only apply to outbound channels.
Source-level invariants (the worker is DB/Kafka-bound).

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
WORKER = (BACKEND / "app" / "execution" / "transition_worker.py").read_text(encoding="utf-8")
CANVAS = (BACKEND / "app" / "routers" / "canvas.py").read_text(encoding="utf-8")
MIGRATION = (BACKEND / "alembic" / "versions" / "035_workflow_schedule.py").read_text(encoding="utf-8")


def _gate() -> str:
    """The B6 schedule gate block in _fire_node."""
    after = WORKER.split("B6 — campaign schedule window", 1)
    assert len(after) == 2, "the B6 schedule gate must exist in _fire_node"
    # bound at the T1 DNC comment that follows it
    return after[1].split("T1 — DNC enforcement", 1)[0]


def test_gate_only_applies_to_outbound_channels():
    gate = _gate()
    assert "node_type in _OUTBOUND_SEND_CHANNELS" in gate


def test_end_at_ends_the_lead():
    gate = _gate()
    assert "end_at" in gate
    assert 'now >= end_at' in gate
    assert '"ended"' in gate, "after end_at the lead terminalizes 'ended'"


def test_start_at_holds_via_delayed_retry():
    gate = _gate()
    assert "now < start_at" in gate
    assert "delay_seconds=hold_seconds" in gate
    # the hold re-fires THIS node (not advance) via the __retry__ handle
    assert '"__retry__"' in gate
    # parked 'waiting' while it holds
    assert "status=\"waiting\"" in gate or "status='waiting'" in gate


def test_gate_precedes_dnc_check():
    fire = WORKER.split("async def _fire_node", 1)[1]
    sched_pos = fire.find("B6 — campaign schedule window")
    dnc_pos = fire.find("T1 — DNC enforcement at the outbound-send seam")
    assert sched_pos != -1 and dnc_pos != -1
    assert sched_pos < dnc_pos, "schedule gate must run before the DNC query"


def test_schedule_helper_defaults_to_none():
    body = WORKER.split("async def _workflow_schedule", 1)[1][:400]
    assert "return None, None" in body, "no workflow_id / no row => always-on"
    assert "SELECT start_at, end_at FROM omni_workflows" in body


def test_canvas_exposes_schedule():
    assert "start_at: datetime | None" in CANVAS
    assert "end_at: datetime | None" in CANVAS


def test_migration_adds_columns():
    assert "ADD COLUMN IF NOT EXISTS start_at" in MIGRATION
    assert "ADD COLUMN IF NOT EXISTS end_at" in MIGRATION
    assert 'down_revision = "034"' in MIGRATION
