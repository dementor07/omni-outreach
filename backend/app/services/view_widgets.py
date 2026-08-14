"""DYNAMIC-001 — the widget vocabulary dynamic views are assembled from.

Mirrors the node-manifest pattern one level up the stack: NodeManifest describes
the campaign primitives agents compose into workflows; WidgetInstance describes
the *interface* primitives agents compose into screens. A view (omni_views row)
is a name + a list of widget instances, each binding a QuerySpec to a renderer.

Served machine-readable on GET /views/widgets (alongside the entity catalog) so
both the in-product view architect and external agents discover the interface
vocabulary the same way they discover the node vocabulary on GET /nodes.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.services.view_query import QuerySpec, QueryValidationError, build_query

WidgetType = Literal["stat", "table", "bar_chart", "line_chart", "list"]

_WIDGET_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}\Z")

# DYNAMIC-003 — chart presentation options.
#
# Charts used to be single-series, single-hue, with no axis and no key: a view
# could SAY "sends by campaign" but could not draw two campaigns side by side or
# tell the reader which colour was which. These options are the vocabulary for
# that, and because WIDGET_TYPES is served verbatim on GET /views/widgets they
# are discoverable by the in-product architect AND any external agent harness.
#
# Series colour is deliberately NOT authorable. Slots are assigned by position
# from one validated categorical palette (see frontend VIZ_SERIES): the ordering
# is what keeps adjacent series distinguishable under colour-vision deficiency,
# so letting a prompt pick hex would quietly break the accessibility guarantee.
_CHART_OPTIONS_DOC: dict[str, str] = {
    "legend": "bool — show the key. Defaults to on whenever the query has 2+ metrics; a single series needs no key because the title names it.",
    "x_label": "string <=40 — axis caption for the category/time axis.",
    "y_label": "string <=40 — axis caption for the value axis.",
    "series_labels": "object — map a metric alias to the human label used in the key, e.g. {\"c2_sent\": \"Campaign 2\"}.",
    "value_labels": "bool — print the value on the mark. Bars label every bar tip; lines label only the final point (a number on every point is unreadable).",
}

# What each widget type means + the query shape it needs. This doc block IS the
# machine contract — it goes verbatim into GET /views/widgets and the architect
# prompt, so keep it accurate.
WIDGET_TYPES: dict[str, dict[str, Any]] = {
    "stat": {
        "summary": "One big number (optionally vs a label). Query must be an aggregate with at least one metric and NO group_by/time_bucket.",
        "options": {},
    },
    "table": {
        "summary": "Tabular data. Either a rows query (select columns) or a grouped aggregate (group_by + metrics).",
        "options": {},
    },
    "bar_chart": {
        "summary": (
            "Horizontal bars comparing categories. Query needs exactly one group_by field "
            "(the category) plus at least one metric. Add MORE metrics to draw several "
            "series per category — grouped by default, or set stacked=true to stack them. "
            "No time_bucket."
        ),
        "options": {**_CHART_OPTIONS_DOC, "stacked": "bool — stack the series within each category instead of grouping them side by side."},
    },
    "line_chart": {
        "summary": (
            "Trend over time. Query needs time_bucket (day/week/month) plus at least one "
            "metric. Add MORE metrics to plot several lines on one shared axis — use this "
            "to compare campaigns over the same period."
        ),
        "options": dict(_CHART_OPTIONS_DOC),
    },
    "list": {
        "summary": "Compact record list (feed style). Rows query only — no metrics/group_by; first two selected columns become title/subtitle.",
        "options": {},
    },
}

_CHART_TYPES = frozenset({"bar_chart", "line_chart"})


class WidgetOptions(BaseModel):
    """Presentation-only. Never changes what a query returns, so it can never
    make a widget mean something its data does not support."""

    model_config = {"extra": "forbid"}

    legend: bool | None = None
    stacked: bool = False
    value_labels: bool = True
    x_label: str | None = Field(None, max_length=40)
    y_label: str | None = Field(None, max_length=40)
    series_labels: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_series_labels(self) -> WidgetOptions:
        if len(self.series_labels) > 8:
            raise ValueError("series_labels is capped at 8 entries")
        for alias, label in self.series_labels.items():
            if not alias or len(alias) > 64:
                raise ValueError(f"series_labels key {alias!r} must be 1-64 characters")
            if not label or len(label) > 40:
                raise ValueError(f"series_labels[{alias!r}] must be 1-40 characters")
        return self


class WidgetInstance(BaseModel):
    id: str = Field(max_length=40, description="Stable slug unique within the view")
    type: WidgetType
    title: str = Field(min_length=1, max_length=80)
    query: QuerySpec
    width: int = Field(2, ge=1, le=4, description="Grid columns out of 4")
    height: int = Field(1, ge=1, le=3, description="Grid rows")
    options: WidgetOptions = Field(default_factory=WidgetOptions)

    @model_validator(mode="after")
    def validate_shape(self) -> WidgetInstance:
        if not _WIDGET_ID_RE.fullmatch(self.id):
            raise ValueError(f"widget id {self.id!r} must match {_WIDGET_ID_RE.pattern}")
        q = self.query
        aggregate = bool(q.metrics or q.group_by or q.time_bucket)
        if self.type == "stat":
            if not q.metrics or q.group_by or q.time_bucket:
                raise ValueError("stat widgets need >=1 metric and no group_by/time_bucket")
        elif self.type == "bar_chart":
            if len(q.group_by) != 1 or q.time_bucket:
                raise ValueError("bar_chart widgets need exactly one group_by and no time_bucket")
        elif self.type == "line_chart":
            if not q.time_bucket:
                raise ValueError("line_chart widgets need a time_bucket")
        elif self.type == "list":
            if aggregate:
                raise ValueError("list widgets are rows-only (no metrics/group_by/time_bucket)")
        # Presentation options must belong to the widget that carries them, or a
        # view silently claims a capability it will not render.
        if self.type not in _CHART_TYPES:
            declared = self.options.model_dump(exclude_defaults=True)
            if declared:
                raise ValueError(
                    f"{self.type} widgets take no chart options; got {sorted(declared)}"
                )
        if self.options.stacked and self.type != "bar_chart":
            raise ValueError("stacked is a bar_chart option")
        if self.type in _CHART_TYPES:
            aliases = {m.alias for m in q.metrics if m.alias}
            unknown = sorted(set(self.options.series_labels) - aliases)
            if unknown:
                raise ValueError(
                    f"series_labels refers to {unknown} which are not metric aliases "
                    f"in this query; available aliases are {sorted(aliases)}"
                )
        # Compile once at validation time so a saved view can never carry a
        # query the runtime would refuse.
        build_query(q)
        return self


class ViewLayoutError(ValueError):
    """A view layout failed validation; message lists every widget's problem."""


def validate_layout(raw_layout: list[Any]) -> list[WidgetInstance]:
    """Validate a full view layout. Raises ViewLayoutError listing ALL problems
    (the architect repair loop needs the complete list, not just the first)."""
    if not isinstance(raw_layout, list) or not raw_layout:
        raise ViewLayoutError("layout must be a non-empty list of widgets")
    if len(raw_layout) > 12:
        raise ViewLayoutError("layout is capped at 12 widgets")
    widgets: list[WidgetInstance] = []
    problems: list[str] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(raw_layout):
        try:
            widget = WidgetInstance.model_validate(item)
        except (ValidationError, QueryValidationError, ValueError) as exc:
            problems.append(f"widget[{idx}]: {exc}")
            continue
        if widget.id in seen_ids:
            problems.append(f"widget[{idx}]: duplicate widget id {widget.id!r}")
            continue
        seen_ids.add(widget.id)
        widgets.append(widget)
    if problems:
        raise ViewLayoutError("; ".join(problems))
    return widgets


def widget_manifests() -> list[dict[str, Any]]:
    return [
        {"type": wtype, **info, "instance_schema": {
            "id": "slug", "type": wtype, "title": "string",
            "query": "QuerySpec (see entity catalog)",
            "width": "1-4 grid columns", "height": "1-3 grid rows",
        }}
        for wtype, info in WIDGET_TYPES.items()
    ]
