"""B7 regression — conversion alert (lead.converted) on the flow.goal claim path.

When a lead reaches a flow.goal node it terminalizes 'converted'. B7 makes that
worth surfacing on its own: `_fire_node` emits a `lead.converted` event so the
operator is told without having to wire a crm.hot_lead_alert by hand. The emit
is gated on the `_terminalize_lead` claim (`claimed`) so a redelivered goal-fire
never double-alerts — the claim is the idempotency key. flow.end is a dead-end,
NOT a conversion, so it must NOT emit.

Source-level invariants (no live DB): the seam shape is what guarantees the
contract under Kafka at-least-once redelivery.

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
WORKER = (BACKEND / "app" / "execution" / "transition_worker.py").read_text(encoding="utf-8")


def _goal_branch() -> str:
    """The flow.goal/flow.end terminal branch of _fire_node."""
    after = WORKER.split('if node_type in ("flow.goal", "flow.end"):', 1)
    assert len(after) == 2, "the flow.goal/flow.end terminal branch must exist"
    # bound it at the next top-level `if commands.` or end-of-function marker so
    # the assertions can't bleed into unrelated code.
    return after[1]


def test_goal_emits_lead_converted():
    branch = _goal_branch()
    assert 'event_type="lead.converted"' in branch, "flow.goal must emit lead.converted"


def test_emit_is_gated_on_the_claim_for_idempotency():
    branch = _goal_branch()
    # the terminalize returns the claim bool, and the emit must be gated on it.
    assert "claimed = await _terminalize_lead" in branch, "must capture the claim bool"
    emit_pos = branch.find('event_type="lead.converted"')
    gate_pos = branch.find('if node_type == "flow.goal" and claimed:')
    assert gate_pos != -1, "emit must be gated on goal + claimed"
    assert gate_pos < emit_pos, "the claim gate must guard the emit (idempotent on redelivery)"


def test_end_is_a_dead_end_not_a_conversion():
    branch = _goal_branch()
    # flow.end terminalizes 'ended' and must NOT trip the conversion alert: the
    # gate is `node_type == "flow.goal"`, so a flow.end fire can't emit.
    assert 'terminal_status = "converted" if node_type == "flow.goal" else "ended"' in branch
    assert '== "flow.goal" and claimed' in branch, "only flow.goal converts"


def test_converted_is_a_terminal_status():
    line = next(line for line in WORKER.splitlines() if line.startswith("TERMINAL_STATUSES"))
    assert "converted" in line, "converted must be terminal so the goal claim is idempotent"
