"""Regression contracts for truthful projection counts and responsive tables."""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.routers.ai_studio import _score_out  # noqa: E402
from app.routers.projections import _contact_filters, _lead_filters  # noqa: E402


def test_contact_list_and_summary_share_identical_filter_sql():
    workflow_id = uuid.uuid4()
    where, args = _contact_filters(" Ada ", "workflow", workflow_id, True)

    assert "c.first_name ILIKE $1" in where
    assert "c.source = $2" in where
    assert "c.email IS NOT NULL" in where
    assert "l.workflow_id = $3" in where
    assert args == ["%Ada%", "workflow", workflow_id]


def test_operational_source_batches_are_not_prospects_by_default():
    where, args = _lead_filters(None, False)
    assert "jsonb_typeof(l.custom_fields->'companies') = 'array'" in where
    assert where.startswith("WHERE NOT")
    assert args == []

    unfiltered_where, unfiltered_args = _lead_filters(None, True)
    assert unfiltered_where == ""
    assert unfiltered_args == []


def test_score_projection_carries_a_human_identity():
    score = _score_out(
        {
            "lead_id": uuid.uuid4(),
            "identity_lead_id": uuid.uuid4(),
            "contact_id": uuid.uuid4(),
            "score": 91,
            "tier": "hot",
            "reasons": ["Strong fit"],
            "model": "test-model",
            "scored_at": datetime.now(UTC),
            "custom_fields": {},
            "c_first_name": "Ada",
            "c_last_name": "Lovelace",
            "c_email": "ada@example.com",
        }
    )
    assert score.identity == "Ada Lovelace"


def test_frontend_uses_exact_summaries_and_contains_wide_tables():
    overview = (ROOT / "frontend/src/pages/Overview.tsx").read_text(encoding="utf-8")
    contacts = (ROOT / "frontend/src/pages/Contacts.tsx").read_text(encoding="utf-8")
    leads = (ROOT / "frontend/src/pages/Leads.tsx").read_text(encoding="utf-8")
    card = (ROOT / "frontend/src/components/Card.tsx").read_text(encoding="utf-8")

    assert "projections.contactSummary()" in overview
    assert "projections.leadSummary()" in overview
    assert "ai.scoreSummary" in overview
    assert "projections.contactSummary(summaryFilters)" in contacts
    assert "projections.leadSummary" in leads
    assert 'className="overflow-hidden"' in contacts
    assert 'className="overflow-hidden"' in leads
    assert "'min-w-0 rounded-2xl border'" in card


def test_current_score_lists_hide_orphaned_history_by_default():
    source = (ROOT / "backend/app/routers/ai_studio.py").read_text(encoding="utf-8")
    assert "include_historical: bool = Query(" in source
    assert 'clauses.append("l.id IS NOT NULL")' in source
    assert "COUNT(*) FILTER (WHERE l.id IS NULL) AS historical" in source
