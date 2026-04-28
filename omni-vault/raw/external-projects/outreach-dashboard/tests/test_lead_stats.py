"""
TDD tests for get_lead_stats() query function and GET /api/leads/stats endpoint.

RED phase: these tests must all fail until the implementation is written.

Mocking strategy:
- queries.fetch_all / queries.fetch_one are patched at the queries module level
  (where they are *used*, not where they are *defined* in db.py).
- The FastAPI endpoint test patches queries.get_lead_stats directly so the
  query-level tests and endpoint-level tests remain independent.
"""

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — add dashboard root so imports work without installation
# ---------------------------------------------------------------------------
DASHBOARD_ROOT = str(Path(__file__).parent.parent)
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

# Stub out heavy external dependencies before importing app or queries so that
# tests do not require a live database, Redis, or any configured env vars.
# Each stub replaces just enough of the module surface to allow imports to
# succeed.

_DB_STUB = MagicMock()
sys.modules.setdefault("db", _DB_STUB)
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("itsdangerous", MagicMock())
sys.modules.setdefault("approval_gate", MagicMock())
sys.modules.setdefault("approval_service", MagicMock())
sys.modules.setdefault("claude_terminal_service", MagicMock())
sys.modules.setdefault("drive_config_service", MagicMock())
sys.modules.setdefault("repair_agent", MagicMock())
sys.modules.setdefault("scenarios", MagicMock())
sys.modules.setdefault("sheets_input_service", MagicMock())
sys.modules.setdefault("terminal_service", MagicMock())
sys.modules.setdefault("audit_log", MagicMock())
sys.modules.setdefault("campaign_validate", MagicMock())
sys.modules.setdefault("command_policy", MagicMock())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dict_row(**kwargs):
    """Simulate a psycopg2 RealDictRow that supports dict() conversion."""
    m = MagicMock()
    m.__iter__ = lambda s: iter(kwargs.items())
    m.keys = lambda: kwargs.keys()
    m.__getitem__ = lambda s, k: kwargs[k]
    m.items = lambda: kwargs.items()
    # Allow dict(row) via mapping protocol
    m._asdict = lambda: kwargs
    return kwargs  # plain dict is fine — queries return list[dict] after dict()


# Canonical fixtures ---------------------------------------------------------

STATS_ROW = {
    "total_ingested": 150,
    "invites_sent": 100,
    "accepted": 60,
    "pending_acceptance": 40,
    "stopped": 5,
}

QUEUE_BREAKDOWN_ROWS = [
    {"task_type": "first_message", "status": "queued", "cnt": 12},
    {"task_type": "followup_1", "status": "sent", "cnt": 30},
    {"task_type": "invite", "status": "failed", "cnt": 3},
]

FAILURE_REASON_ROWS = [
    {"failure_reason": "connection_timeout", "cnt": 2},
    {"failure_reason": "rate_limited", "cnt": 1},
]


# ===========================================================================
# Unit tests — queries.get_lead_stats()
# ===========================================================================

class TestGetLeadStatsNoFilter:
    """get_lead_stats() with no campaign_id must issue SQL without a WHERE clause."""

    def test_returns_stats_key(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW) as mock_fo, \
             patch.object(queries, "fetch_all", return_value=QUEUE_BREAKDOWN_ROWS + FAILURE_REASON_ROWS):
            result = queries.get_lead_stats()
        assert "stats" in result

    def test_returns_queue_breakdown_key(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=QUEUE_BREAKDOWN_ROWS):
            result = queries.get_lead_stats()
        assert "queue_breakdown" in result

    def test_returns_failure_reasons_key(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=FAILURE_REASON_ROWS):
            result = queries.get_lead_stats()
        assert "failure_reasons" in result

    def test_stats_contains_all_required_fields(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=[]):
            result = queries.get_lead_stats()
        stats = result["stats"]
        required = {"total_ingested", "invites_sent", "accepted", "pending_acceptance", "stopped"}
        assert required.issubset(set(stats.keys())), (
            f"Missing keys: {required - set(stats.keys())}"
        )

    def test_sql_has_no_where_clause_when_no_campaign_id(self):
        """Verify the SQL passed to fetch_one does not contain WHERE campaign_id."""
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW) as mock_fo, \
             patch.object(queries, "fetch_all", return_value=[]):
            queries.get_lead_stats()
        # All calls to fetch_one must not include a campaign_id filter
        for c in mock_fo.call_args_list:
            sql = c.args[0] if c.args else ""
            assert "campaign_id" not in sql.lower() or "= %s" not in sql, (
                "fetch_one SQL should not filter by campaign_id when none provided"
            )

    def test_no_params_passed_to_fetch_one_when_no_campaign_id(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW) as mock_fo, \
             patch.object(queries, "fetch_all", return_value=[]):
            queries.get_lead_stats()
        for c in mock_fo.call_args_list:
            params = c.args[1] if len(c.args) > 1 else c.kwargs.get("params")
            assert params in (None, ()), (
                f"Expected no params when no campaign_id, got {params!r}"
            )

    def test_stats_values_match_mock_data(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=[]):
            result = queries.get_lead_stats()
        assert result["stats"]["total_ingested"] == 150
        assert result["stats"]["invites_sent"] == 100
        assert result["stats"]["accepted"] == 60
        assert result["stats"]["pending_acceptance"] == 40
        assert result["stats"]["stopped"] == 5


class TestGetLeadStatsWithCampaignFilter:
    """get_lead_stats(campaign_id=...) must inject a WHERE campaign_id = %s clause."""

    def test_sql_contains_where_campaign_id(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW) as mock_fo, \
             patch.object(queries, "fetch_all", return_value=[]) as mock_fa:
            queries.get_lead_stats(campaign_id="CAMPAIGN_3")

        # At least one call among fetch_one / fetch_all must filter by campaign_id
        all_calls = mock_fo.call_args_list + mock_fa.call_args_list
        found_filter = False
        for c in all_calls:
            sql = c.args[0] if c.args else ""
            params = c.args[1] if len(c.args) > 1 else c.kwargs.get("params")
            if "campaign_id" in sql.lower() and params and "CAMPAIGN_3" in str(params):
                found_filter = True
                break
        assert found_filter, (
            "Expected at least one DB call to filter by campaign_id = 'CAMPAIGN_3'"
        )

    def test_campaign_id_passed_as_param_not_interpolated(self):
        """Campaign ID must be a bind parameter, never f-string interpolated, to prevent SQL injection."""
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW) as mock_fo, \
             patch.object(queries, "fetch_all", return_value=[]) as mock_fa:
            queries.get_lead_stats(campaign_id="CAMPAIGN_3")

        all_calls = mock_fo.call_args_list + mock_fa.call_args_list
        for c in all_calls:
            sql = c.args[0] if c.args else ""
            # The literal value must not appear inside the SQL string itself
            assert "CAMPAIGN_3" not in sql, (
                "campaign_id value must not be interpolated directly into SQL — use parameterised query"
            )

    def test_returns_correct_shape_with_campaign_filter(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=QUEUE_BREAKDOWN_ROWS):
            result = queries.get_lead_stats(campaign_id="CAMPAIGN_3")
        assert set(result.keys()) == {"stats", "queue_breakdown", "failure_reasons"}

    def test_stats_values_correct_with_campaign_filter(self):
        import queries
        campaign_stats = {**STATS_ROW, "total_ingested": 50, "accepted": 20}
        with patch.object(queries, "fetch_one", return_value=campaign_stats), \
             patch.object(queries, "fetch_all", return_value=[]):
            result = queries.get_lead_stats(campaign_id="CAMPAIGN_3")
        assert result["stats"]["total_ingested"] == 50
        assert result["stats"]["accepted"] == 20


class TestGetLeadStatsReturnShape:
    """Validate the exact structure of the returned dict under various data conditions."""

    def test_queue_breakdown_is_list(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=QUEUE_BREAKDOWN_ROWS):
            result = queries.get_lead_stats()
        assert isinstance(result["queue_breakdown"], list)

    def test_failure_reasons_is_list(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=FAILURE_REASON_ROWS):
            result = queries.get_lead_stats()
        assert isinstance(result["failure_reasons"], list)

    def test_queue_breakdown_items_have_task_type_status_cnt(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=QUEUE_BREAKDOWN_ROWS):
            result = queries.get_lead_stats()
        for item in result["queue_breakdown"]:
            assert "task_type" in item
            assert "status" in item
            assert "cnt" in item

    def test_failure_reasons_items_have_failure_reason_and_cnt(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=FAILURE_REASON_ROWS):
            result = queries.get_lead_stats()
        for item in result["failure_reasons"]:
            assert "failure_reason" in item
            assert "cnt" in item

    def test_empty_queue_breakdown_when_no_tasks(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=[]):
            result = queries.get_lead_stats()
        # queue_breakdown and failure_reasons may both be empty lists — that is valid
        assert isinstance(result["queue_breakdown"], list)
        assert isinstance(result["failure_reasons"], list)

    def test_stats_counts_are_non_negative_integers(self):
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=[]):
            result = queries.get_lead_stats()
        for key, val in result["stats"].items():
            assert isinstance(val, int), f"stats[{key!r}] should be int, got {type(val)}"
            assert val >= 0, f"stats[{key!r}] should be >= 0, got {val}"

    def test_fetch_one_called_for_stats_aggregation(self):
        """get_lead_stats must call fetch_one at least once (for the stats aggregate)."""
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW) as mock_fo, \
             patch.object(queries, "fetch_all", return_value=[]):
            queries.get_lead_stats()
        assert mock_fo.called, "Expected fetch_one to be called for stats aggregation"

    def test_fetch_all_called_for_breakdown_queries(self):
        """get_lead_stats must call fetch_all at least twice (queue breakdown + failure reasons)."""
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW), \
             patch.object(queries, "fetch_all", return_value=[]) as mock_fa:
            queries.get_lead_stats()
        assert mock_fa.call_count >= 2, (
            f"Expected fetch_all called at least 2 times, called {mock_fa.call_count}"
        )


class TestGetLeadStatsEdgeCases:
    """Edge cases: None row from fetch_one, empty lists, zero counts."""

    def test_handles_none_from_fetch_one_gracefully(self):
        """If fetch_one returns None (no rows), function must not raise."""
        import queries
        with patch.object(queries, "fetch_one", return_value=None), \
             patch.object(queries, "fetch_all", return_value=[]):
            result = queries.get_lead_stats()
        assert "stats" in result

    def test_handles_all_zero_counts(self):
        import queries
        zero_stats = {k: 0 for k in STATS_ROW}
        with patch.object(queries, "fetch_one", return_value=zero_stats), \
             patch.object(queries, "fetch_all", return_value=[]):
            result = queries.get_lead_stats()
        for val in result["stats"].values():
            assert val == 0

    def test_handles_empty_string_campaign_id_as_no_filter(self):
        """Passing campaign_id='' should behave identically to campaign_id=None (no WHERE)."""
        import queries
        with patch.object(queries, "fetch_one", return_value=STATS_ROW) as mock_fo, \
             patch.object(queries, "fetch_all", return_value=[]) as mock_fa:
            queries.get_lead_stats(campaign_id="")
        all_calls = mock_fo.call_args_list + mock_fa.call_args_list
        for c in all_calls:
            params = c.args[1] if len(c.args) > 1 else c.kwargs.get("params")
            assert params in (None, ()), (
                "Empty string campaign_id should not produce a bind parameter"
            )

    def test_large_counts_returned_correctly(self):
        import queries
        large_stats = {
            "total_ingested": 100_000,
            "invites_sent": 80_000,
            "accepted": 50_000,
            "pending_acceptance": 30_000,
            "stopped": 500,
        }
        with patch.object(queries, "fetch_one", return_value=large_stats), \
             patch.object(queries, "fetch_all", return_value=[]):
            result = queries.get_lead_stats()
        assert result["stats"]["total_ingested"] == 100_000


# ===========================================================================
# Integration tests — GET /api/leads/stats endpoint
# ===========================================================================

class TestLeadStatsEndpoint:
    """FastAPI TestClient tests for the /api/leads/stats route.

    queries.get_lead_stats is mocked at the app module level so no DB
    connection is ever attempted.
    """

    @pytest.fixture(autouse=True)
    def _setup_client(self):
        """Build a TestClient with auth bypassed via dependency override."""
        from fastapi.testclient import TestClient
        import app as app_module
        import queries

        original_require_admin = app_module.require_admin
        app_module.require_admin = lambda request=None: {"role": "admin", "actor": "test"}
        # Override require_admin so every request is pre-authenticated
        app_module.app.dependency_overrides[original_require_admin] = lambda: {"role": "admin", "actor": "test"}

        self.client = TestClient(app_module.app, raise_server_exceptions=True)
        self.queries = queries
        yield
        app_module.require_admin = original_require_admin
        app_module.app.dependency_overrides.clear()

    @property
    def _full_mock_return(self):
        return {
            "stats": STATS_ROW,
            "queue_breakdown": QUEUE_BREAKDOWN_ROWS,
            "failure_reasons": FAILURE_REASON_ROWS,
        }

    def test_endpoint_returns_200(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        assert response.status_code == 200

    def test_response_contains_stats_key(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        assert "stats" in response.json()

    def test_response_contains_queue_breakdown_key(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        assert "queue_breakdown" in response.json()

    def test_response_contains_failure_reasons_key(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        assert "failure_reasons" in response.json()

    def test_stats_has_all_required_sub_keys(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        stats = response.json()["stats"]
        required = {"total_ingested", "invites_sent", "accepted", "pending_acceptance", "stopped"}
        assert required.issubset(set(stats.keys()))

    def test_endpoint_calls_get_lead_stats_with_no_campaign_id_by_default(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return) as mock_fn:
            self.client.get("/api/leads/stats")
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs.get("campaign_id") in (None, ""), (
            "Without query param, campaign_id should be None or empty"
        )

    def test_endpoint_passes_campaign_id_query_param_through(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return) as mock_fn:
            self.client.get("/api/leads/stats?campaign_id=CAMPAIGN_3")
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs.get("campaign_id") == "CAMPAIGN_3"

    def test_endpoint_passes_none_when_campaign_id_omitted(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return) as mock_fn:
            self.client.get("/api/leads/stats")
        _, kwargs = mock_fn.call_args
        assert kwargs.get("campaign_id") is None

    def test_response_values_match_mock_data(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        body = response.json()
        assert body["stats"]["total_ingested"] == 150
        assert body["stats"]["invites_sent"] == 100
        assert body["stats"]["accepted"] == 60
        assert body["stats"]["pending_acceptance"] == 40
        assert body["stats"]["stopped"] == 5

    def test_queue_breakdown_is_list_in_response(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        assert isinstance(response.json()["queue_breakdown"], list)

    def test_failure_reasons_is_list_in_response(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        assert isinstance(response.json()["failure_reasons"], list)

    def test_campaign_id_query_param_forwarded_correctly_for_campaign_1(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return) as mock_fn:
            self.client.get("/api/leads/stats?campaign_id=CAMPAIGN_1")
        _, kwargs = mock_fn.call_args
        assert kwargs.get("campaign_id") == "CAMPAIGN_1"

    def test_endpoint_returns_json_content_type(self):
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        assert "application/json" in response.headers.get("content-type", "")

    def test_endpoint_handles_empty_results_gracefully(self):
        empty_result = {
            "stats": {k: 0 for k in STATS_ROW},
            "queue_breakdown": [],
            "failure_reasons": [],
        }
        with patch.object(self.queries, "get_lead_stats", return_value=empty_result):
            response = self.client.get("/api/leads/stats")
        assert response.status_code == 200
        body = response.json()
        assert body["queue_breakdown"] == []
        assert body["failure_reasons"] == []

    def test_endpoint_does_not_require_campaign_id_param(self):
        """campaign_id must be optional — omitting it should not return 422."""
        with patch.object(self.queries, "get_lead_stats", return_value=self._full_mock_return):
            response = self.client.get("/api/leads/stats")
        assert response.status_code != 422
