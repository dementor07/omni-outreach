"""B1 regression — AI draft-review on the approvals queue.

flow.human_approval can park a lead carrying an AI-composed draft (from an
upstream ai.compose node, read off the lead's custom_fields). The operator
reviews + edits the draft (PATCH /approvals/{id}/draft, event-sourced via
approval.draft_updated) before approving, so a human signs off on AI copy.

Covered:
  - the node surfaces the upstream draft into approval.requested (pure logic)
  - the projector populates `draft` on request + applies draft_updated only to
    pending rows (source-level — the projector is DB-bound)
  - the PATCH endpoint is event-sourced + frozen once resolved
  - migration 032 adds the column

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import uuid

from app.nodes import NodeContext
from app.nodes.flow.human_approval import _lead_draft, execute
from app.routers.approvals import _approval_evidence, _compose_context

BACKEND = Path(__file__).resolve().parents[2] / "backend"
ROUTER = (BACKEND / "app" / "routers" / "approvals.py").read_text(encoding="utf-8")
PROJECTOR = (BACKEND / "app" / "projector" / "main.py").read_text(encoding="utf-8")
MIGRATION = (BACKEND / "alembic" / "versions" / "032_approval_draft.py").read_text(encoding="utf-8")


# ── node: surfaces the upstream AI draft ──────────────────────────────────────

def test_lead_draft_reads_target_variable():
    lead = {"custom_fields": {"ai_draft": "Hi there, following up…"}}
    assert _lead_draft(lead, "ai_draft") == "Hi there, following up…"
    # absent / empty → None (no draft to review)
    assert _lead_draft({"custom_fields": {}}, "ai_draft") is None
    assert _lead_draft({"custom_fields": {"ai_draft": ""}}, "ai_draft") is None


def test_lead_draft_tolerates_json_string_custom_fields():
    lead = {"custom_fields": '{"ai_draft": "stringified"}'}
    assert _lead_draft(lead, "ai_draft") == "stringified"


def test_human_approval_emits_draft_in_request():
    ctx = NodeContext(
        workspace_id="ws",
        workflow_id="wf",
        node_id="n1",
        config={"prompt": "Review this?"},
        lead={"id": "lead-1", "custom_fields": {"ai_draft": "drafted copy"}},
    )
    result = asyncio.run(execute(ctx))
    assert result.park is True
    payload = result.events[0]["payload"]
    assert payload["draft"] == "drafted copy"
    assert result.events[0]["event_type"] == "approval.requested"


# ── projector: populates + edits the draft ────────────────────────────────────

def test_projector_inserts_draft_on_request():
    # the INSERT branch must carry the draft column + its payload value.
    insert = PROJECTOR.split('if et == "approval.requested":', 1)[1][:600]
    assert "INSERT INTO omni_approvals" in insert
    assert "draft" in insert
    assert 'p.get("draft")' in insert


def test_projector_draft_updated_only_touches_pending():
    body = PROJECTOR.split("approval.draft_updated", 1)[1][:500]
    assert "UPDATE omni_approvals" in body
    assert "status = 'pending'" in body, "a resolved approval's draft is frozen"


# ── endpoint: event-sourced PATCH, frozen once resolved ───────────────────────

def test_patch_draft_is_event_sourced_and_frozen():
    body = ROUTER.split("async def update_draft", 1)[1]
    assert 'event_type="approval.draft_updated"' in body, "edit must go through the event log"
    assert "409" in body, "editing a resolved approval must 409 (frozen)"


def test_list_returns_draft():
    body = ROUTER.split("async def list_approvals", 1)[1]
    assert "draft" in body.split("FROM omni_approvals", 1)[0]


def test_approval_queue_is_newest_first_and_campaign_scoped():
    body = ROUTER.split("async def list_approvals", 1)[1]
    assert "campaign_id:" in body
    assert "($1::uuid IS NULL OR l.workflow_id = $1)" in body
    assert "ORDER BY a.created_at DESC, a.id DESC" in body


def test_approval_queue_identifies_prospect_seat_and_evidence():
    body = ROUTER.split("async def list_approvals", 1)[1]
    assert "prospect_linkedin_url" in body
    assert "sa.external_identity AS sending_account_id" in body
    assert "sa.display_name AS sending_account_name" in body
    assert "invite_account_id" in body

    sources = _approval_evidence(
        {
            "hiring_signal": "Hiring two account executives",
            "job_url": "https://example.com/jobs/1",
            "recent_post": "The founder wrote about pipeline quality.",
            "website_summary": "A revenue intelligence platform.",
            "website_url": "https://example.com",
            "profile_headline": "VP Sales",
        },
        "https://linkedin.com/in/prospect",
    )
    assert {source.kind for source in sources} == {"hiring", "post", "website", "profile"}
    assert next(source for source in sources if source.kind == "post").url == "https://linkedin.com/in/prospect"


def test_approval_compose_context_is_campaign_specific_and_fail_closed():
    node_id = uuid.uuid4()
    context = _compose_context(node_id, {
        "instruction": "Message two: follow up on the prospect's hiring signal.",
        "channel": "linkedin",
        "tone": "direct",
        "max_words": 90,
        "model": "claude-sonnet-4-6",
    }, 1)
    assert context is not None
    assert context.node_id == node_id
    assert context.instruction.startswith("Message two")
    assert context.max_words == 90
    assert _compose_context(node_id, {"instruction": "ambiguous"}, 2) is None
    assert _compose_context(node_id, {}, 1) is None


def test_regeneration_resolves_provenance_and_validates_anchored_selections():
    body = ROUTER.split("async def regenerate_approval", 1)[1]
    assert "_COMPOSE_SOURCE_JOIN" in body
    assert "n.node_type = 'ai.compose'" in ROUTER
    assert "source_count" in body
    assert "original_draft[directive.start : directive.end]" in body
    assert "create_job(" in body, "approval rewrites must reuse the existing async AI job seam"


def test_migration_adds_draft_column():
    assert "ADD COLUMN IF NOT EXISTS draft" in MIGRATION
    assert 'down_revision = "031"' in MIGRATION
