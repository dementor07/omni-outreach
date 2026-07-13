"""DYNAMIC-001 — dynamic views: the interface-as-data surface.

  * GET  /views/widgets  — widget vocabulary + entity catalog (agent discovery,
                           the interface twin of GET /nodes)
  * POST /views/query    — run one constrained QuerySpec (what widgets bind to)
  * POST /views/generate — prompt → AI-designed view, validated + persisted
  * CRUD /views          — list/create/read/update/delete views

Static routes are declared BEFORE /{view_id} (the recorded projection-router
gotcha). Every layout write revalidates through validate_layout(), so a stored
view can never carry a query the runtime would refuse. Workspace isolation is
RLS on the request-scoped connection.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import acquire, fetch_all, fetch_one
from app.services.default_view import DEFAULT_LAYOUT, DEFAULT_VIEW_NAME
from app.services.view_architect import ViewArchitectError, edit_view, generate_view
from app.services.view_query import QuerySpec, QueryValidationError, build_query, entity_catalog
from app.services.view_widgets import ViewLayoutError, validate_layout, widget_manifests

router = APIRouter()


class ViewOut(BaseModel):
    id: UUID
    name: str
    description: str
    icon: str
    layout: list[dict[str, Any]]
    prompt: str | None
    created_by: str
    position: int
    updated_at: Any


class ViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=200)
    icon: str = Field("layout-dashboard", max_length=40)
    layout: list[dict[str, Any]] = Field(min_length=1)


class ViewPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=200)
    icon: str | None = Field(None, max_length=40)
    layout: list[dict[str, Any]] | None = None
    position: int | None = Field(None, ge=0)


class ViewGenerate(BaseModel):
    prompt: str = Field(min_length=8, max_length=2000)


class ViewEdit(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]


def _row_to_out(row: dict) -> ViewOut:
    layout = row.get("layout")
    if isinstance(layout, str):
        layout = json.loads(layout)
    return ViewOut(
        id=row["id"],
        name=row["name"],
        description=row.get("description") or "",
        icon=row.get("icon") or "layout-dashboard",
        layout=layout or [],
        prompt=row.get("prompt"),
        created_by=row.get("created_by") or "user",
        position=row.get("position") or 0,
        updated_at=row.get("updated_at"),
    )


# ── Static routes FIRST ──────────────────────────────────────────────────────


@router.get(
    "/widgets",
    summary="Widget vocabulary + entity catalog",
    description=(
        "The machine-readable interface vocabulary: every widget type a view can "
        "contain and every entity/field a widget query can bind to. Agents discover "
        "the interface primitives here the same way they discover campaign "
        "primitives on GET /nodes."
    ),
)
async def get_widget_catalog(_: AuthContext = Depends(get_current_workspace)) -> dict[str, Any]:
    return {"widgets": widget_manifests(), **entity_catalog()}


@router.get(
    "/default",
    response_model=ViewOut,
    summary="The workspace's home (Overview) view — seeded on first request",
    description=(
        "DYNAMIC-002: the home page is a stored view, not hardcoded React. Returns "
        "this workspace's default Overview view, lazily creating it from the "
        "canonical layout the first time it's asked for. The frontend renders this "
        "through the generic view renderer and falls back to the static page if "
        "this call fails — so seeding is zero-risk."
    ),
)
async def get_default_view(ctx: AuthContext = Depends(get_current_workspace)) -> ViewOut:
    # Fast path: an Overview already exists (RLS scopes the read to this
    # workspace, so filtering by name only is safe). The user may have edited or
    # renamed it — we key on the seed name only for the INITIAL create.
    existing = await fetch_one(
        "SELECT * FROM omni_views WHERE name = $1 ORDER BY created_at LIMIT 1",
        DEFAULT_VIEW_NAME,
    )
    if existing:
        return _row_to_out(dict(existing))

    # Seed once. Guard the check-then-insert against concurrent first-loads
    # (two tabs / two teammates) with a per-workspace advisory lock — the same
    # pattern CONTACT-CAP-002 used for a lazy-seed race — so we never mint a
    # duplicate Overview a later edit could silently miss. validate_layout()
    # guarantees the layout compiles; if the catalog ever drifts it raises and
    # the frontend shows the static page (zero-risk).
    widgets = validate_layout(DEFAULT_LAYOUT)
    async with acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                f"seed-default-view:{ctx.workspace_id}",
            )
            # Re-check inside the lock: the request that lost the race sees the
            # winner's row instead of inserting a second one.
            row = await conn.fetchrow(
                "SELECT * FROM omni_views WHERE name = $1 ORDER BY created_at LIMIT 1",
                DEFAULT_VIEW_NAME,
            )
            if row is None:
                row = await conn.fetchrow(
                    """
                    INSERT INTO omni_views (workspace_id, name, description, icon, layout, created_by)
                    VALUES ($1, $2, $3, $4, $5::jsonb, 'user')
                    RETURNING *
                    """,
                    ctx.workspace_id,
                    DEFAULT_VIEW_NAME,
                    "Your mission control — reshape it with the view architect.",
                    "layout-dashboard",
                    json.dumps([w.model_dump(mode="json") for w in widgets]),
                )
    return _row_to_out(dict(row))


@router.post(
    "/query",
    response_model=QueryResult,
    summary="Run one constrained widget query",
    description=(
        "Compile and run a QuerySpec against the workspace's projections. All "
        "identifiers are whitelisted, all values parameterized, and results are "
        "RLS-scoped to the caller's workspace."
    ),
)
async def run_view_query(spec: QuerySpec, _: AuthContext = Depends(get_current_workspace)) -> QueryResult:
    try:
        built = build_query(spec)
    except QueryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    rows = await fetch_all(built.sql, *built.params)
    return QueryResult(
        columns=list(built.columns),
        rows=[{k: v for k, v in dict(r).items()} for r in rows],
    )


@router.post(
    "/generate",
    response_model=ViewOut,
    status_code=201,
    summary="Generate a view from a plain-language prompt",
    description=(
        "The view architect: describe the screen you want ('a reply-triage board "
        "with hot leads on the right') and the AI composes it from the widget "
        "vocabulary, validated against the same rules as a hand-built view, then "
        "saved. Requires an anthropic connection."
    ),
)
async def generate_view_from_prompt(
    body: ViewGenerate, ctx: AuthContext = Depends(get_current_workspace)
) -> ViewOut:
    try:
        view = await generate_view(ctx.workspace_id, body.prompt)
    except ViewArchitectError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    row = await fetch_one(
        """
        INSERT INTO omni_views (workspace_id, name, description, icon, layout, prompt, created_by)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'ai')
        RETURNING *
        """,
        ctx.workspace_id,
        view["name"],
        view["description"],
        view["icon"],
        json.dumps(view["layout"]),
        body.prompt,
    )
    return _row_to_out(dict(row))


@router.post(
    "/{view_id}/edit",
    response_model=ViewOut,
    summary="Edit a view with a plain-language instruction",
    description=(
        "DYNAMIC-002: reshape an existing view by describing the change — 'add a "
        "failures-by-provider chart', 'make the trend weekly', 'drop the tasks "
        "widget'. The view architect gets the current layout + the instruction and "
        "returns the full revised layout, re-validated through the same whitelist, "
        "then saved. This is the core dynamic interaction (and the call an external "
        "agent / the MCP server makes). Requires an anthropic connection."
    ),
)
async def edit_view_with_prompt(
    view_id: UUID, body: ViewEdit, ctx: AuthContext = Depends(get_current_workspace)
) -> ViewOut:
    current = await fetch_one("SELECT * FROM omni_views WHERE id=$1", view_id)
    if not current:
        raise HTTPException(status_code=404, detail="view not found")
    current_view = _row_to_out(dict(current))
    try:
        revised = await edit_view(
            ctx.workspace_id,
            {
                "name": current_view.name,
                "description": current_view.description,
                "icon": current_view.icon,
                "layout": current_view.layout,
            },
            body.instruction,
        )
    except ViewArchitectError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    row = await fetch_one(
        """
        UPDATE omni_views
        SET name=$1, description=$2, icon=$3, layout=$4::jsonb, updated_at=NOW()
        WHERE id=$5
        RETURNING *
        """,
        revised["name"],
        revised["description"],
        revised["icon"],
        json.dumps(revised["layout"]),
        view_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="view not found")
    return _row_to_out(dict(row))


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ViewOut], summary="List this workspace's dynamic views")
async def list_views(_: AuthContext = Depends(get_current_workspace)) -> list[ViewOut]:
    rows = await fetch_all("SELECT * FROM omni_views ORDER BY position, updated_at DESC")
    return [_row_to_out(dict(r)) for r in rows]


@router.post("", response_model=ViewOut, status_code=201, summary="Create a view")
async def create_view(body: ViewCreate, ctx: AuthContext = Depends(get_current_workspace)) -> ViewOut:
    try:
        widgets = validate_layout(body.layout)
    except ViewLayoutError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    row = await fetch_one(
        """
        INSERT INTO omni_views (workspace_id, name, description, icon, layout, created_by)
        VALUES ($1, $2, $3, $4, $5::jsonb, 'user')
        RETURNING *
        """,
        ctx.workspace_id,
        body.name,
        body.description,
        body.icon,
        json.dumps([w.model_dump(mode="json") for w in widgets]),
    )
    return _row_to_out(dict(row))


@router.get("/{view_id}", response_model=ViewOut, summary="Fetch one view")
async def get_view(view_id: UUID, _: AuthContext = Depends(get_current_workspace)) -> ViewOut:
    row = await fetch_one("SELECT * FROM omni_views WHERE id=$1", view_id)
    if not row:
        raise HTTPException(status_code=404, detail="view not found")
    return _row_to_out(dict(row))


@router.patch("/{view_id}", response_model=ViewOut, summary="Update a view")
async def update_view(
    view_id: UUID, body: ViewPatch, _: AuthContext = Depends(get_current_workspace)
) -> ViewOut:
    sets: list[str] = []
    params: list[Any] = []
    if body.name is not None:
        params.append(body.name)
        sets.append(f"name=${len(params)}")
    if body.description is not None:
        params.append(body.description)
        sets.append(f"description=${len(params)}")
    if body.icon is not None:
        params.append(body.icon)
        sets.append(f"icon=${len(params)}")
    if body.position is not None:
        params.append(body.position)
        sets.append(f"position=${len(params)}")
    if body.layout is not None:
        try:
            widgets = validate_layout(body.layout)
        except ViewLayoutError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        params.append(json.dumps([w.model_dump(mode="json") for w in widgets]))
        sets.append(f"layout=${len(params)}::jsonb")
    if not sets:
        raise HTTPException(status_code=422, detail="nothing to update")
    params.append(view_id)
    row = await fetch_one(
        f"UPDATE omni_views SET {', '.join(sets)}, updated_at=NOW() WHERE id=${len(params)} RETURNING *",
        *params,
    )
    if not row:
        raise HTTPException(status_code=404, detail="view not found")
    return _row_to_out(dict(row))


@router.delete("/{view_id}", status_code=204, summary="Delete a view")
async def delete_view(view_id: UUID, _: AuthContext = Depends(get_current_workspace)) -> None:
    row = await fetch_one("DELETE FROM omni_views WHERE id=$1 RETURNING id", view_id)
    if not row:
        raise HTTPException(status_code=404, detail="view not found")
