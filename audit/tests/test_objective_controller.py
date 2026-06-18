"""Campaign Objective controller regression (ADR campaign-objective-controller).

The controller closes the goal-pursuit loop: when a campaign's ROOT run-lead
completes, it measures progress and either stops (reached/exhausted) or widens +
re-runs. These cover the pure decision matrix (`decide`) + the safety-critical
wire-in invariants:
  - the worker hook fires only for a ROOT lead (no parent), gated on the
    once-only terminalize claim, and is best-effort (can't wedge the claim);
  - re-seed is a FRESH root lead via the run path (no graph back-edge — the
    for_each cycle-explosion class stays impossible).

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services.objective_controller import (
    DEFAULT_MAX_ITERATIONS,
    decide,
    widen_audience,
)

BACKEND = Path(__file__).resolve().parents[2] / "backend"


# ── decide(): the pure goal-pursuit matrix ───────────────────────────────────

def test_reached_when_target_met():
    v = decide(current=20, target=20, iterations_used=0, spend_usd=0.0, bounds={})
    assert v.decision == "reached" and v.next_status == "reached"


def test_reached_wins_even_at_iteration_cap():
    # hitting the target on the last allowed iteration is success, not exhaustion
    v = decide(current=25, target=20, iterations_used=5, spend_usd=999.0, bounds={"max_iterations": 5})
    assert v.decision == "reached"


def test_widen_when_short_and_within_bounds():
    v = decide(current=13, target=20, iterations_used=1, spend_usd=1.0, bounds={"max_iterations": 5})
    assert v.decision == "widen" and v.next_status == "pursuing"


def test_exhausted_at_max_iterations():
    v = decide(current=13, target=20, iterations_used=5, spend_usd=0.0, bounds={"max_iterations": 5})
    assert v.decision == "exhausted" and v.next_status == "exhausted"


def test_exhausted_at_spend_cap():
    v = decide(current=5, target=20, iterations_used=1, spend_usd=10.0, bounds={"max_spend_usd": 10})
    assert v.decision == "exhausted"


def test_exhausted_past_deadline():
    v = decide(
        current=5, target=20, iterations_used=1, spend_usd=0.0,
        bounds={"deadline": "2020-01-01"}, today=date(2026, 6, 18),
    )
    assert v.decision == "exhausted"


def test_default_max_iterations_applies_when_unset():
    # no max_iterations in bounds -> DEFAULT_MAX_ITERATIONS is the cap
    v = decide(current=0, target=99, iterations_used=DEFAULT_MAX_ITERATIONS, spend_usd=0.0, bounds={})
    assert v.decision == "exhausted"


# ── widen_audience(): each iteration must vary the input ─────────────────────

def test_widen_advances_keyword_index():
    aud = {"keywords": ["Software Engineer", "DevOps Engineer", "Data Engineer"]}
    o0, _ = widen_audience(aud, 0)
    o1, _ = widen_audience(aud, 1)
    assert o0["keyword"] != o1["keyword"], "consecutive widenings must source different roles"
    assert o0["keyword"] in aud["keywords"]


def test_widen_falls_back_to_page_depth_without_keywords():
    overrides, _ = widen_audience({"max_pages": 5}, 0)
    assert overrides["max_pages"] > 5, "no keyword ladder -> widen by scraping deeper"


# ── wire-in: the worker hook (safety-critical) ───────────────────────────────

def test_worker_hooks_controller_on_root_lead_completion():
    src = (BACKEND / "app" / "execution" / "transition_worker.py").read_text(encoding="utf-8")
    body = src.split("async def _terminalize_lead", 1)[1]
    assert "objective_controller.evaluate_on_completion" in body, "controller must fire on completion"
    # it must be in the ROOT branch (the elif after the parent-barrier branch),
    # i.e. only when there's no parent_lead_id — a fan-out child must NOT trigger it.
    assert "elif row.get(\"workflow_id\")" in body, "hook must be the no-parent (root) branch"
    # best-effort: a controller error cannot wedge the terminalize claim.
    assert "except Exception" in body and "objective controller failed" in body


def test_reseed_uses_fresh_root_lead_no_backedge():
    src = (BACKEND / "app" / "services" / "objective_controller.py").read_text(encoding="utf-8")
    body = src.split("async def _reseed_and_fire", 1)[1]
    # a brand-new lead id + INSERT (fresh lineage), NOT an edge back into the graph
    assert "uuid.uuid4()" in body and "INSERT INTO omni_leads" in body
    assert "contact_id, workflow_id, current_node_id, status" in body
