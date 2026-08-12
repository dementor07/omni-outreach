"""DYNAMIC-001 — the constrained query surface dynamic views bind to.

Dynamic views (omni_views) are data, and their widgets need data bindings. The
dangerous shortcut is user SQL; this module is the safe alternative: a small,
schema-validated query spec (entity + filters + group-bys + metrics) compiled
to parameterized SQL against the existing projections.

Safety model (the whole point of this file):
  * Every identifier (table, column, alias, op, bucket) resolves through a
    hardcoded whitelist — user strings are NEVER interpolated as SQL. Unknown
    names raise QueryValidationError.
  * Every value travels as a bind parameter ($1, $2, …), coerced to the
    column's Python type first so asyncpg never sees a mistyped literal.
  * Workspace isolation is RLS: the router runs the built SQL on a
    request-scoped connection (app.workspace_id armed), so no ws WHERE here.

Pure module: no DB, no network — build_query() returns (sql, params) and the
router executes it. Tests target this file directly.
"""

from __future__ import annotations

import re
import uuid as uuid_mod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class QueryValidationError(ValueError):
    """A spec referenced an unknown entity/field/op or carried a bad value."""


# ── Entity catalog ───────────────────────────────────────────────────────────
# Column type tags drive value coercion; only whitelisted columns are queryable.

@dataclass(frozen=True)
class EntityDef:
    table: str
    columns: Mapping[str, str]  # column -> type tag
    default_columns: tuple[str, ...]
    time_field: str
    default_sort: str


_TS = "timestamp"

ENTITIES: dict[str, EntityDef] = {
    "contacts": EntityDef(
        table="omni_contacts",
        columns={
            "id": "uuid", "email": "text", "first_name": "text", "last_name": "text",
            "company": "text", "headline": "text", "linkedin_url": "text", "phone": "text",
            "source": "text", "created_at": _TS, "updated_at": _TS,
        },
        default_columns=("first_name", "last_name", "email", "company", "headline", "created_at"),
        time_field="created_at",
        default_sort="updated_at",
    ),
    "companies": EntityDef(
        table="omni_companies",
        columns={
            "id": "uuid", "name": "text", "domain": "text", "industry": "text",
            "size": "text", "created_at": _TS, "updated_at": _TS,
        },
        default_columns=("name", "domain", "industry", "size", "created_at"),
        time_field="created_at",
        default_sort="updated_at",
    ),
    "leads": EntityDef(
        table="omni_leads",
        columns={
            "id": "uuid", "contact_id": "uuid", "workflow_id": "uuid",
            "current_node_id": "uuid", "status": "text", "created_at": _TS, "updated_at": _TS,
        },
        default_columns=("id", "workflow_id", "status", "created_at"),
        time_field="created_at",
        default_sort="updated_at",
    ),
    "deals": EntityDef(
        table="omni_deals",
        columns={
            "id": "uuid", "name": "text", "stage": "text", "value": "numeric",
            "currency": "text", "contact_id": "uuid", "company_id": "uuid",
            "close_date": "date", "created_at": _TS, "updated_at": _TS,
        },
        default_columns=("name", "stage", "value", "currency", "close_date"),
        time_field="created_at",
        default_sort="updated_at",
    ),
    "tasks": EntityDef(
        table="omni_tasks",
        columns={
            "id": "uuid", "contact_id": "uuid", "title": "text", "due_date": "date",
            "priority": "text", "status": "text", "created_at": _TS, "updated_at": _TS,
        },
        default_columns=("title", "status", "priority", "due_date"),
        time_field="created_at",
        default_sort="created_at",
    ),
    "messages": EntityDef(
        table="omni_messages",
        columns={
            "id": "uuid", "contact_id": "uuid", "channel": "text", "direction": "text",
            "subject": "text", "body": "text", "classification": "text",
            "confidence": "numeric", "occurred_at": _TS,
        },
        default_columns=("channel", "direction", "subject", "classification", "occurred_at"),
        time_field="occurred_at",
        default_sort="occurred_at",
    ),
    "campaigns": EntityDef(
        table="omni_workflows",
        columns={
            "id": "uuid", "name": "text", "status": "text", "timezone": "text",
            "created_at": _TS, "updated_at": _TS,
        },
        default_columns=("name", "status", "created_at"),
        time_field="created_at",
        default_sort="updated_at",
    ),
    "send_outcomes": EntityDef(
        table="omni_send_outcomes",
        columns={
            "id": "uuid", "lead_id": "uuid", "contact_id": "uuid", "workflow_id": "uuid",
            "channel": "text", "mode": "text", "status": "text", "provider": "text",
            "error_code": "text", "occurred_at": _TS,
        },
        default_columns=("channel", "status", "provider", "error_code", "occurred_at"),
        time_field="occurred_at",
        default_sort="occurred_at",
    ),
}

_NUMERIC_TAGS = frozenset({"numeric"})
_ALIAS_RE = re.compile(r"[a-z_][a-z0-9_]{0,30}\Z")

FilterOp = Literal[
    "eq", "neq", "gt", "gte", "lt", "lte", "contains", "in", "not_in", "is_null", "not_null"
]
_VALUELESS_OPS = frozenset({"is_null", "not_null"})
_LIST_OPS = frozenset({"in", "not_in"})


# Bound the size of a single filter value so one request can't force Postgres to
# evaluate a multi-megabyte ILIKE pattern or a huge ANY() array (DoS lever — the
# per-filter value was previously unbounded even though filters/select/limit were
# all capped). List ops are capped by count; scalar text values by length.
_MAX_LIST_VALUES = 200
_MAX_VALUE_LEN = 500


class QueryFilter(BaseModel):
    field: str = Field(max_length=64)
    op: FilterOp = "eq"
    value: Any = None

    @model_validator(mode="after")
    def _bound_value(self) -> QueryFilter:
        if self.op in _VALUELESS_OPS:
            return self
        if self.value is None:
            raise ValueError(f"op {self.op!r} on field {self.field!r} requires a value")
        if self.op in _LIST_OPS:
            values = self.value if isinstance(self.value, list) else [self.value]
            if len(values) > _MAX_LIST_VALUES:
                raise ValueError(f"'{self.op}' list is capped at {_MAX_LIST_VALUES} values")
            for v in values:
                if isinstance(v, str) and len(v) > _MAX_VALUE_LEN:
                    raise ValueError(f"filter value exceeds {_MAX_VALUE_LEN} chars")
        elif isinstance(self.value, str) and len(self.value) > _MAX_VALUE_LEN:
            raise ValueError(f"filter value exceeds {_MAX_VALUE_LEN} chars")
        return self


class QueryMetric(BaseModel):
    fn: Literal["count", "count_distinct", "sum", "avg", "min", "max"] = "count"
    field: str | None = Field(None, max_length=64)
    alias: str | None = Field(None, max_length=32)


class QuerySort(BaseModel):
    field: str = Field(max_length=64)
    dir: Literal["asc", "desc"] = "desc"


class QuerySpec(BaseModel):
    entity: str = Field(max_length=64)
    filters: list[QueryFilter] = Field(default_factory=list, max_length=12)
    select: list[str] = Field(default_factory=list, max_length=16)
    group_by: list[str] = Field(default_factory=list, max_length=3)
    metrics: list[QueryMetric] = Field(default_factory=list, max_length=6)
    time_bucket: Literal["day", "week", "month"] | None = None
    sort: list[QuerySort] = Field(default_factory=list, max_length=3)
    limit: int = Field(50, ge=1, le=500)


@dataclass(frozen=True)
class BuiltQuery:
    sql: str
    params: tuple[Any, ...]
    columns: tuple[str, ...]


# ── Value coercion (mistyped literals fail HERE, not inside asyncpg) ─────────

def _coerce(value: Any, tag: str, field: str) -> Any:
    try:
        if tag == "uuid":
            return uuid_mod.UUID(str(value))
        if tag == "numeric":
            return float(value)
        if tag == "date":
            return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value))
        if tag == _TS:
            if isinstance(value, datetime):
                return value
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return str(value)
    except (ValueError, TypeError) as exc:
        raise QueryValidationError(f"filter value {value!r} is not a valid {tag} for field {field!r}") from exc


def _entity(spec: QuerySpec) -> EntityDef:
    entity = ENTITIES.get(spec.entity)
    if not entity:
        raise QueryValidationError(f"unknown entity {spec.entity!r}; one of {sorted(ENTITIES)}")
    return entity


def _column(entity: EntityDef, name: str, entity_name: str) -> str:
    if name not in entity.columns:
        raise QueryValidationError(f"unknown field {name!r} on entity {entity_name!r}")
    return name


def _where(spec: QuerySpec, entity: EntityDef, params: list[Any]) -> str:
    clauses: list[str] = []
    for f in spec.filters:
        col = _column(entity, f.field, spec.entity)
        tag = entity.columns[col]
        if f.op in _VALUELESS_OPS:
            clauses.append(f"{col} IS NULL" if f.op == "is_null" else f"{col} IS NOT NULL")
            continue
        if f.op == "contains":
            if tag != "text":
                raise QueryValidationError(f"'contains' only applies to text fields, not {col!r}")
            params.append(f"%{f.value}%")
            clauses.append(f"{col} ILIKE ${len(params)}")
            continue
        if f.op in _LIST_OPS:
            raw = f.value if isinstance(f.value, list) else [f.value]
            if not raw:
                raise QueryValidationError(f"'{f.op}' on {col!r} needs a non-empty list value")
            params.append([_coerce(v, tag, col) for v in raw])
            comparator = "= ANY" if f.op == "in" else "<> ALL"
            clauses.append(f"{col} {comparator}(${len(params)})")
            continue
        op_sql = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[f.op]
        params.append(_coerce(f.value, tag, col))
        clauses.append(f"{col} {op_sql} ${len(params)}")
    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


def _metric_expr(entity: EntityDef, m: QueryMetric, entity_name: str) -> tuple[str, str]:
    """Return (sql_expr, alias). Aliases are whitelisted-shape, never raw user SQL."""
    if m.fn == "count" and not m.field:
        expr = "COUNT(*)"
        alias = m.alias or "count"
    else:
        if not m.field:
            raise QueryValidationError(f"metric {m.fn!r} requires a field")
        col = _column(entity, m.field, entity_name)
        if m.fn in {"sum", "avg"} and entity.columns[col] not in _NUMERIC_TAGS:
            raise QueryValidationError(f"metric {m.fn!r} needs a numeric field, {col!r} is {entity.columns[col]}")
        fn_sql = "COUNT(DISTINCT {})" if m.fn == "count_distinct" else m.fn.upper() + "({})"
        expr = fn_sql.format(col)
        alias = m.alias or f"{m.fn}_{col}"
    if not _ALIAS_RE.fullmatch(alias):
        raise QueryValidationError(f"metric alias {alias!r} must match {_ALIAS_RE.pattern}")
    return expr, alias


def _build_aggregate(spec: QuerySpec, entity: EntityDef, params: list[Any], where: str) -> BuiltQuery:
    select_parts: list[str] = []
    group_parts: list[str] = []
    out_columns: list[str] = []
    sortable: set[str] = set()

    if spec.time_bucket:
        select_parts.append(f"date_trunc('{spec.time_bucket}', {entity.time_field}) AS bucket")
        group_parts.append("1")
        out_columns.append("bucket")
        sortable.add("bucket")
    for g in spec.group_by:
        col = _column(entity, g, spec.entity)
        select_parts.append(col)
        group_parts.append(col)
        out_columns.append(col)
        sortable.add(col)

    metrics = spec.metrics or [QueryMetric()]
    # Seed the taken-names set with the bucket/group-by output columns, not just
    # prior metric aliases: a metric alias equal to a group field (e.g.
    # group_by=['source'] + metric alias 'source') produces two same-named SELECT
    # columns, and the row-dict in the router silently collapses them — the widget
    # then renders wrong/missing data with no error. Reject the collision up front.
    seen_aliases: set[str] = set(out_columns)
    for m in metrics:
        expr, alias = _metric_expr(entity, m, spec.entity)
        if alias in seen_aliases:
            raise QueryValidationError(f"output column name {alias!r} collides with a group field or another metric")
        seen_aliases.add(alias)
        select_parts.append(f"{expr} AS {alias}")
        out_columns.append(alias)
        sortable.add(alias)

    order = ""
    if spec.sort:
        parts = []
        for s in spec.sort:
            if s.field not in sortable:
                raise QueryValidationError(f"sort field {s.field!r} must be a group field or metric alias")
            parts.append(f"{s.field} {'ASC' if s.dir == 'asc' else 'DESC'}")
        order = f" ORDER BY {', '.join(parts)}"
    elif spec.time_bucket:
        order = " ORDER BY bucket ASC"
    elif group_parts:
        # Grouped with no explicit sort: order by the first metric, biggest first
        # (out_columns = group columns then metric aliases, so index len(group_parts)).
        order = f" ORDER BY {out_columns[len(group_parts)]} DESC"

    group = f" GROUP BY {', '.join(group_parts)}" if group_parts else ""
    sql = (
        f"SELECT {', '.join(select_parts)} FROM {entity.table}{where}{group}{order} LIMIT {spec.limit}"
    )
    return BuiltQuery(sql=sql, params=tuple(params), columns=tuple(out_columns))


def _build_rows(spec: QuerySpec, entity: EntityDef, params: list[Any], where: str) -> BuiltQuery:
    columns = [_column(entity, c, spec.entity) for c in spec.select] or list(entity.default_columns)
    order_parts = []
    for s in spec.sort:
        order_parts.append(f"{_column(entity, s.field, spec.entity)} {'ASC' if s.dir == 'asc' else 'DESC'}")
    order = ", ".join(order_parts) or f"{entity.default_sort} DESC"
    sql = f"SELECT {', '.join(columns)} FROM {entity.table}{where} ORDER BY {order} LIMIT {spec.limit}"
    return BuiltQuery(sql=sql, params=tuple(params), columns=tuple(columns))


def build_query(spec: QuerySpec) -> BuiltQuery:
    """Compile a validated spec to (sql, params, columns). Raises QueryValidationError."""
    entity = _entity(spec)
    params: list[Any] = []
    where = _where(spec, entity, params)
    if spec.metrics or spec.group_by or spec.time_bucket:
        return _build_aggregate(spec, entity, params, where)
    return _build_rows(spec, entity, params, where)


def entity_catalog() -> dict[str, Any]:
    """Machine-readable catalog (served on /views/widgets and fed to the view
    architect prompt) — the discovery contract for interface-authoring agents,
    mirroring what GET /nodes does for campaign-authoring agents."""
    return {
        "entities": {
            name: {
                "fields": dict(e.columns),
                "time_field": e.time_field,
                "default_columns": list(e.default_columns),
            }
            for name, e in ENTITIES.items()
        },
        "filter_ops": ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "in", "not_in", "is_null", "not_null"],
        "metric_fns": ["count", "count_distinct", "sum", "avg", "min", "max"],
        "time_buckets": ["day", "week", "month"],
    }
