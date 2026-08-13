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

import ast
import os
from pathlib import Path

import pytest

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


@pytest.mark.asyncio
async def test_compose_revision_keeps_campaign_draft_annotations_and_facts(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_anthropic(_key, system, user, _max_tokens, *, model):
        captured.update(system=system, user=user, model=model)
        return "Revised draft", {"input_tokens": 10, "output_tokens": 4}

    monkeypatch.setattr(ai_jobs, "_anthropic_text", fake_anthropic)
    result = await ai_jobs.compose_message(
        "secret",
        "Follow up after an accepted LinkedIn invite",
        {"first_name": "Asha", "extra": {"latest_post": "Hiring SDRs"}},
        channel="linkedin",
        tone="warm",
        model="claude-sonnet-4-6",
        original_draft="Hi Asha, your recent hiring push stood out.",
        rewrite_note="Keep the close conversational.",
        rewrite_directives=[{
            "start": 14,
            "end": 32,
            "selected_text": "recent hiring push",
            "instruction": "Name the SDR role from the evidence.",
        }],
    )

    assert result["draft"] == "Revised draft"
    assert captured["model"] == "claude-sonnet-4-6"
    assert "Preserve unannotated wording" in captured["system"]
    assert "Follow up after an accepted LinkedIn invite" in captured["user"]
    assert "Hi Asha, your recent hiring push stood out." in captured["user"]
    assert "Name the SDR role from the evidence." in captured["user"]
    assert "Hiring SDRs" in captured["user"]


def test_every_anthropic_text_consumer_unpacks_usage_tuple():
    """Prevent control-plane callers from passing the helper's (text, usage)
    tuple to JSON/text parsers as though it were a string."""
    backend = Path(__file__).resolve().parents[2] / "backend" / "app"
    bad_calls: list[str] = []
    for path in backend.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Await):
                continue
            call = node.value.value
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            if call.func.id != "_anthropic_text":
                continue
            target = node.targets[0] if len(node.targets) == 1 else None
            if not isinstance(target, (ast.Tuple, ast.List)) or len(target.elts) != 2:
                bad_calls.append(f"{path.relative_to(backend)}:{node.lineno}")
    assert not bad_calls, f"_anthropic_text callers must unpack text and usage: {bad_calls}"
