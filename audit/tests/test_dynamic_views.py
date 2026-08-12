"""DYNAMIC-001 — regression locks for the dynamic-interface layer.

Three pure surfaces, no DB/network:
  * view_query.build_query — the constrained query DSL. The security property
    under test: user strings can never become SQL identifiers, and values only
    ever travel as bind parameters.
  * view_widgets.validate_layout — the widget vocabulary's shape rules; a
    stored view can never carry a query the runtime would refuse.
  * campaign_architect / view_architect validators — the prompt→spec repair
    loop's validation core.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.view_query import (
    QueryFilter,
    QueryMetric,
    QuerySort,
    QuerySpec,
    QueryValidationError,
    build_query,
    entity_catalog,
)
from app.services.view_widgets import ViewLayoutError, validate_layout
from app.services.campaign_architect import _connections_block
from app.services.campaign_architect import _validate as validate_campaign_payload
from app.services.view_architect import _validate as validate_view_payload


# ── Query DSL: identifier whitelisting ───────────────────────────────────────


def test_unknown_entity_rejected():
    with pytest.raises(QueryValidationError, match="unknown entity"):
        build_query(QuerySpec(entity="pg_shadow"))


def test_unknown_field_rejected():
    with pytest.raises(QueryValidationError, match="unknown field"):
        build_query(QuerySpec(entity="contacts", select=["password"]))


def test_injection_shaped_field_rejected():
    hostile = "email; DROP TABLE omni_contacts;--"
    with pytest.raises(QueryValidationError, match="unknown field"):
        build_query(
            QuerySpec(entity="contacts", filters=[QueryFilter(field=hostile, op="eq", value="x")])
        )


def test_injection_shaped_group_by_rejected():
    with pytest.raises(QueryValidationError, match="unknown field"):
        build_query(QuerySpec(entity="contacts", group_by=["company) UNION SELECT * FROM users --"]))


def test_hostile_metric_alias_rejected():
    with pytest.raises(QueryValidationError, match="alias"):
        build_query(
            QuerySpec(
                entity="contacts",
                metrics=[QueryMetric(fn="count", alias="x, (SELECT 1)")],
            )
        )


# ── Query DSL: values are parameterized, never inlined ──────────────────────


def test_filter_values_travel_as_bind_params():
    built = build_query(
        QuerySpec(
            entity="contacts",
            filters=[QueryFilter(field="company", op="contains", value="Robert'); DROP TABLE--")],
        )
    )
    assert "Robert" not in built.sql
    assert "$1" in built.sql
    assert built.params == ("%Robert'); DROP TABLE--%",)


def test_in_op_binds_a_list():
    built = build_query(
        QuerySpec(
            entity="send_outcomes",
            filters=[QueryFilter(field="status", op="in", value=["sent", "failed"])],
        )
    )
    assert "= ANY($1)" in built.sql
    assert built.params == (["sent", "failed"],)


def test_bad_uuid_value_fails_closed():
    with pytest.raises(QueryValidationError, match="not a valid uuid"):
        build_query(
            QuerySpec(entity="leads", filters=[QueryFilter(field="workflow_id", op="eq", value="not-a-uuid")])
        )


def test_contains_on_non_text_rejected():
    with pytest.raises(QueryValidationError, match="contains"):
        build_query(
            QuerySpec(entity="deals", filters=[QueryFilter(field="value", op="contains", value="9")])
        )


# ── Query DSL: shape ─────────────────────────────────────────────────────────


def test_rows_mode_defaults():
    built = build_query(QuerySpec(entity="contacts"))
    assert built.sql.startswith("SELECT first_name, last_name, email, company")
    assert "ORDER BY updated_at DESC" in built.sql
    assert built.sql.endswith("LIMIT 50")


def test_grouped_aggregate_shape():
    built = build_query(
        QuerySpec(entity="send_outcomes", group_by=["channel"], metrics=[QueryMetric(fn="count")])
    )
    assert "GROUP BY channel" in built.sql
    assert "COUNT(*) AS count" in built.sql
    assert "ORDER BY count DESC" in built.sql
    assert built.columns == ("channel", "count")


def test_time_bucket_shape():
    built = build_query(
        QuerySpec(entity="contacts", time_bucket="day", metrics=[QueryMetric(fn="count")])
    )
    assert "date_trunc('day', created_at) AS bucket" in built.sql
    assert "ORDER BY bucket ASC" in built.sql
    assert built.columns == ("bucket", "count")


def test_sum_requires_numeric_field():
    with pytest.raises(QueryValidationError, match="numeric"):
        build_query(QuerySpec(entity="contacts", metrics=[QueryMetric(fn="sum", field="email")]))


def test_aggregate_sort_must_be_group_or_alias():
    with pytest.raises(QueryValidationError, match="sort field"):
        build_query(
            QuerySpec(
                entity="send_outcomes",
                group_by=["channel"],
                metrics=[QueryMetric(fn="count")],
                sort=[QuerySort(field="provider", dir="desc")],
            )
        )


def test_limit_capped_by_schema():
    with pytest.raises(ValidationError):
        QuerySpec(entity="contacts", limit=501)


def test_catalog_matches_entities():
    catalog = entity_catalog()
    assert "contacts" in catalog["entities"]
    assert catalog["entities"]["messages"]["time_field"] == "occurred_at"


# ── Gate findings from the DYNAMIC-001 fresh-context review ──────────────────


def test_metric_alias_colliding_with_group_field_rejected():
    """MEDIUM (review): a metric alias equal to a group-by field name produced two
    same-named SELECT columns that the router's row-dict silently collapsed."""
    with pytest.raises(QueryValidationError, match="collides"):
        build_query(
            QuerySpec(
                entity="send_outcomes",
                group_by=["channel"],
                metrics=[QueryMetric(fn="count", alias="channel")],
            )
        )


def test_value_required_op_with_none_rejected():
    """LOW (review): eq/contains/etc. with no value used to compile to a 'None'
    literal match instead of failing closed."""
    with pytest.raises(ValidationError, match="requires a value"):
        QueryFilter(field="email", op="eq", value=None)
    with pytest.raises(ValidationError, match="requires a value"):
        QueryFilter(field="company", op="contains")


def test_in_list_length_capped():
    """MEDIUM (review): an unbounded in-list is a DoS lever (huge ANY() array)."""
    with pytest.raises(ValidationError, match="capped"):
        QueryFilter(field="status", op="in", value=[f"s{i}" for i in range(201)])
    # 200 is allowed (the cap boundary).
    ok = QueryFilter(field="status", op="in", value=[f"s{i}" for i in range(200)])
    assert len(ok.value) == 200


def test_oversized_scalar_value_rejected():
    """MEDIUM (review): an oversized ILIKE/eq value is a DoS lever."""
    with pytest.raises(ValidationError, match="exceeds"):
        QueryFilter(field="company", op="contains", value="x" * 501)


def test_valueless_ops_need_no_value():
    """is_null/not_null legitimately carry no value and must still validate."""
    assert QueryFilter(field="email", op="is_null").value is None
    built = build_query(
        QuerySpec(entity="contacts", filters=[QueryFilter(field="email", op="not_null")])
    )
    assert "email IS NOT NULL" in built.sql


# ── Widget vocabulary ────────────────────────────────────────────────────────


def _stat(id_: str = "total") -> dict:
    return {
        "id": id_,
        "type": "stat",
        "title": "Total contacts",
        "query": {"entity": "contacts", "metrics": [{"fn": "count"}]},
        "width": 1,
    }


def test_valid_layout_passes():
    widgets = validate_layout(
        [
            _stat(),
            {
                "id": "by-channel",
                "type": "bar_chart",
                "title": "Sends by channel",
                "query": {"entity": "send_outcomes", "group_by": ["channel"], "metrics": [{"fn": "count"}]},
            },
            {
                "id": "trend",
                "type": "line_chart",
                "title": "New contacts",
                "query": {"entity": "contacts", "time_bucket": "week", "metrics": [{"fn": "count"}]},
            },
            {
                "id": "recent",
                "type": "list",
                "title": "Recent contacts",
                "query": {"entity": "contacts", "select": ["first_name", "company"]},
            },
        ]
    )
    assert [w.id for w in widgets] == ["total", "by-channel", "trend", "recent"]


def test_stat_with_group_by_rejected():
    bad = _stat()
    bad["query"]["group_by"] = ["company"]
    with pytest.raises(ViewLayoutError, match="stat widgets"):
        validate_layout([bad])


def test_bar_chart_needs_exactly_one_group():
    with pytest.raises(ViewLayoutError, match="bar_chart"):
        validate_layout(
            [{
                "id": "b", "type": "bar_chart", "title": "x",
                "query": {"entity": "contacts", "metrics": [{"fn": "count"}]},
            }]
        )


def test_line_chart_needs_time_bucket():
    with pytest.raises(ViewLayoutError, match="line_chart"):
        validate_layout(
            [{
                "id": "l", "type": "line_chart", "title": "x",
                "query": {"entity": "contacts", "metrics": [{"fn": "count"}]},
            }]
        )


def test_duplicate_widget_ids_rejected():
    with pytest.raises(ViewLayoutError, match="duplicate"):
        validate_layout([_stat("same"), _stat("same")])


def test_widget_with_unknown_field_rejected():
    with pytest.raises(ViewLayoutError, match="unknown field"):
        validate_layout(
            [{
                "id": "x", "type": "list", "title": "x",
                "query": {"entity": "contacts", "select": ["ssn"]},
            }]
        )


def test_layout_capped_at_12():
    with pytest.raises(ViewLayoutError, match="capped"):
        validate_layout([_stat(f"w{i}") for i in range(13)])


# ── Architect validators (the repair loop's core) ────────────────────────────


def test_campaign_payload_validates_to_spec():
    spec = validate_campaign_payload(
        {
            "name": "Apollo India CEOs",
            "target_contacts": 25,
            "sources": [
                {
                    "provider": "apollo_people",
                    "connection_name": "apollo",
                    "titles": ["CEO"],
                    "employee_ranges": ["10,100"],
                }
            ],
            "enrichment": [{"provider": "apollo", "connection_name": "apollo"}],
            "messages": [],
            "skip_verification": True,
        }
    )
    assert spec.sources[0].provider == "apollo_people"
    assert spec.skip_verification is True


def test_campaign_payload_missing_connection_fails():
    with pytest.raises(ValidationError, match="connection_name"):
        validate_campaign_payload(
            {
                "name": "x",
                "target_contacts": 5,
                "sources": [{"provider": "apollo_people", "titles": ["CEO"]}],
            }
        )


def test_connections_block_grounds_the_prompt():
    empty = _connections_block([])
    assert "NO connections" in empty
    listed = _connections_block([{"provider": "apollo", "name": "apollo-main"}])
    assert "provider=apollo name=apollo-main" in listed


def test_campaign_ai_supports_named_byok_and_read_only_agent_validation():
    import inspect
    from app.routers import canvas
    from app.services import campaign_architect

    generate_src = inspect.getsource(campaign_architect.generate_campaign_spec)
    validate_src = inspect.getsource(canvas.validate_campaign_spec)
    assert "connection_name" in generate_src
    assert "anthropic_key(workspace_id, connection_name)" in generate_src
    assert "_assert_campaign_spec_connections" in validate_src
    assert "compile_campaign_spec" in validate_src
    assert "acquire(" not in validate_src, "agent validation must not write a workflow"

    root = Path(__file__).resolve().parents[2]
    architect_ui = (root / "frontend/src/components/CampaignArchitect.tsx").read_text(encoding="utf-8")
    assert "Workspace key (BYOK)" in architect_ui
    assert "Agent harness" in architect_ui
    assert "Create draft campaign" in architect_ui
    assert "canvas.validateSpec" in architect_ui


def test_view_payload_normalizes_icon_and_validates_layout():
    view = validate_view_payload(
        {"name": "Morning brief", "icon": "not-a-real-icon", "layout": [_stat()]}
    )
    assert view["icon"] == "layout-dashboard"
    assert view["layout"][0]["id"] == "total"


def test_view_payload_bad_name_rejected():
    with pytest.raises(ViewLayoutError, match="name"):
        validate_view_payload({"name": "", "layout": [_stat()]})


# ── DYNAMIC-002 step 1: the default Overview home view ───────────────────────


def test_default_overview_layout_compiles():
    """The seeded home view must validate through the SAME whitelist as any
    other view — every widget query compiles, or the frontend falls back."""
    from app.services.default_view import DEFAULT_LAYOUT, DEFAULT_VIEW_NAME

    widgets = validate_layout(DEFAULT_LAYOUT)
    assert len(widgets) == len(DEFAULT_LAYOUT)
    assert DEFAULT_VIEW_NAME == "Overview"
    # It exercises a real spread of widget types (not just stats).
    kinds = {w.type for w in widgets}
    assert {"stat", "line_chart", "bar_chart", "table", "list"} <= kinds


def test_default_overview_uses_only_catalogued_fields():
    """Every field the default layout references must exist in the entity
    catalog — a typo here would 500 the home page on a real query."""
    from app.services.default_view import DEFAULT_LAYOUT
    from app.services.view_query import ENTITIES

    for widget in DEFAULT_LAYOUT:
        q = widget["query"]
        entity = ENTITIES[q["entity"]]
        refs: list[str] = list(q.get("select", []))
        refs += list(q.get("group_by", []))
        refs += [f["field"] for f in q.get("filters", [])]
        refs += [m["field"] for m in q.get("metrics", []) if m.get("field")]
        for field in refs:
            assert field in entity.columns, f"{widget['id']}: unknown field {field!r} on {q['entity']}"


def test_overview_and_custom_views_share_the_agent_composer():
    root = Path(__file__).resolve().parents[2]
    overview = (root / "frontend/src/pages/Overview.tsx").read_text(encoding="utf-8")
    dynamic = (root / "frontend/src/pages/DynamicView.tsx").read_text(encoding="utf-8")
    composer = (root / "frontend/src/components/ViewPromptBar.tsx").read_text(encoding="utf-8")
    assert "<ViewPromptBar" in overview
    assert "<ViewPromptBar" in dynamic
    assert "views.edit(viewId, text)" in composer


# ── DYNAMIC-002 step 2: agent edits a view ───────────────────────────────────


def test_edit_validate_rejects_bad_model_output():
    """The edit path runs model output through the SAME validator as generate —
    a revised layout the model hallucinates that references an unknown field is
    rejected, never persisted."""
    bad = {
        "name": "Edited",
        "layout": [{
            "id": "x", "type": "list", "title": "x",
            "query": {"entity": "contacts", "select": ["ssn"]},
        }],
    }
    with pytest.raises(ViewLayoutError, match="unknown field"):
        validate_view_payload(bad)


def test_edit_validate_accepts_a_good_revision():
    """A revised layout that adds a valid widget passes and normalizes."""
    good = {
        "name": "Overview",
        "layout": [
            _stat("keep"),
            {
                "id": "sends-by-status",
                "type": "bar_chart",
                "title": "Sends by status",
                "query": {"entity": "send_outcomes", "group_by": ["status"], "metrics": [{"fn": "count"}]},
            },
        ],
    }
    out = validate_view_payload(good)
    assert [w["id"] for w in out["layout"]] == ["keep", "sends-by-status"]


def test_view_architect_shares_one_validate_loop():
    """generate_view and edit_view must route through the same _run_architect
    helper (no cloned repair loop) — guards the DRY refactor."""
    import inspect
    from app.services import view_architect

    gen_src = inspect.getsource(view_architect.generate_view)
    edit_src = inspect.getsource(view_architect.edit_view)
    assert "_run_architect" in gen_src
    assert "_run_architect" in edit_src
