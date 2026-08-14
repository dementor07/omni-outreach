"""DYNAMIC-003 — chart presentation options (colour slots, keys, axis captions).

Before this, every chart was single-series and single-hue with no axis and no
key: a view could SAY "sends by campaign" but could not draw two campaigns side
by side, and nothing told the reader which colour was which. WIDGET_TYPES gained
an options vocabulary, and because that dict is served verbatim on
GET /views/widgets it is what both the in-product architect and an external
agent harness discover.

Two things are locked here beyond the happy path:

  * options are presentation-only and must belong to the widget carrying them,
    so a view can never claim a capability it will not render; and
  * the harness's OWN ViewSpec JSON schema must allow them. That schema is what
    the agent is *constrained* to emit, so an empty options object there made the
    whole feature unauthorable no matter what the brief said — a silent
    integration break that no backend test would have caught.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

REPO = Path(__file__).resolve().parents[2]


def _widget(**overrides):
    base = {
        "id": "sends_by_campaign",
        "type": "bar_chart",
        "title": "Sends by campaign",
        "query": {
            "entity": "send_outcomes",
            "group_by": ["status"],
            "metrics": [
                {"fn": "count", "field": "id", "alias": "c1_sent"},
                {"fn": "count", "field": "id", "alias": "c2_sent"},
            ],
        },
        "width": 2,
        "height": 1,
    }
    base.update(overrides)
    return base


# ── the vocabulary is discoverable, or agents cannot use it ────────────────────


def test_chart_options_are_published_in_the_widget_catalog():
    """GET /views/widgets is the machine contract; an undocumented option is an
    option no agent will ever emit."""
    from app.services.view_widgets import widget_manifests

    by_type = {m["type"]: m for m in widget_manifests()}
    for chart in ("bar_chart", "line_chart"):
        options = by_type[chart]["options"]
        assert {"legend", "series_labels", "x_label", "y_label", "value_labels"} <= set(options)
    assert "stacked" in by_type["bar_chart"]["options"]
    assert "stacked" not in by_type["line_chart"]["options"]


def test_multi_metric_chart_is_valid():
    """Several metrics in one query IS the multi-series mechanism."""
    from app.services.view_widgets import WidgetInstance

    widget = WidgetInstance.model_validate(_widget(options={
        "legend": True,
        "series_labels": {"c1_sent": "Campaign 1", "c2_sent": "Campaign 2"},
        "x_label": "Outcome status",
        "stacked": True,
    }))
    assert widget.options.stacked is True
    assert widget.options.series_labels["c2_sent"] == "Campaign 2"


# ── presentation options must belong to the widget carrying them ───────────────


def test_non_chart_widget_rejects_chart_options():
    from app.services.view_widgets import WidgetInstance

    with pytest.raises(ValueError, match="take no chart options"):
        WidgetInstance.model_validate({
            "id": "total", "type": "stat", "title": "Total",
            "query": {"entity": "send_outcomes", "metrics": [{"fn": "count", "alias": "n"}]},
            "options": {"legend": True},
        })


def test_stacked_is_rejected_on_a_line_chart():
    from app.services.view_widgets import WidgetInstance

    with pytest.raises(ValueError, match="stacked is a bar_chart option"):
        WidgetInstance.model_validate({
            "id": "trend", "type": "line_chart", "title": "Trend",
            "query": {
                "entity": "send_outcomes", "time_bucket": "day",
                "metrics": [{"fn": "count", "alias": "n"}],
            },
            "options": {"stacked": True},
        })


def test_series_labels_must_name_real_metric_aliases():
    """A label for a series that does not exist is a silent no-op in the UI —
    exactly the kind of plausible-but-wrong output the grounding gate exists for."""
    from app.services.view_widgets import WidgetInstance

    with pytest.raises(ValueError, match="not metric aliases"):
        WidgetInstance.model_validate(_widget(options={"series_labels": {"nope": "Campaign 9"}}))


def test_unknown_option_keys_are_rejected():
    from app.services.view_widgets import WidgetInstance

    with pytest.raises(ValueError):
        WidgetInstance.model_validate(_widget(options={"colour": "#ff0000"}))


def test_series_colour_is_not_authorable():
    """Slot ORDER is the colour-vision-deficiency safety mechanism. If a prompt
    could pick hex, the validated palette guarantee would be silently voidable."""
    from app.services.view_widgets import WidgetOptions

    assert not {"color", "colour", "palette", "colors"} & set(WidgetOptions.model_fields)


# ── the harness must be ABLE to emit what the backend accepts ──────────────────


def test_harness_viewspec_schema_allows_chart_options():
    source = (REPO / "scripts/omni_harness.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    schema_node = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", None) == "VIEW_SPEC_SCHEMA"
    )
    schema = ast.literal_eval(schema_node)
    options = schema["$defs"]["options"]
    assert set(options["properties"]) >= {
        "legend", "stacked", "value_labels", "x_label", "y_label", "series_labels",
    }, "the agent is constrained by this schema; missing keys are unauthorable"
    # And the widget still points at it, or the definition is dead weight.
    assert schema["$defs"]["widget"]["properties"]["options"] == {"$ref": "#/$defs/options"}


def test_harness_schema_does_not_expose_series_colour():
    source = (REPO / "scripts/omni_harness.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    schema_node = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", None) == "VIEW_SPEC_SCHEMA"
    )
    schema = ast.literal_eval(schema_node)
    assert not {"color", "colour", "palette"} & set(schema["$defs"]["options"]["properties"])
