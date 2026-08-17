"""DYNAMIC-002 step 1 — the default "Overview" home view, as data.

The home page becomes a stored omni_views row instead of hardcoded React. This
module defines the canonical Overview layout (the same information the static
Overview page showed — contacts, leads, pipeline, campaigns — expressed as
widget instances over the constrained query DSL) and the lazy-seed logic.

Kept pure + declarative: the layout is validated through validate_layout() at
seed time, so the default can never carry a query the runtime would refuse. If
seeding ever fails, the frontend falls back to the static page (zero-risk).
"""

from __future__ import annotations

from typing import Any

# The slug that marks a workspace's home view. The Overview page asks for the
# default; we seed this one on first request if none exists.
DEFAULT_VIEW_NAME = "Overview"

# The canonical home layout — the static Overview page re-expressed as widgets.
# Every query here uses only whitelisted entities/fields (see view_query.ENTITIES);
# validate_layout() compile-checks each at seed time.
DEFAULT_LAYOUT: list[dict[str, Any]] = [
    {
        "id": "stat-contacts",
        "type": "stat",
        "title": "Contacts",
        "width": 1,
        "query": {"entity": "contacts", "metrics": [{"fn": "count", "alias": "total"}]},
    },
    {
        "id": "stat-active-leads",
        "type": "stat",
        "title": "Active leads",
        "width": 1,
        "query": {
            "entity": "leads",
            "filters": [{"field": "status", "op": "eq", "value": "active"}],
            "metrics": [{"fn": "count", "alias": "active"}],
        },
    },
    {
        "id": "stat-campaigns",
        "type": "stat",
        "title": "Campaigns",
        "width": 1,
        "query": {"entity": "campaigns", "metrics": [{"fn": "count", "alias": "total"}]},
    },
    {
        "id": "stat-conversations",
        "type": "stat",
        "title": "Conversations",
        "width": 1,
        "query": {
            "entity": "messages",
            "filters": [{"field": "direction", "op": "eq", "value": "inbound"}],
            "metrics": [{"fn": "count_distinct", "field": "contact_id", "alias": "threads"}],
        },
    },
    {
        "id": "new-contacts-trend",
        "type": "line_chart",
        "title": "New contacts (weekly)",
        "width": 2,
        "query": {"entity": "contacts", "time_bucket": "week", "metrics": [{"fn": "count", "alias": "added"}]},
    },
    {
        "id": "deals-by-stage",
        "type": "bar_chart",
        "title": "Deals by stage",
        "width": 2,
        "query": {
            "entity": "deals",
            "group_by": ["stage"],
            "metrics": [{"fn": "count", "alias": "deals"}],
        },
    },
    {
        "id": "recent-campaigns",
        "type": "table",
        "title": "Campaigns",
        "width": 2,
        "query": {"entity": "campaigns", "select": ["name", "status", "created_at"], "limit": 8},
    },
    {
        "id": "recent-contacts",
        "type": "list",
        "title": "Recent contacts",
        "width": 2,
        "query": {"entity": "contacts", "select": ["first_name", "company"], "limit": 12},
    },
]
