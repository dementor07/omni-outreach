"""Campaign Objective regression (ADR campaign-objective-controller).

The goal-pursuit loop is event-driven: when a campaign's ROOT run-lead
terminalizes, the transition worker EMITS `campaign.run.completed` (a fact, not
a control loop), and the dedicated objective worker consumes it, measures
LINEAGE-SCOPED progress, decides (reached/widen/exhausted), and re-seeds via the
SHARED run path on a widen.

These cover the pure decision matrix + the architectural invariants that keep
the loop in the right place:
  - the transition worker emits a fact (no control loop inside its
    safety-critical terminalize claim);
  - the worker measures the campaign's OWN lineage, never the whole workspace;
  - re-seed reuses app.execution.run.seed_and_run (no copied seed path, no graph
    back-edge — the for_each cycle-explosion class stays impossible);
  - only honestly-measurable metrics are offered.

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services.objective_controller import (
    DEFAULT_MAX_ITERATIONS,
    MEASURABLE_METRICS,
    decide,
    widen_audience,
)

BACKEND = Path(__file__).resolve().parents[2] / "backend"


# ── decide(): the pure goal-pursuit matrix ───────────────────────────────────

def test_reached_when_target_met():
    v = decide(current=20, target=20, iterations_used=0, spend_usd=0.0, bounds={})
    assert v.decision == "reached" and v.next_status == "reached"


def test_reached_wins_even_at_iteration_cap():
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
    v = decide(current=0, target=99, iterations_used=DEFAULT_MAX_ITERATIONS, spend_usd=0.0, bounds={})
    assert v.decision == "exhausted"


# ── widen_audience(): each iteration varies the input; field matches the node ─

def test_widen_advances_keyword_index_as_query():
    # search/apollo/clutch sources take `query`; consecutive widenings differ.
    aud = {"keywords": ["lead gen agency", "appointment setting agency", "SDR agency"]}
    o0, _ = widen_audience(aud, 0)
    o1, _ = widen_audience(aud, 1)
    assert "query" in o0 and "query" in o1
    assert o0["query"] != o1["query"], "consecutive widenings must source a different slice"


def test_widen_uses_keyword_field_for_naukri():
    aud = {"keywords": ["SDR", "AE"]}
    o, _ = widen_audience(aud, 0, entry_node_type="source.naukri")
    assert "keyword" in o and "query" not in o, "naukri's source field is `keyword`"


def test_widen_falls_back_to_max_results_without_keywords():
    overrides, _ = widen_audience({"max_results": 25}, 0)
    assert overrides["max_results"] > 25, "no keyword ladder -> widen breadth via max_results"


# ── metrics honesty: only what the engine can measure is offered ─────────────

def test_only_measurable_metrics_exposed():
    # meetings_booked is intentionally NOT measurable (no campaign calendar signal)
    assert "meetings_booked" not in MEASURABLE_METRICS
    assert set(MEASURABLE_METRICS) == {"contacts", "qualified_leads", "companies", "replies"}
    # the router's Metric Literal must match this set (no goal the engine can't
    # track). Check the Literal line specifically — a comment may legitimately
    # mention meetings_booked to explain why it's excluded.
    router = (BACKEND / "app" / "routers" / "objectives.py").read_text(encoding="utf-8")
    literal_line = next((ln for ln in router.splitlines() if ln.strip().startswith("Metric = Literal")), "")
    assert literal_line, "router must define the Metric Literal"
    assert "meetings_booked" not in literal_line, "router Metric must not offer an unmeasurable metric"
    for m in MEASURABLE_METRICS:
        assert m in literal_line, f"router Metric must offer {m}"


# ── placement: the loop is event-driven, off the safety-critical claim ───────

def test_transition_worker_emits_fact_not_control_loop():
    src = (BACKEND / "app" / "execution" / "transition_worker.py").read_text(encoding="utf-8")
    body = src.split("async def _terminalize_lead", 1)[1]
    # the worker EMITS a fact in the root (no-parent) branch...
    assert "campaign.run.completed" in body, "root completion must emit the fact"
    assert 'elif row.get("workflow_id")' in body, "fact emitted in the no-parent (root) branch"
    # ...and must NOT run the control loop inline (that's the misplacement we fixed)
    assert "evaluate_on_completion" not in body, "no inline control loop in the terminalize claim"
    assert "objective_controller" not in body, "controller must not be called from the hot path"


def test_objective_worker_consumes_the_fact_and_reuses_run_path():
    worker = (BACKEND / "app" / "execution" / "objective_worker.py").read_text(encoding="utf-8")
    assert 'TRIGGER_EVENT = "campaign.run.completed"' in worker, "worker keys off the emitted fact"
    assert "objective_controller.measure" in worker and "objective_controller.decide" in worker
    # re-seed goes through the SHARED run path, not a copied seed-and-fire
    assert "runner.seed_and_run" in worker
    assert "INSERT INTO omni_leads" not in worker, "worker must not hand-roll lead seeding"
    # REGRESSION (live-caught): the worker re-fires the entry node, so it MUST
    # discover the node registry at startup — otherwise get('source.*') raises
    # KeyError and a widen can decide but never re-run. The API process discovers
    # in main.py; a worker process that fires nodes must do it itself.
    assert "noderegistry.discover()" in worker, "worker must discover nodes before firing them"


def test_objective_worker_has_stall_watchdog():
    """The loop is otherwise PURELY event-driven (wakes only on run.completed),
    so a re-seed that never completes (hung source, rate-limit, send gate, crashed
    muscle) would freeze its objective in 'pursuing' forever. A periodic watchdog
    must re-pursue stale 'pursuing' objectives so a silent freeze becomes a real
    decision (re-measure → re-seed or exhaust)."""
    worker = (BACKEND / "app" / "execution" / "objective_worker.py").read_text(encoding="utf-8")
    assert "_watchdog_sweep" in worker and "_watchdog_loop" in worker, "watchdog must exist"
    sweep = worker.split("async def _watchdog_sweep", 1)[1].split("async def _watchdog_loop", 1)[0]
    # it targets STALLED pursuing objectives (status + staleness), not all of them
    assert "status = 'pursuing'" in sweep
    assert "updated_at <" in sweep, "must select on staleness, not sweep every objective"
    # and it recovers by re-pursuing through the SAME pursue() path (re-measure/re-seed)
    assert "pursue(" in sweep
    # the watchdog runs concurrently with the consumer, not instead of it
    run_body = worker.split("async def run(", 1)[1]
    assert "_watchdog_loop" in run_body and "create_task" in run_body, (
        "watchdog must run concurrently with the event consumer"
    )


def test_measure_is_lineage_scoped_not_global():
    src = (BACKEND / "app" / "services" / "objective_controller.py").read_text(encoding="utf-8")
    body = src.split("async def measure", 1)[1].split("async def spend", 1)[0]
    # every measurement query is scoped to THIS workflow's leads (workflow_id=$1)
    assert "workflow_id=$1" in body, "measurement must scope to the campaign's lineage"
    # the old global whole-workspace COUNT(*) is gone
    assert "COUNT(*) AS n FROM omni_contacts" not in src, "no whole-workspace count"


def test_companies_metric_reads_discovery_events_not_dead_field():
    """REGRESSION: the companies metric read custom_fields.company_resolution.
    company_id — an INPUT the worker injects, never a durable output — so it
    measured 0 forever while real runs created companies (caught live 2026-06-21,
    65 real companies reported as 0). It must count company.discovered events in
    the workflow's correlation lineage, mirroring spend()'s proven join."""
    src = (BACKEND / "app" / "services" / "objective_controller.py").read_text(encoding="utf-8")
    body = src.split("async def measure", 1)[1].split("async def spend", 1)[0]
    companies = body.split('metric == "companies"', 1)[1].split("elif", 1)[0]
    # the dead field must NOT be queried as the basis of the companies measure
    # (a comment may still NAME it to document the old bug — only the SQL matters)
    assert "->'company_resolution'" not in companies, (
        "companies must not query custom_fields.company_resolution (a node input, "
        "absent on real leads — it read 0 forever)"
    )
    # it counts discovery EVENTS, lineage-linked by correlation (like spend())
    assert "company.discovered" in companies
    assert "omni_events_archive" in companies and "correlation_id" in companies
    assert "l.workflow_id = $1" in companies, "still lineage-scoped to this workflow"


def test_seed_path_is_shared_single_source():
    run = (BACKEND / "app" / "execution" / "run.py").read_text(encoding="utf-8")
    assert "async def seed_and_run" in run, "the one shared seed-and-fire entry point"
    # the /run endpoint delegates to it (no duplicate seed logic in the router)
    canvas = (BACKEND / "app" / "routers" / "canvas.py").read_text(encoding="utf-8")
    assert "runner.seed_and_run" in canvas, "/run must delegate to the shared path"
