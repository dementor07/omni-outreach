"""Regression — ad-hoc AI Studio jobs actually execute.

THE BUG (project_ai_studio_jobs_void): `POST /ai/jobs` publishes
`ai.<kind>.queued` with no node_id; the dispatcher only routes intents that
resolve to a workflow node, so it DROPPED every ad-hoc job — the "Run scoring"
button queued a row that sat at 'queued' forever. The ai_jobs_worker now owns
the node-less path.

These invariants keep that fix honest and stop the void from silently returning:
  * the worker claims node-less ai.score/compose/classify queued events,
  * it does NOT claim in-workflow AI events (those carry node_id → the muscle),
  * the dispatcher continues to ignore node-less ai intents (no double-run),
  * the model-response parsing is robust to fenced/sloppy JSON.

Pure: no DB, no network.

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.execution import ai_jobs_worker as worker  # noqa: E402
from app.services import ai_jobs  # noqa: E402


# ── the worker claims exactly the ad-hoc jobs, nothing else ──────────────────

def test_worker_claims_node_less_adhoc_jobs():
    for kind in ("score", "compose", "classify"):
        assert worker._is_adhoc_job_event(f"ai.{kind}.queued", {}) is True


def test_worker_ignores_in_workflow_ai_events():
    # In-workflow AI runs carry a node_id (the dispatcher set it) → the muscle
    # owns them; the worker must not double-run.
    assert worker._is_adhoc_job_event("ai.compose.queued", {"node_id": "abc"}) is False
    assert worker._is_adhoc_job_event("ai.score.queued", {"node_id": "n1"}) is False


def test_worker_ignores_non_job_events():
    # completed/failed are facts the worker emits, not triggers it consumes.
    assert worker._is_adhoc_job_event("ai.score.completed", {}) is False
    assert worker._is_adhoc_job_event("ai.score.failed", {}) is False
    # screen/enrich are workflow-only — not ad-hoc Studio job kinds.
    assert worker._is_adhoc_job_event("ai.screen_company.queued", {}) is False
    assert worker._is_adhoc_job_event("ai.enrich.queued", {}) is False
    # unrelated events
    assert worker._is_adhoc_job_event("lead.created", {}) is False
    assert worker._is_adhoc_job_event("campaign.run.completed", {}) is False


# ── the dispatcher must keep ignoring node-less ai intents (no double-run) ────

def test_dispatcher_has_no_route_for_adhoc_ai_kinds():
    """The dispatcher routes by NODE_CHANNEL; ad-hoc score/classify have no node
    type there, so a node-less ai.score/classify intent can't be dispatched as a
    muscle command (which is correct — the worker owns them)."""
    from app.execution import commands

    assert "ai.score" not in commands.NODE_CHANNEL
    assert "ai.classify" not in commands.NODE_CHANNEL


# ── model-response parsing is robust ─────────────────────────────────────────

def test_extract_json_handles_fences_and_prose():
    assert ai_jobs._extract_json('```json\n{"score": 80}\n```') == {"score": 80}
    assert ai_jobs._extract_json('Here you go: {"intent": "positive"} — done') == {"intent": "positive"}
    assert ai_jobs._extract_json("no json here") is None
    assert ai_jobs._extract_json("[1,2,3]") is None  # array, not an object
