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
        "summary": "Horizontal bars comparing categories. Query needs exactly one group_by field (the category) plus at least one metric (the bar length). No time_bucket.",
        "options": {},
    },
    "line_chart": {
        "summary": "Trend over time. Query needs time_bucket (day/week/month) plus at least one metric.",
        "options": {},
    },
    "list": {
        "summary": "Compact record list (feed style). Rows query only — no metrics/group_by; first two selected columns become title/subtitle.",
        "options": {},
    },
}


class WidgetInstance(BaseModel):
    id: str = Field(max_length=40, description="Stable slug unique within the view")
    type: WidgetType
    title: str = Field(min_length=1, max_length=80)
    query: QuerySpec
    width: int = Field(2, ge=1, le=4, description="Grid columns out of 4")
    height: int = Field(1, ge=1, le=3, description="Grid rows")
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_shape(self) -> "WidgetInstance":
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
