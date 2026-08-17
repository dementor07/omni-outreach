"""VIEW-GROUNDING-001 — live evidence and pre-apply review for ViewSpecs."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import view_grounding  # noqa: E402

C1 = UUID("a09140c2-6b68-4506-8640-1d23599d1606")
C2 = UUID("29b16f55-840d-4323-b8cc-be37ab5061c9")
CAPTURED = datetime(2026, 8, 13, 14, 30, tzinfo=UTC)
OLD_CAMPAIGN = UUID("0f100000-0000-4000-8000-000000000250")


def _stat(widget_id: str, title: str, *, workflow_id: UUID | None = None, status: str | None = None) -> dict:
    filters: list[dict] = []
    if workflow_id is not None:
        filters.append({"field": "workflow_id", "op": "eq", "value": str(workflow_id)})
    if status is not None:
        filters.append({"field": "status", "op": "eq", "value": status})
    return {
        "id": widget_id,
        "type": "stat",
        "title": title,
        "query": {
            "entity": "send_outcomes",
            "filters": filters,
            "metrics": [{"fn": "count", "alias": widget_id}],
        },
        "width": 1,
    }


def _view(layout: list[dict], *, name: str = "Trial campaigns") -> dict:
    return {
        "name": name,
        "description": "Campaign activity",
        "icon": "megaphone",
        "layout": layout,
    }


class FakeConn:
    """Small asyncpg-shaped projection with the two live campaign identities."""

    def __init__(
        self,
        *,
        fail_widget: str | None = None,
        campaign_total: int = 2,
        extra_campaigns: list[dict] | None = None,
        truncate_breakdowns: bool = False,
    ):
        self.calls: list[tuple[str, tuple]] = []
        self.fail_widget = fail_widget
        self.campaign_total = campaign_total
        self.extra_campaigns = extra_campaigns or []
        self.truncate_breakdowns = truncate_breakdowns
        self.savepoints = 0

    async def execute(self, sql: str):
        self.calls.append((sql, ()))
        return "SET"

    @asynccontextmanager
    async def transaction(self):
        self.savepoints += 1
        yield

    @staticmethod
    def _metric_alias(sql: str) -> str:
        match = re.search(r"COUNT\(\*\) AS ([a-z0-9_]+)", sql)
        return match.group(1) if match else "count"

    async def fetch(self, sql: str, *params):
        self.calls.append((sql, params))
        if self.fail_widget and f"AS {self.fail_widget}" in sql:
            raise RuntimeError("projection unavailable")

        if "FROM omni_workflows" in sql:
            if "COUNT(*) AS total" in sql:
                return [{"total": self.campaign_total}]
            catalog = [
                {"id": C2, "name": "Trial Campaign 2", "status": "active", "updated_at": CAPTURED},
                {"id": C1, "name": "Trial Campaign 1", "status": "active", "updated_at": CAPTURED},
            ]
            if "WHERE id = ANY" in sql:
                requested = {str(value) for value in (params[0] if params else [])}
                return [
                    row for row in [*catalog, *self.extra_campaigns]
                    if str(row["id"]) in requested
                ]
            return catalog

        if "FROM omni_leads" in sql and "GROUP BY workflow_id, status" in sql:
            rows = [
                {"workflow_id": C1, "status": "completed", "count": 9, "source_max_at": CAPTURED},
                {"workflow_id": C1, "status": "errored", "count": 1, "source_max_at": CAPTURED},
                {"workflow_id": C2, "status": "waiting", "count": 73, "source_max_at": CAPTURED},
                {"workflow_id": C2, "status": "completed", "count": 6, "source_max_at": CAPTURED},
            ]
            return [rows[0] for _ in range(500)] if self.truncate_breakdowns else rows

        if "FROM omni_send_outcomes" in sql and "GROUP BY workflow_id, status" in sql:
            rows = [
                {"workflow_id": C1, "status": "sent", "count": 26, "source_max_at": CAPTURED},
                {"workflow_id": C2, "status": "sent", "count": 258, "source_max_at": CAPTURED},
                {"workflow_id": C2, "status": "failed", "count": 1, "source_max_at": CAPTURED},
                {"workflow_id": C2, "status": "skipped", "count": 4, "source_max_at": CAPTURED},
            ]
            return [rows[0] for _ in range(500)] if self.truncate_breakdowns else rows

        if "MAX(occurred_at) AS source_max_at" in sql:
            return [{"source_max_at": CAPTURED}]

        if "FROM omni_send_outcomes" in sql:
            alias = self._metric_alias(sql)
            values = {str(value) for value in params}
            if str(C1) in values:
                count = 26
            elif str(C2) in values:
                count = 258 if "sent" in values else 263
            elif "delivered" in values:
                count = 0
            else:
                count = 315
            return [{alias: count}]

        if "FROM omni_contacts" in sql and "MAX(updated_at)" in sql:
            return [{"source_max_at": CAPTURED}]
        if "FROM omni_contacts" in sql:
            return []
        raise AssertionError(f"unexpected query: {sql}")


def _install_conn(monkeypatch, conn: FakeConn) -> None:
    @asynccontextmanager
    async def fake_acquire():
        yield conn

    monkeypatch.setattr(view_grounding, "acquire", fake_acquire)


def test_campaign_reference_matching_uses_token_boundaries():
    campaigns = {
        "items": [
            {"id": "2", "name": "Campaign 2"},
            {"id": "20", "name": "Campaign 20"},
            {"id": "ai", "name": "AI"},
        ],
    }

    matches = view_grounding._campaign_references("Campaign 20 sends", campaigns)

    assert [item["id"] for item in matches] == ["20"]
    assert view_grounding._campaign_references("Campaign activity", campaigns) == []


@pytest.mark.asyncio
async def test_grounding_captures_widget_values_campaign_ids_breakdowns_and_freshness(monkeypatch):
    conn = FakeConn()
    _install_conn(monkeypatch, conn)
    current = _view([_stat("campaign_1_sends", "Campaign 1 sends")])

    grounded = await view_grounding.capture_view_grounding(current)

    assert grounded["version"] == "view-grounding.v1"
    snapshot = grounded["widget_results"][0]
    assert snapshot["rows"] == [{"campaign_1_sends": 315}]
    assert snapshot["source_max_at"] == CAPTURED.isoformat()
    assert snapshot["returned_rows"] == snapshot["preview_rows"] == 1
    assert snapshot["truncated"] is False and snapshot["error"] is None
    assert snapshot["content_truncated"] is False

    campaigns = {item["id"]: item for item in grounded["campaigns"]["items"]}
    assert campaigns[str(C1)]["name"] == "Trial Campaign 1"
    assert campaigns[str(C1)]["send_outcome_status_counts"] == {"sent": 26}
    assert campaigns[str(C2)]["lead_status_counts"] == {"waiting": 73, "completed": 6}
    assert grounded["campaigns"]["observed_values"]["send_outcomes.status"] == [
        "failed", "sent", "skipped"
    ]
    # The durable broker payload can json.dumps this directly; no UUID/datetime leaks.
    json.dumps(grounded)
    assert all("workspace_id" not in sql for sql, _ in conn.calls)
    assert conn.calls[0][0] == "SET LOCAL statement_timeout = '5000ms'"


@pytest.mark.asyncio
async def test_candidate_review_executes_scoped_queries_and_returns_structured_diff(monkeypatch):
    conn = FakeConn()
    _install_conn(monkeypatch, conn)
    current = _view([
        _stat("campaign_1_sends", "Campaign 1 sends"),
        _stat("campaign_2_sends", "Campaign 2 sends"),
    ])
    candidate = _view([
        _stat("campaign_1_sends", "Campaign 1 sends", workflow_id=C1, status="sent"),
        _stat("campaign_2_sends", "Campaign 2 sends", workflow_id=C2, status="sent"),
    ])

    review = await view_grounding.review_candidate_view(current, candidate)

    assert review["ready_to_apply"] is True
    assert review["error_count"] == 0
    assert review["diff"]["summary"] == {
        "view_fields_changed": 0,
        "widgets_added": 0,
        "widgets_removed": 0,
        "widgets_changed": 2,
    }
    assert {item["widget_id"] for item in review["diff"]["widgets"]["changed"]} == {
        "campaign_1_sends", "campaign_2_sends"
    }
    snapshots = {item["widget_id"]: item for item in review["verification"]["widget_results"]}
    assert snapshots["campaign_1_sends"]["rows"] == [{"campaign_1_sends": 26}]
    assert snapshots["campaign_2_sends"]["rows"] == [{"campaign_2_sends": 258}]
    assert not {"campaign_reference_unfiltered", "duplicate_campaign_stat_result"} & {
        item["code"] for item in review["warnings"]
    }


@pytest.mark.asyncio
async def test_campaign_title_scope_rejects_extra_known_workflow_ids(monkeypatch):
    _install_conn(monkeypatch, FakeConn())
    widget = _stat("campaign_1_sends", "Trial Campaign 1 sends", status="sent")
    widget["query"]["filters"].insert(0, {
        "field": "workflow_id",
        "op": "in",
        "value": [str(C1), str(C2)],
    })
    candidate = _view([widget])

    review = await view_grounding.review_candidate_view(candidate, candidate)

    issue = next(
        item for item in review["warnings"]
        if item["code"] == "campaign_identity_mismatch"
    )
    assert review["ready_to_apply"] is False
    assert issue["required_workflow_ids"] == [str(C1)]
    assert issue["unexpected_workflow_ids"] == [str(C2)]


@pytest.mark.asyncio
async def test_annotation_history_cannot_contaminate_visible_candidate_semantics(monkeypatch):
    _install_conn(monkeypatch, FakeConn())
    current = _view([_stat(
        "campaign_sends",
        "Trial Campaign 1 deliveries",
        workflow_id=C1,
        status="sent",
    )])
    candidate = _view([_stat(
        "campaign_sends",
        "Trial Campaign 2 sends",
        workflow_id=C2,
        status="sent",
    )])

    review = await view_grounding.review_candidate_view(
        current,
        candidate,
        annotations=[{
            "widget_id": "campaign_sends",
            "note": "Change Trial Campaign 1 deliveries to Trial Campaign 2 sent messages",
        }],
    )

    assert review["ready_to_apply"] is True
    assert not {
        "campaign_identity_mismatch",
        "unsupported_delivery_claim",
    } & {item["code"] for item in review["warnings"]}


@pytest.mark.asyncio
async def test_annotation_with_old_and_new_status_does_not_disable_visible_status_gate(monkeypatch):
    _install_conn(monkeypatch, FakeConn())
    candidate = _view([_stat(
        "failed_sends",
        "Failed sends",
        workflow_id=C1,
        status="failed",
    )])

    review = await view_grounding.review_candidate_view(
        candidate,
        candidate,
        annotations=[{
            "widget_id": "failed_sends",
            "note": "Change from sent to failed",
        }],
    )

    assert review["ready_to_apply"] is True
    assert "send_metric_status_mismatch" not in {
        item["code"] for item in review["warnings"]
    }


@pytest.mark.asyncio
async def test_broker_review_contract_uses_frozen_before_rows_and_live_after_rows(monkeypatch):
    conn = FakeConn()
    _install_conn(monkeypatch, conn)
    current = _view([_stat("campaign_1_sends", "Campaign 1 sends")])
    candidate = _view([_stat("campaign_1_sends", "Campaign 1 sends", workflow_id=C1, status="sent")])
    frozen = await view_grounding.capture_view_grounding(current)

    review = await view_grounding.review_view_candidate(
        {
            "current_view": current,
            "widget_annotations": [{
                "widget_id": "campaign_1_sends",
                "note": "Use Trial Campaign 1 only",
            }],
            "data_context": frozen,
        },
        candidate,
    )

    assert review["all_queries_valid"] is True
    assert review["ready_to_apply"] is True
    assert review["blocking_issues"] == []
    assert len(review["changed_widgets"]) == 1
    change = review["changed_widgets"][0]
    assert change == {
        "widget_id": "campaign_1_sends",
        "before_title": "Campaign 1 sends",
        "after_title": "Campaign 1 sends",
        "before_rows": [{"campaign_1_sends": 315}],
        "after_rows": [{"campaign_1_sends": 26}],
        "query_changed": True,
    }


@pytest.mark.asyncio
async def test_review_blocks_unscoped_campaign_stats_that_claim_sent_counts(monkeypatch):
    _install_conn(monkeypatch, FakeConn())
    candidate = _view([
        _stat("campaign_1_sends", "Campaign 1 sends"),
        _stat("campaign_2_sends", "Campaign 2 sends"),
    ])

    review = await view_grounding.review_candidate_view(candidate, candidate)
    codes = {item["code"] for item in review["warnings"]}

    assert review["ready_to_apply"] is False  # a named campaign without identity is unsafe
    assert "campaign_reference_unfiltered" in codes
    assert "duplicate_campaign_stat_result" in codes
    assert "send_metric_status_mismatch" in codes

    broker_review = await view_grounding.review_view_candidate(
        {"current_view": candidate, "grounding": review["verification"]},
        candidate,
    )
    assert broker_review["all_queries_valid"] is True
    assert broker_review["ready_to_apply"] is False
    assert {item["code"] for item in broker_review["blocking_issues"]} >= {
        "campaign_reference_unfiltered"
    }


def test_invalid_projection_enum_is_rejected_before_live_execution():
    with pytest.raises(ValueError, match="not valid for send_outcomes.status"):
        view_grounding.QuerySpec(
            entity="send_outcomes",
            filters=[{"field": "status", "op": "eq", "value": "delivered"}],
            metrics=[{"fn": "count", "alias": "delivered"}],
        )

    with pytest.raises(ValueError, match="not valid for leads.status"):
        view_grounding.QuerySpec(
            entity="leads",
            filters=[{"field": "status", "op": "eq", "value": "delivered"}],
            metrics=[{"fn": "count", "alias": "delivered_leads"}],
        )


@pytest.mark.parametrize("op", ["contains", "gt", "gte", "lt", "lte", "is_null", "not_null"])
def test_enum_fields_reject_nonsensical_operators(op):
    item = {"field": "status", "op": op}
    if op not in {"is_null", "not_null"}:
        item["value"] = "delivered"

    with pytest.raises(ValueError, match="is not valid for enum field send_outcomes.status"):
        view_grounding.QuerySpec(
            entity="send_outcomes",
            filters=[item],
            metrics=[{"fn": "count", "alias": "count"}],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "skipped", "queued"])
async def test_explicit_send_outcome_labels_require_their_own_status(
    monkeypatch, status,
):
    _install_conn(monkeypatch, FakeConn())
    candidate = _view([
        _stat(
            f"{status}_sends",
            f"{status.title()} sends",
            workflow_id=C1,
            status=status,
        ),
    ])

    review = await view_grounding.review_candidate_view(candidate, candidate)

    assert review["ready_to_apply"] is True
    assert "send_metric_status_mismatch" not in {
        item["code"] for item in review["warnings"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["Send outcomes", "Attempted sends"])
async def test_explicit_send_attempt_labels_can_include_multiple_statuses(monkeypatch, title):
    _install_conn(monkeypatch, FakeConn())
    candidate = _view([
        _stat("send_outcomes", title, workflow_id=C2),
    ])

    review = await view_grounding.review_candidate_view(candidate, candidate)

    assert review["ready_to_apply"] is True
    assert "send_metric_status_mismatch" not in {
        item["code"] for item in review["warnings"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["All sends", "Total sends"])
async def test_all_or_total_sends_still_require_sent_status(monkeypatch, title):
    _install_conn(monkeypatch, FakeConn())
    candidate = _view([_stat("sends", title, workflow_id=C2)])

    review = await view_grounding.review_candidate_view(candidate, candidate)

    assert review["ready_to_apply"] is False
    assert "send_metric_status_mismatch" in {
        item["code"] for item in review["warnings"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["Campaign 1 Messages", "Campaign 2 Messages"])
async def test_campaign_messages_on_send_outcomes_require_sent_status(monkeypatch, title):
    _install_conn(monkeypatch, FakeConn())
    workflow_id = C1 if "1" in title else C2
    candidate = _view([_stat("messages", title, workflow_id=workflow_id)])

    review = await view_grounding.review_candidate_view(candidate, candidate)

    assert review["ready_to_apply"] is False
    assert "send_metric_status_mismatch" in {
        item["code"] for item in review["warnings"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("campaign_total", [2, 201])
async def test_every_workflow_filter_must_match_authoritative_workspace_campaign(
    monkeypatch, campaign_total,
):
    _install_conn(monkeypatch, FakeConn(campaign_total=campaign_total))
    unknown = UUID("b8b2ee7b-7b3a-4042-9795-71843beec5da")
    candidate = _view([
        _stat("campaign_99_sends", "Campaign 99 sends", workflow_id=unknown, status="sent"),
    ])

    review = await view_grounding.review_candidate_view(candidate, candidate)

    assert review["ready_to_apply"] is False
    assert "campaign_scope_unknown" in {item["code"] for item in review["warnings"]}


@pytest.mark.asyncio
async def test_targeted_lookup_resolves_scope_beyond_truncated_campaign_catalog(monkeypatch):
    old = {
        "id": OLD_CAMPAIGN,
        "name": "Legacy Campaign 250",
        "status": "archived",
        "updated_at": CAPTURED,
    }
    _install_conn(monkeypatch, FakeConn(campaign_total=250, extra_campaigns=[old]))
    candidate = _view([_stat(
        "legacy_sends",
        "Legacy Campaign 250 sends",
        workflow_id=OLD_CAMPAIGN,
        status="sent",
    )])

    review = await view_grounding.review_candidate_view(candidate, candidate)

    context = review["verification"]["campaigns"]
    assert review["ready_to_apply"] is True
    assert context["returned"] == 2
    assert context["truncated"] is True
    assert [item["id"] for item in context["scope_items"]] == [str(OLD_CAMPAIGN)]
    assert context["scope_verification"] == {
        "requested_ids": [str(OLD_CAMPAIGN)],
        "resolved_ids": [str(OLD_CAMPAIGN)],
        "missing_ids": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["Delivered messages", "Email deliveries"])
async def test_send_outcomes_cannot_be_mislabelled_as_delivered(monkeypatch, title):
    _install_conn(monkeypatch, FakeConn())
    candidate = _view([_stat(
        "delivered",
        title,
        workflow_id=C1,
        status="sent",
    )])
    review = await view_grounding.review_candidate_view(candidate, candidate)
    assert review["ready_to_apply"] is False
    assert "unsupported_delivery_claim" in {
        item["code"] for item in review["warnings"]
    }


@pytest.mark.asyncio
async def test_candidate_runtime_failure_is_structured_and_blocks_apply_readiness(monkeypatch):
    conn = FakeConn(fail_widget="broken_metric")
    _install_conn(monkeypatch, conn)
    current = _view([_stat("safe_metric", "Safe")])
    candidate = _view([_stat("broken_metric", "Broken")])

    review = await view_grounding.review_candidate_view(current, candidate)

    assert review["ready_to_apply"] is False
    assert review["error_count"] == 1
    snapshot = review["verification"]["widget_results"][0]
    assert snapshot["error"] == {
        "code": "query_execution_failed",
        "message": "projection unavailable",
    }
    assert "candidate_query_failed" in {item["code"] for item in review["warnings"]}
    assert conn.savepoints >= 1  # the caught failure is isolated from later evidence reads


@pytest.mark.asyncio
async def test_empty_rows_are_definitive_evidence_not_a_query_failure(monkeypatch):
    _install_conn(monkeypatch, FakeConn())
    empty_table = {
        "id": "recent_contacts",
        "type": "table",
        "title": "Recent contacts",
        "query": {"entity": "contacts", "select": ["first_name", "company"]},
        "width": 2,
    }

    review = await view_grounding.review_candidate_view(_view([empty_table]), _view([empty_table]))
    snapshot = review["verification"]["widget_results"][0]

    assert snapshot["rows"] == []
    assert snapshot["returned_rows"] == 0
    assert snapshot["error"] is None
    assert review["ready_to_apply"] is True


@pytest.mark.asyncio
async def test_breakdown_group_caps_are_explicit_in_grounding_evidence(monkeypatch):
    _install_conn(monkeypatch, FakeConn(truncate_breakdowns=True))

    grounded = await view_grounding.capture_view_grounding(
        _view([_stat("campaign_1_sends", "Campaign 1 sends")]),
    )

    context = grounded["campaigns"]
    assert context["breakdowns"] == {
        "leads": {
            "group_limit": 500,
            "groups_returned": 500,
            "truncated": True,
        },
        "send_outcomes": {
            "group_limit": 500,
            "groups_returned": 500,
            "truncated": True,
        },
    }
    assert all(
        item["lead_breakdown_complete"] is False
        and item["send_outcome_breakdown_complete"] is False
        for item in context["items"]
    )


@pytest.mark.asyncio
async def test_grounding_has_a_whole_review_deadline(monkeypatch):
    _install_conn(monkeypatch, FakeConn())
    monkeypatch.setattr(view_grounding, "GROUNDING_BUDGET_SECONDS", 0.001)

    async def slow_capture(*_args, **_kwargs):
        await asyncio.sleep(0.02)
        return {}

    monkeypatch.setattr(view_grounding, "_capture_with_conn", slow_capture)

    with pytest.raises(view_grounding.ViewGroundingTimeoutError, match="read budget"):
        await view_grounding.capture_view_grounding(
            _view([_stat("campaign_1_sends", "Campaign 1 sends")]),
        )


def test_verbose_cells_are_bounded_for_durable_agent_context():
    bounded, truncated = view_grounding._bounded_json({"body": "x" * 700})
    assert truncated is True
    assert len(bounded["body"]) == view_grounding.MAX_CELL_CHARS + 1
    assert bounded["body"].endswith("…")


# ── false positives found by actually running a harness job (2026-08-14) ───────
#
# Both of these BLOCKED correct work, which is worse than a missed warning: the
# gate refuses Apply, so an unsatisfiable rule stops the operator entirely.


def test_campaign_alias_ignores_digits_that_are_not_a_campaign_number():
    """"e2e" and "(v2)" are not campaign numbers.

    Harvesting every digit in a campaign NAME minted a "campaign 2" alias for
    "TEST e2e CLEAN — Johnsy→Navin" and for "…leaders <100 (v2)", so a widget
    correctly titled "Campaign 2 — sent per day" was reported as visibly
    referring to four unrelated campaigns. Its workflow_id scope could then
    never match the demanded set, making the gate impossible to satisfy.
    """
    from app.services.view_grounding import _campaign_references

    campaigns = {
        "items": [
            {"id": "c2-id", "name": "Trial Campaign 2"},
            {"id": "e2e-id", "name": "TEST e2e CLEAN — Johnsy→Navin"},
            {"id": "v2-id", "name": "LinkedIn Jobs -> India mktg leaders <100 (v2)"},
        ],
        "scope_items": [],
    }
    matched = {c["id"] for c in _campaign_references("Campaign 2 — sent per day", campaigns)}
    assert matched == {"c2-id"}


def test_full_campaign_name_still_matches():
    from app.services.view_grounding import _campaign_references

    campaigns = {"items": [{"id": "c1-id", "name": "Trial Campaign 1"}], "scope_items": []}
    assert [c["id"] for c in _campaign_references("Trial Campaign 1 health", campaigns)] == ["c1-id"]


def test_rows_table_does_not_make_a_sent_count_claim():
    """A table listing individual outcomes with a status column states no total.

    Demanding status='sent' on it blocked the honest "Recent Send Activity"
    widget — and satisfying the demand would have hidden exactly the failed and
    skipped rows an operator needs.
    """
    from app.services.view_grounding import _review_warnings

    candidate = {
        "layout": [{
            "id": "recent_activity",
            "type": "table",
            "title": "Recent Send Activity",
            "query": {
                "entity": "send_outcomes",
                "filters": [],
                "select": ["occurred_at", "channel", "status"],
                "group_by": [],
                "metrics": [],
            },
        }],
    }
    verification = {
        "widget_results": [{"widget_id": "recent_activity", "rows": [], "columns": [], "error": None}],
        "campaigns": {"items": [], "scope_items": [], "total": 2, "observed_values": {}},
    }
    codes = {w["code"] for w in _review_warnings({}, candidate, verification, [])}
    assert "send_metric_status_mismatch" not in codes


def test_aggregate_sent_claim_is_still_enforced():
    """The real guard must survive the fix: a COUNT labelled 'sent' still needs
    status='sent', or a tile can quietly count failures as successes."""
    from app.services.view_grounding import _review_warnings

    candidate = {
        "layout": [{
            "id": "sent_total",
            "type": "stat",
            "title": "Messages sent",
            "query": {
                "entity": "send_outcomes",
                "filters": [],
                "select": [],
                "group_by": [],
                "metrics": [{"fn": "count", "field": "id", "alias": "n"}],
            },
        }],
    }
    verification = {
        "widget_results": [{"widget_id": "sent_total", "rows": [], "columns": [], "error": None}],
        "campaigns": {"items": [], "scope_items": [], "total": 2, "observed_values": {}},
    }
    codes = {w["code"] for w in _review_warnings({}, candidate, verification, [])}
    assert "send_metric_status_mismatch" in codes
