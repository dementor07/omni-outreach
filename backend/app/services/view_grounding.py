"""Live, workspace-scoped evidence for dynamic-view authoring.

ViewSpec validation proves that a query is syntactically safe; it does not prove
that the query means what its title claims.  This module supplies the missing
runtime half of that contract without giving an authoring agent arbitrary SQL:
every read still compiles through :mod:`app.services.view_query` and executes on
the request-scoped, RLS-armed connection.

The public seams are deliberately independent of the HTTP/job broker layers:

``capture_view_grounding``
    Freeze the values the current widgets actually return, plus campaign IDs and
    per-campaign lead/send-outcome breakdowns.

``review_candidate_view``
    Validate a complete candidate ViewSpec, execute every candidate query, and
    return a structured diff and warnings before anything is persisted.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.db import acquire
from app.services.view_architect import validate_candidate_view
from app.services.view_query import (
    ENTITIES,
    ENUM_VALUES,
    QueryMetric,
    QuerySort,
    QuerySpec,
    build_query,
)
from app.services.view_widgets import WidgetInstance

GROUNDING_VERSION = "view-grounding.v1"
MAX_CAMPAIGNS = 200
MAX_PREVIEW_ROWS = 50
MAX_CELL_CHARS = 500
QUERY_TIMEOUT_MS = 5_000
GROUNDING_BUDGET_SECONDS = 30
BREAKDOWN_GROUP_LIMIT = 500
SCOPE_ID_CHUNK_SIZE = 200
MAX_TARGETED_SCOPE_IDS = 2_400  # 12 widgets × 200 values per validated filter

_CAMPAIGN_ENTITIES = frozenset({"leads", "send_outcomes"})
_CAMPAIGN_WORD_RE = re.compile(r"\bcampaign(?:\s+|[-_])?(?:\d+|one|two)\b", re.IGNORECASE)
# A campaign NAME only earns a short "campaign n" alias when it actually says so.
# Matching any digit swept up "e2e" and "(v2)" and made the gate unsatisfiable.
_CAMPAIGN_NUMBER_RE = re.compile(r"\bcampaign (\d+)\b")
# On a send_outcomes widget, a bare Messages label is a sent-count claim too:
# the table stores attempts/outcomes, not one row per successfully sent message.
_SEND_WORD_RE = re.compile(r"\b(?:send|sends|sent|message|messages)\b", re.IGNORECASE)
_DELIVERED_WORD_RE = re.compile(r"\b(?:delivered|delivery|deliveries)\b", re.IGNORECASE)
_ALL_OUTCOMES_RE = re.compile(
    r"\b(?:send outcomes?|attempted sends?)\b",
    re.IGNORECASE,
)
_SEND_STATUS_RE = {
    "sent": re.compile(r"\b(?:sent|successful(?:ly)? sent)\b", re.IGNORECASE),
    "failed": re.compile(r"\b(?:failed|failures?)\b", re.IGNORECASE),
    "skipped": re.compile(r"\bskipped\b", re.IGNORECASE),
    "queued": re.compile(r"\bqueued\b", re.IGNORECASE),
}


class ViewGroundingTimeoutError(TimeoutError):
    """A bounded grounding/review read exceeded its control-plane budget."""


def _authoritative_values() -> dict[str, list[str]]:
    return {
        f"{entity}.{field}": sorted(values)
        for (entity, field), values in ENUM_VALUES.items()
    }


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_safe(value: Any) -> Any:
    """Normalize asyncpg values (UUID/datetime/Decimal) for a durable JSONB brief."""
    return jsonable_encoder(value)


def _bounded_json(value: Any) -> tuple[Any, bool]:
    """Bound verbose cells before durable payload/model prompt storage."""
    safe = _json_safe(value)
    if isinstance(safe, str):
        if len(safe) <= MAX_CELL_CHARS:
            return safe, False
        return safe[:MAX_CELL_CHARS] + "…", True
    if isinstance(safe, list):
        values: list[Any] = []
        truncated = False
        for item in safe:
            bounded, item_truncated = _bounded_json(item)
            values.append(bounded)
            truncated = truncated or item_truncated
        return values, truncated
    if isinstance(safe, dict):
        values: dict[str, Any] = {}
        truncated = False
        for key, item in safe.items():
            bounded, item_truncated = _bounded_json(item)
            values[str(key)] = bounded
            truncated = truncated or item_truncated
        return values, truncated
    return safe, False


async def _prepare_connection(conn: Any) -> None:
    # Each read remains independently bounded; a hostile/accidental aggregate
    # cannot occupy a backend worker indefinitely while live campaigns run.
    await conn.execute(f"SET LOCAL statement_timeout = '{QUERY_TIMEOUT_MS}ms'")


def _query_dict(spec: QuerySpec) -> dict[str, Any]:
    return spec.model_dump(mode="json")


def _error(exc: Exception) -> dict[str, str]:
    # QueryValidationError messages are useful to an agent.  Driver failures are
    # bounded so a dependency cannot dump a giant diagnostic into a job payload.
    detail = str(exc).strip() or exc.__class__.__name__
    return {"code": "query_execution_failed", "message": detail[:500]}


async def _source_max_at(conn: Any, spec: QuerySpec) -> Any:
    entity = ENTITIES[spec.entity]
    freshness_field = "updated_at" if "updated_at" in entity.columns else entity.time_field
    freshness = QuerySpec(
        entity=spec.entity,
        filters=spec.filters,
        metrics=[QueryMetric(fn="max", field=freshness_field, alias="source_max_at")],
        limit=1,
    )
    built = build_query(freshness)
    # This function's caller deliberately catches freshness failures. Give that
    # caught statement its own savepoint so PostgreSQL does not leave the outer
    # RLS transaction aborted for the rest of the review.
    async with conn.transaction():
        rows = await conn.fetch(built.sql, *built.params)
    return _json_safe(dict(rows[0]).get("source_max_at")) if rows else None


async def _capture_widget(conn: Any, raw_widget: dict[str, Any]) -> dict[str, Any]:
    executed_at = _iso_now()
    widget_id = str(raw_widget.get("id") or "")
    title = str(raw_widget.get("title") or widget_id)
    try:
        widget = WidgetInstance.model_validate(raw_widget)
        built = build_query(widget.query)
        # Candidate failures become review evidence rather than HTTP 500s. A
        # nested asyncpg transaction is a savepoint; on timeout/error it rolls
        # back only this query and keeps subsequent evidence reads usable.
        async with conn.transaction():
            records = await conn.fetch(built.sql, *built.params)
        rows: list[dict[str, Any]] = []
        content_truncated = False
        for record in records:
            bounded, row_truncated = _bounded_json(dict(record))
            rows.append(bounded)
            content_truncated = content_truncated or row_truncated
        freshness_error: dict[str, str] | None = None
        try:
            source_max_at = await _source_max_at(conn, widget.query)
        except Exception as exc:  # noqa: BLE001 - evidence records a bounded failure
            source_max_at = None
            freshness_error = {
                "code": "freshness_unavailable",
                "message": (str(exc).strip() or exc.__class__.__name__)[:500],
            }
        snapshot: dict[str, Any] = {
            "widget_id": widget.id,
            "title": widget.title,
            "entity": widget.query.entity,
            "query": _query_dict(widget.query),
            "columns": list(built.columns),
            "rows": rows[:MAX_PREVIEW_ROWS],
            "returned_rows": len(rows),
            "preview_rows": min(len(rows), MAX_PREVIEW_ROWS),
            "truncated": len(rows) > MAX_PREVIEW_ROWS,
            "content_truncated": content_truncated,
            "source_max_at": source_max_at,
            "executed_at": executed_at,
            "error": None,
        }
        if freshness_error is not None:
            snapshot["freshness_error"] = freshness_error
        return snapshot
    except Exception as exc:  # noqa: BLE001 - a broken stored widget must remain repairable
        return {
            "widget_id": widget_id,
            "title": title,
            "entity": (raw_widget.get("query") or {}).get("entity"),
            "query": _json_safe(raw_widget.get("query") or {}),
            "columns": [],
            "rows": [],
            "returned_rows": 0,
            "preview_rows": 0,
            "truncated": False,
            "content_truncated": False,
            "source_max_at": None,
            "executed_at": executed_at,
            "error": _error(exc),
        }


async def _fetch_rows(conn: Any, spec: QuerySpec) -> list[dict[str, Any]]:
    built = build_query(spec)
    return [_json_safe(dict(record)) for record in await conn.fetch(built.sql, *built.params)]


async def _targeted_campaign_identities(
    conn: Any,
    workflow_ids: set[str],
) -> list[dict[str, Any]]:
    """Resolve scoped UUIDs without expanding the bounded prompt catalog."""
    identities: list[dict[str, Any]] = []
    ordered = sorted(workflow_ids)
    for offset in range(0, len(ordered), SCOPE_ID_CHUNK_SIZE):
        chunk = ordered[offset:offset + SCOPE_ID_CHUNK_SIZE]
        identities.extend(await _fetch_rows(
            conn,
            QuerySpec(
                entity="campaigns",
                filters=[{"field": "id", "op": "in", "value": chunk}],
                select=["id", "name", "status", "updated_at"],
                limit=len(chunk),
            ),
        ))
    return identities


async def _campaign_context(
    conn: Any,
    scoped_workflow_ids: set[str] | None = None,
) -> dict[str, Any]:
    requested_scope_ids = set(scoped_workflow_ids or ())
    count_rows = await _fetch_rows(
        conn,
        QuerySpec(entity="campaigns", metrics=[QueryMetric(fn="count", alias="total")], limit=1),
    )
    campaign_total = int((count_rows[0] if count_rows else {}).get("total") or 0)
    campaigns = await _fetch_rows(
        conn,
        QuerySpec(
            entity="campaigns",
            select=["id", "name", "status", "updated_at"],
            sort=[QuerySort(field="updated_at", dir="desc")],
            limit=MAX_CAMPAIGNS,
        ),
    )
    targeted_campaigns = await _targeted_campaign_identities(conn, requested_scope_ids)
    lead_rows = await _fetch_rows(
        conn,
        QuerySpec(
            entity="leads",
            group_by=["workflow_id", "status"],
            metrics=[
                QueryMetric(fn="count", alias="count"),
                QueryMetric(fn="max", field="updated_at", alias="source_max_at"),
            ],
            limit=BREAKDOWN_GROUP_LIMIT,
        ),
    )
    outcome_rows = await _fetch_rows(
        conn,
        QuerySpec(
            entity="send_outcomes",
            group_by=["workflow_id", "status"],
            metrics=[
                QueryMetric(fn="count", alias="count"),
                QueryMetric(fn="max", field="occurred_at", alias="source_max_at"),
            ],
            limit=BREAKDOWN_GROUP_LIMIT,
        ),
    )
    lead_breakdown_truncated = len(lead_rows) >= BREAKDOWN_GROUP_LIMIT
    outcome_breakdown_truncated = len(outcome_rows) >= BREAKDOWN_GROUP_LIMIT

    by_id: dict[str, dict[str, Any]] = {}
    for campaign in [*campaigns, *targeted_campaigns]:
        campaign_id = str(campaign["id"])
        by_id[campaign_id] = {
            "id": campaign_id,
            "name": campaign.get("name"),
            "status": campaign.get("status"),
            "updated_at": campaign.get("updated_at"),
            "lead_status_counts": {},
            "send_outcome_status_counts": {},
            "lead_source_max_at": None,
            "send_outcome_source_max_at": None,
            "lead_breakdown_complete": not lead_breakdown_truncated,
            "send_outcome_breakdown_complete": not outcome_breakdown_truncated,
        }

    for row in lead_rows:
        campaign = by_id.get(str(row.get("workflow_id")))
        if campaign is None:
            continue
        campaign["lead_status_counts"][str(row.get("status"))] = int(row.get("count") or 0)
        current = campaign.get("lead_source_max_at")
        candidate = row.get("source_max_at")
        if candidate is not None and (current is None or str(candidate) > str(current)):
            campaign["lead_source_max_at"] = candidate

    for row in outcome_rows:
        campaign = by_id.get(str(row.get("workflow_id")))
        if campaign is None:
            continue
        campaign["send_outcome_status_counts"][str(row.get("status"))] = int(row.get("count") or 0)
        current = campaign.get("send_outcome_source_max_at")
        candidate = row.get("source_max_at")
        if candidate is not None and (current is None or str(candidate) > str(current)):
            campaign["send_outcome_source_max_at"] = candidate

    catalog_ids = [str(campaign["id"]) for campaign in campaigns]
    catalog_id_set = set(catalog_ids)
    identities = [by_id[campaign_id] for campaign_id in catalog_ids]
    resolved_scope_ids = sorted(requested_scope_ids & by_id.keys())
    scope_items = [
        by_id[campaign_id]
        for campaign_id in resolved_scope_ids
        if campaign_id not in catalog_id_set
    ]
    return {
        "total": campaign_total,
        "returned": len(identities),
        "truncated": campaign_total > len(identities),
        "items": identities,
        # Only explicitly referenced UUIDs missing from the catalog are added,
        # so a candidate can prove an old campaign while the prompt stays bound.
        "scope_items": scope_items,
        "scope_verification": {
            "requested_ids": sorted(requested_scope_ids),
            "resolved_ids": resolved_scope_ids,
            "missing_ids": sorted(requested_scope_ids - by_id.keys()),
        },
        "breakdowns": {
            "leads": {
                "group_limit": BREAKDOWN_GROUP_LIMIT,
                "groups_returned": len(lead_rows),
                "truncated": lead_breakdown_truncated,
            },
            "send_outcomes": {
                "group_limit": BREAKDOWN_GROUP_LIMIT,
                "groups_returned": len(outcome_rows),
                "truncated": outcome_breakdown_truncated,
            },
        },
        "observed_values": {
            "campaigns.status": sorted({
                str(item["status"])
                for item in [*identities, *scope_items]
                if item.get("status")
            }),
            "leads.status": sorted({str(row["status"]) for row in lead_rows if row.get("status") is not None}),
            "send_outcomes.status": sorted(
                {str(row["status"]) for row in outcome_rows if row.get("status") is not None}
            ),
        },
        "authoritative_values": _authoritative_values(),
    }


async def _capture_with_conn(
    conn: Any,
    view: dict[str, Any],
    scoped_workflow_ids: set[str] | None = None,
) -> dict[str, Any]:
    captured_at = _iso_now()
    widgets = [
        await _capture_widget(conn, raw_widget)
        for raw_widget in (view.get("layout") or [])
        if isinstance(raw_widget, dict)
    ]
    return {
        "version": GROUNDING_VERSION,
        "captured_at": captured_at,
        "widget_results": widgets,
        "campaigns": await _campaign_context(conn, scoped_workflow_ids),
    }


async def _capture_with_budget(conn: Any, view: dict[str, Any]) -> dict[str, Any]:
    try:
        async with asyncio.timeout(GROUNDING_BUDGET_SECONDS):
            await _prepare_connection(conn)
            return await _capture_with_conn(
                conn,
                view,
                _view_workflow_filter_values(view),
            )
    except TimeoutError as exc:
        raise ViewGroundingTimeoutError(
            f"view grounding exceeded the {GROUNDING_BUDGET_SECONDS}s read budget",
        ) from exc


async def capture_view_grounding(view: dict[str, Any]) -> dict[str, Any]:
    """Capture current widget values and campaign identity under request RLS.

    Broken stored widgets are returned as structured per-widget errors rather
    than aborting the brief; otherwise an agent could never repair one.
    """
    async with acquire() as conn:
        return await _capture_with_budget(conn, view)


def diff_views(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a stable, JSON-ready ViewSpec diff keyed by widget ID."""
    view_fields: dict[str, dict[str, Any]] = {}
    for field in ("name", "description", "icon"):
        if current.get(field) != candidate.get(field):
            view_fields[field] = {
                "before": _json_safe(current.get(field)),
                "after": _json_safe(candidate.get(field)),
            }

    current_widgets = {
        str(widget.get("id")): widget
        for widget in current.get("layout") or []
        if isinstance(widget, dict) and widget.get("id")
    }
    candidate_widgets = {
        str(widget.get("id")): widget
        for widget in candidate.get("layout") or []
        if isinstance(widget, dict) and widget.get("id")
    }
    added = [widget_id for widget_id in candidate_widgets if widget_id not in current_widgets]
    removed = [widget_id for widget_id in current_widgets if widget_id not in candidate_widgets]
    changed: list[dict[str, Any]] = []
    for widget_id in candidate_widgets.keys() & current_widgets.keys():
        before = current_widgets[widget_id]
        after = candidate_widgets[widget_id]
        changes: dict[str, dict[str, Any]] = {}
        for field in ("type", "title", "query", "width", "height", "options"):
            if before.get(field) != after.get(field):
                changes[field] = {
                    "before": _json_safe(before.get(field)),
                    "after": _json_safe(after.get(field)),
                }
        if changes:
            changed.append({"widget_id": widget_id, "fields": list(changes), "changes": changes})
    return {
        "view_fields": view_fields,
        "widgets": {"added": added, "removed": removed, "changed": changed},
        "summary": {
            "view_fields_changed": len(view_fields),
            "widgets_added": len(added),
            "widgets_removed": len(removed),
            "widgets_changed": len(changed),
        },
    }


def _result_signature(snapshot: dict[str, Any]) -> str | None:
    if snapshot.get("error") or not snapshot.get("rows"):
        return None
    columns = snapshot.get("columns") or []
    values = [[row.get(column) for column in columns] for row in snapshot["rows"]]
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def _normalize_label(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _campaign_references(text: str, campaigns: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = _normalize_label(text)
    padded = f" {normalized} "
    matches: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for campaign in [
        *(campaigns.get("items") or []),
        *(campaigns.get("scope_items") or []),
    ]:
        if campaign.get("id"):
            by_id[str(campaign["id"])] = campaign
    for campaign in by_id.values():
        name = _normalize_label(campaign.get("name"))
        aliases = {name}
        # Only a name that literally says "campaign <n>" earns the short
        # "campaign n" / "cn" aliases. Harvesting EVERY digit in the name made
        # the gate unsatisfiable: "TEST e2e CLEAN" yielded "campaign 2" from the
        # 2 inside "e2e", and "…leaders <100 (v2)" yielded it too, so a widget
        # correctly titled "Campaign 2 — sent per day" was reported as referring
        # to four unrelated campaigns and could never be scoped to match.
        for number in _CAMPAIGN_NUMBER_RE.findall(name):
            aliases.update({f"campaign {number}", f"c{number}"})
        if any(
            alias and f" {alias} " in padded
            for alias in aliases
        ):
            matches.append(campaign)
    return matches


def _filter_values(item: dict[str, Any]) -> set[str]:
    raw = item.get("value")
    candidates = raw if isinstance(raw, list) else [raw]
    return {str(value) for value in candidates if value is not None}


def _workflow_filter_values(filters: list[dict[str, Any]]) -> set[str]:
    positive_domains: list[set[str]] = []
    excluded: set[str] = set()
    for item in filters:
        if item.get("field") != "workflow_id":
            continue
        if item.get("op") in {"eq", "in"}:
            positive_domains.append(_filter_values(item))
        elif item.get("op") in {"neq", "not_in"}:
            excluded.update(_filter_values(item))
    if not positive_domains:
        return set()
    values = set.intersection(*positive_domains)
    return values - excluded


def _view_workflow_filter_values(view: dict[str, Any]) -> set[str]:
    """Union positive workflow UUIDs for bounded, targeted RLS verification."""
    values: set[str] = set()
    for widget in view.get("layout") or []:
        if not isinstance(widget, dict):
            continue
        query = widget.get("query") or {}
        if query.get("entity") not in _CAMPAIGN_ENTITIES:
            continue
        for item in query.get("filters") or []:
            if item.get("field") == "workflow_id" and item.get("op") in {"eq", "in"}:
                values.update(_filter_values(item))
                if len(values) >= MAX_TARGETED_SCOPE_IDS:
                    return set(sorted(values)[:MAX_TARGETED_SCOPE_IDS])
    return values


def _exact_filter_values(filters: list[dict[str, Any]], field: str) -> set[str]:
    """Return the exact positive domain after simple negative constraints."""
    positive_domains: list[set[str]] = []
    excluded: set[str] = set()
    for item in filters:
        if item.get("field") != field:
            continue
        if item.get("op") in {"eq", "in"}:
            positive_domains.append(_filter_values(item))
        elif item.get("op") in {"neq", "not_in"}:
            excluded.update(_filter_values(item))
    if not positive_domains:
        return set()
    return set.intersection(*positive_domains) - excluded


def _claimed_send_status(text: str) -> str | None:
    """Infer a status only when the visible label makes a concrete claim.

    Explicit qualifiers win ("Failed sends" means failed). A bare "sends"
    retains Omni's product convention of sent messages, while labels that say
    outcomes/all/attempted deliberately aggregate multiple statuses.
    """
    explicit = [
        status for status, pattern in _SEND_STATUS_RE.items()
        if pattern.search(text)
    ]
    if len(explicit) == 1:
        return explicit[0]
    if explicit:
        return None
    if _SEND_WORD_RE.search(text) and not _ALL_OUTCOMES_RE.search(text):
        return "sent"
    return None


def _review_warnings(
    current: dict[str, Any],
    candidate: dict[str, Any],
    verification: dict[str, Any],
    annotations: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    campaigns = verification["campaigns"]
    observed_values: dict[str, list[str]] = campaigns.get("observed_values") or {}
    authoritative_values: dict[str, list[str]] = (
        campaigns.get("authoritative_values") or _authoritative_values()
    )
    snapshots = {item["widget_id"]: item for item in verification["widget_results"]}
    # A note describes the requested transition, often mentioning both old and
    # new semantics ("change Delivered to Sent"). The candidate's visible title
    # is the claim users will see, so only that title drives semantic gates.
    _ = current, annotations

    stat_signatures: dict[str, list[str]] = {}
    for raw_widget in candidate.get("layout") or []:
        widget_id = str(raw_widget.get("id") or "")
        snapshot = snapshots.get(widget_id) or {}
        query = raw_widget.get("query") or {}
        entity = str(query.get("entity") or "")
        filters = query.get("filters") or []
        candidate_title = str(raw_widget.get("title") or "")
        candidate_references = _campaign_references(candidate_title, campaigns)

        if entity in _CAMPAIGN_ENTITIES:
            scoped_values = _workflow_filter_values(filters)
            scoped = bool(scoped_values)
            known_campaign_ids = {
                str(campaign.get("id"))
                for campaign in [
                    *(campaigns.get("items") or []),
                    *(campaigns.get("scope_items") or []),
                ]
                if campaign.get("id")
            }
            unknown_campaign_ids = sorted(scoped_values - known_campaign_ids)
            if unknown_campaign_ids:
                warnings.append({
                    "code": "campaign_scope_unknown",
                    "severity": "error",
                    "widget_id": widget_id,
                    "message": (
                        "A targeted workspace-scoped lookup could not resolve these "
                        f"workflow_id values: {unknown_campaign_ids}."
                    ),
                    "workflow_ids": unknown_campaign_ids,
                })

            if query.get("metrics") and not scoped and campaigns.get("total", 0) > 1:
                specific = bool(
                    candidate_references or _CAMPAIGN_WORD_RE.search(candidate_title)
                )
                warnings.append({
                    "code": "campaign_reference_unfiltered" if specific else "campaign_scope_all",
                    "severity": "error" if specific else "warning",
                    "widget_id": widget_id,
                    "message": (
                        "This widget names a campaign but its query has no workflow_id filter; "
                        "the value spans every campaign."
                        if specific
                        else "This aggregate has no workflow_id filter and spans every campaign."
                    ),
                })

            referenced_ids = {
                str(campaign["id"])
                for campaign in candidate_references
            }
            if referenced_ids and scoped_values != referenced_ids:
                names = [
                    str(campaign.get("name") or campaign["id"])
                    for campaign in candidate_references
                ]
                missing_ids = sorted(referenced_ids - scoped_values)
                extra_ids = sorted(scoped_values - referenced_ids)
                warnings.append({
                    "code": "campaign_identity_mismatch",
                    "severity": "error",
                    "widget_id": widget_id,
                    "message": (
                        f"This widget visibly refers to {names}; its positive workflow_id "
                        "scope must match those authoritative campaign IDs exactly."
                    ),
                    "required_workflow_ids": sorted(referenced_ids),
                    "missing_workflow_ids": missing_ids,
                    "unexpected_workflow_ids": extra_ids,
                })
            if entity == "send_outcomes" and _DELIVERED_WORD_RE.search(
                candidate_title,
            ):
                warnings.append({
                    "code": "unsupported_delivery_claim",
                    "severity": "error",
                    "widget_id": widget_id,
                    "message": (
                        "omni_send_outcomes records queued, sent, failed, and skipped "
                        "outcomes; it does not prove downstream delivery. Rename this "
                        "metric to Sent or bind it to a real delivery-event projection."
                    ),
                })

            # Only an AGGREGATE claims a count. A rows table titled "Recent Send
            # Activity" that selects a status column per row states no total, so
            # demanding status='sent' there blocked an honest widget — and would
            # have forced it to hide the failures an operator most needs to see.
            claimed_status = (
                _claimed_send_status(candidate_title)
                if entity == "send_outcomes" and query.get("metrics")
                else None
            )
            if claimed_status is not None:
                status_values = _exact_filter_values(filters, "status")
                if status_values != {claimed_status}:
                    warnings.append({
                        "code": "send_metric_status_mismatch",
                        "severity": "error",
                        "widget_id": widget_id,
                        "message": (
                            f"This widget claims to count {claimed_status} send outcomes "
                            f"but is not filtered exactly to send_outcomes.status="
                            f"'{claimed_status}'."
                        ),
                        "required_status": claimed_status,
                    })

        for item in filters:
            if item.get("op") not in {"eq", "in"}:
                continue
            key = f"{entity}.{item.get('field')}"
            authoritative = authoritative_values.get(key)
            raw_values = item.get("value") if item.get("op") == "in" else [item.get("value")]
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            if authoritative:
                invalid = [str(value) for value in values if str(value) not in authoritative]
                if invalid:
                    warnings.append({
                        "code": "filter_value_invalid",
                        "severity": "error",
                        "widget_id": widget_id,
                        "message": (
                            f"Filter {key} uses invalid values {invalid}; allowed values are "
                            f"{authoritative}."
                        ),
                        "allowed_values": authoritative,
                    })
                    continue
            observed = observed_values.get(key)
            if not observed:
                continue
            missing = [str(value) for value in values if str(value) not in observed]
            if missing:
                warnings.append({
                    "code": "filter_value_unobserved",
                    "severity": "warning",
                    "widget_id": widget_id,
                    "message": (
                        f"Filter {key} uses {missing}; observed live values are {observed}. "
                        "Confirm the projection contract before applying."
                    ),
                    "observed_values": observed,
                })

        if snapshot.get("error"):
            warnings.append({
                "code": "candidate_query_failed",
                "severity": "error",
                "widget_id": widget_id,
                "message": snapshot["error"]["message"],
            })
        elif raw_widget.get("type") == "stat":
            signature = _result_signature(snapshot)
            if signature is not None:
                stat_signatures.setdefault(signature, []).append(widget_id)

    for widget_ids in stat_signatures.values():
        if len(widget_ids) < 2:
            continue
        campaign_named: list[str] = []
        for widget_id in widget_ids:
            title = str(next((
                widget.get("title")
                for widget in candidate.get("layout") or []
                if widget.get("id") == widget_id
            ), ""))
            if _CAMPAIGN_WORD_RE.search(title) or _campaign_references(title, campaigns):
                campaign_named.append(widget_id)
        if campaign_named:
            warnings.append({
                "code": "duplicate_campaign_stat_result",
                "severity": "warning",
                "widget_ids": widget_ids,
                "message": "Multiple campaign-labelled stat widgets return the same live rows; verify their workflow_id filters.",
            })
    return warnings


async def review_candidate_view(
    current: dict[str, Any],
    candidate: dict[str, Any],
    *,
    annotations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate and live-check a candidate without writing the view.

    ``ready_to_apply`` means every candidate query executed and no high-confidence
    semantic blocker was found. Lower-confidence warnings remain review evidence;
    legitimate all-campaign and zero-result views stay expressible.
    """
    validated = validate_candidate_view(candidate)
    async with acquire() as conn:
        verification = await _capture_with_budget(conn, validated)
    warnings = _review_warnings(current, validated, verification, annotations)
    ready = not any(item.get("severity") == "error" for item in warnings)
    return {
        "version": GROUNDING_VERSION,
        "candidate": validated,
        "diff": diff_views(current, validated),
        "verification": verification,
        "warnings": warnings,
        "warning_count": sum(1 for item in warnings if item.get("severity") == "warning"),
        "error_count": sum(1 for item in warnings if item.get("severity") == "error"),
        "ready_to_apply": ready,
    }


async def review_view_candidate(
    job_payload: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Broker-facing review contract for a completed ``view.author`` job.

    The queued payload already owns the frozen ``current_view`` and, once wired,
    its ``grounding`` from :func:`capture_view_grounding`.  Reuse that frozen
    evidence for before-values while executing the candidate against live
    projections now.  A payload created before grounding shipped falls back to a
    fresh current-view capture so old queued jobs fail safely, not mysteriously.
    """
    current = job_payload.get("current_view")
    if not isinstance(current, dict):
        raise ValueError("view.author job payload is missing current_view")
    annotations = job_payload.get("widget_annotations")
    if not isinstance(annotations, list):
        annotations = []

    before = job_payload.get("grounding") or job_payload.get("data_context")
    if not isinstance(before, dict) or not isinstance(before.get("widget_results"), list):
        before = await capture_view_grounding(current)
    reviewed = await review_candidate_view(current, candidate, annotations=annotations)
    after = reviewed["verification"]

    before_widgets = {
        str(item.get("widget_id")): item
        for item in before.get("widget_results") or []
        if isinstance(item, dict) and item.get("widget_id")
    }
    after_widgets = {
        str(item.get("widget_id")): item
        for item in after.get("widget_results") or []
        if isinstance(item, dict) and item.get("widget_id")
    }
    before_specs = {
        str(item.get("id")): item
        for item in current.get("layout") or []
        if isinstance(item, dict) and item.get("id")
    }
    after_specs = {
        str(item.get("id")): item
        for item in reviewed["candidate"].get("layout") or []
        if isinstance(item, dict) and item.get("id")
    }
    changed_ids = list(dict.fromkeys([
        *(reviewed["diff"]["widgets"]["added"] or []),
        *(reviewed["diff"]["widgets"]["removed"] or []),
        *[item["widget_id"] for item in reviewed["diff"]["widgets"]["changed"]],
    ]))
    changed_widgets = []
    for widget_id in changed_ids:
        before_spec = before_specs.get(widget_id) or {}
        after_spec = after_specs.get(widget_id) or {}
        changed_widgets.append({
            "widget_id": widget_id,
            "before_title": before_spec.get("title"),
            "after_title": after_spec.get("title"),
            "before_rows": (before_widgets.get(widget_id) or {}).get("rows") or [],
            "after_rows": (after_widgets.get(widget_id) or {}).get("rows") or [],
            "query_changed": before_spec.get("query") != after_spec.get("query"),
        })

    blocking = [item for item in reviewed["warnings"] if item.get("severity") == "error"]
    # Keep transport/execution validity distinct from semantic readiness.  A
    # campaign-labelled but unscoped query executed successfully: persist the
    # proposal and its review so the human can see the flaw, but refuse Apply.
    query_failures = [item for item in blocking if item.get("code") == "candidate_query_failed"]
    all_queries_valid = not query_failures
    return {
        "captured_at": after["captured_at"],
        "all_queries_valid": all_queries_valid,
        "ready_to_apply": reviewed["ready_to_apply"],
        "changed_widgets": changed_widgets,
        "warnings": [item for item in reviewed["warnings"] if item.get("severity") != "error"],
        "blocking_issues": blocking,
        # Rich evidence remains available for the review UI and audit trail.
        "candidate": reviewed["candidate"],
        "diff": reviewed["diff"],
        "verification": after,
    }
