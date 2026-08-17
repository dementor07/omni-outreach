"""DYNAMIC-001 — dynamic views: the interface-as-data surface.

  * GET  /views/widgets  — widget vocabulary + entity catalog (agent discovery,
                           the interface twin of GET /nodes)
  * POST /views/query    — run one constrained QuerySpec (what widgets bind to)
  * POST /views/generate — prompt → AI-designed new view, validated + persisted
  * POST /views/{id}/proposals — existing-view edit → grounded proposal/review
  * CRUD /views          — list/create/read/update/delete views

Static routes are declared BEFORE /{view_id} (the recorded projection-router
gotcha). Every layout write revalidates through validate_layout(), so a stored
view can never carry a query the runtime would refuse. Workspace isolation is
RLS on the request-scoped connection.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import acquire, fetch_all, fetch_one
from app.routers.agent_harness import AgentJobOut
from app.services import agent_harness
from app.services.ai_authoring import list_authoring_connections
from app.services.default_view import DEFAULT_LAYOUT, DEFAULT_VIEW_NAME
from app.services.view_architect import (
    ViewArchitectError,
    edit_view,
    generate_view,
    validate_annotation_targets,
    validate_candidate_view,
)
from app.services.view_grounding import capture_view_grounding
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


class ViewAnnotation(BaseModel):
    widget_id: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=1000)


class ViewCandidate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=200)
    icon: str = Field("layout-dashboard", max_length=40)
    layout: list[dict[str, Any]] = Field(min_length=1, max_length=12)


class ViewCandidateOut(BaseModel):
    name: str
    description: str
    icon: str
    layout: list[dict[str, Any]]


class ViewAuthoringConnectionOut(BaseModel):
    id: UUID
    provider: str
    name: str
    adapter: str
    default_model: str


class ViewAuthorRequest(BaseModel):
    source: Literal["connection", "harness", "import"]
    annotations: list[ViewAnnotation] = Field(default_factory=list, max_length=50)
    harness_job_id: UUID | None = None
    proposal_id: UUID | None = None


class ViewProposalCreate(BaseModel):
    source: Literal["connection", "harness", "import"]
    instruction: str = Field("", max_length=2000)
    annotations: list[ViewAnnotation] = Field(default_factory=list, max_length=50)
    connection_id: UUID | None = None
    model: str | None = Field(None, max_length=160)
    harness_id: str | None = Field(
        None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    candidate_view: dict[str, Any] | None = None


class ViewHarnessJobCreate(BaseModel):
    instruction: str = Field("", max_length=2000)
    annotations: list[ViewAnnotation] = Field(default_factory=list, max_length=50)
    harness_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


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
    "/authoring/connections",
    response_model=list[ViewAuthoringConnectionOut],
    summary="Connected AI providers that can author a validated view",
)
async def get_authoring_connections(
    ctx: AuthContext = Depends(get_current_workspace),
) -> list[ViewAuthoringConnectionOut]:
    rows = await list_authoring_connections(ctx.workspace_id)
    return [ViewAuthoringConnectionOut.model_validate(row) for row in rows]


@router.post(
    "/validate",
    response_model=ViewCandidateOut,
    summary="Validate an external agent-harness ViewSpec without writing it",
)
async def validate_view_candidate(
    body: ViewCandidate,
    _: AuthContext = Depends(get_current_workspace),
) -> ViewCandidateOut:
    try:
        candidate = validate_candidate_view(body.model_dump(mode="json"))
    except ViewLayoutError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ViewCandidateOut.model_validate(candidate)


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


async def _load_view_payload(view_id: UUID) -> tuple[ViewOut, dict[str, Any]]:
    current = await fetch_one("SELECT * FROM omni_views WHERE id=$1", view_id)
    if not current:
        raise HTTPException(status_code=404, detail="view not found")
    view = _row_to_out(dict(current))
    return view, {
        "name": view.name,
        "description": view.description,
        "icon": view.icon,
        "layout": view.layout,
    }


async def _apply_proposal_revision(
    view_id: UUID,
    proposal_id: UUID,
    revised: dict[str, Any],
    *,
    expected_version: Any,
) -> ViewOut:
    """Atomically apply a reviewed proposal and mark that exact proposal used."""
    async with acquire() as conn:
        applied = await conn.fetchrow(
            """
            UPDATE omni_agent_jobs
            SET applied_at=NOW(), updated_at=NOW()
            WHERE id=$1 AND kind='view.author' AND target_type='view'
              AND target_id=$2 AND target_version=$3
              AND status='succeeded' AND applied_at IS NULL
              AND COALESCE((review->>'ready_to_apply')::boolean, false)
            RETURNING id
            """,
            proposal_id,
            view_id,
            expected_version,
        )
        if applied is None:
            raise HTTPException(
                status_code=409,
                detail="this proposal is stale, already applied, or has unresolved review issues",
            )
        row = await conn.fetchrow(
            """
            UPDATE omni_views
            SET name=$1, description=$2, icon=$3, layout=$4::jsonb, updated_at=NOW()
            WHERE id=$5 AND updated_at=$6
            RETURNING *
            """,
            revised["name"],
            revised["description"],
            revised["icon"],
            json.dumps(revised["layout"]),
            view_id,
            expected_version,
        )
        if row is None:
            raise HTTPException(
                status_code=409,
                detail="this view changed after the proposal was created; create a fresh proposal",
            )
    return _row_to_out(dict(row))


async def _create_view_proposal(
    view_id: UUID,
    body: ViewProposalCreate,
    ctx: AuthContext,
) -> AgentJobOut:
    current_view, current_payload = await _load_view_payload(view_id)
    annotations = [annotation.model_dump(mode="json") for annotation in body.annotations]
    try:
        validate_annotation_targets(current_payload, annotations)
    except ViewArchitectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.source != "import" and not body.instruction.strip() and not annotations:
        raise HTTPException(
            status_code=422,
            detail="add a view instruction or at least one widget annotation",
        )
    request_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "source": body.source,
                "target_version": str(current_view.updated_at),
                "instruction": body.instruction.strip(),
                "annotations": annotations,
                "harness_id": body.harness_id,
                "connection_id": str(body.connection_id) if body.connection_id else None,
                "model": body.model,
                "candidate_view": body.candidate_view,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    grounding = await capture_view_grounding(current_payload)
    payload = {
        "task": (
            "Return one complete revised ViewSpec JSON object. Preserve everything "
            "that was not requested, including stable widget IDs."
        ),
        "current_view": current_payload,
        "whole_view_instruction": body.instruction.strip(),
        "widget_annotations": annotations,
        "grounding": grounding,
        "grounding_contract": [
            "Treat captured campaign IDs and widget query results as authoritative for this workspace.",
            "A campaign-labelled leads/send-outcomes widget must filter workflow_id to that exact campaign.",
            "A sent-message count must also filter send_outcomes.status to exactly 'sent'.",
            "Never label send_outcomes as delivered; this projection does not contain delivery receipts.",
            "Do not evade a requested correction by renaming a campaign widget to a global metric.",
            "Preserve unrequested widget semantics and stable widget IDs.",
        ],
        "widget_catalog": {"widgets": widget_manifests(), **entity_catalog()},
        "output_contract": {
            "name": "1-80 characters",
            "description": "0-200 characters",
            "icon": "a catalogued icon or layout-dashboard",
            "layout": "1-12 validated widget objects with stable IDs where preserved",
        },
        "safety": [
            "Return data only; do not call campaign, send, or integration endpoints.",
            "Do not request or include credentials.",
            "Omni will validate the candidate and require a human to apply it.",
        ],
        "authoring_origin": body.source,
        "request_fingerprint": request_fingerprint,
    }
    try:
        if body.source == "harness":
            if not body.harness_id:
                raise ViewArchitectError("choose a currently polling agent harness")
            row = await agent_harness.create_job(
                workspace_id=ctx.workspace_id,
                kind="view.author",
                target_type="view",
                target_id=view_id,
                target_version=current_view.updated_at,
                payload=payload,
                created_by=ctx.user_id,
                requested_harness_id=body.harness_id,
                origin="harness",
            )
        else:
            if body.source == "connection":
                if body.connection_id is None:
                    raise ViewArchitectError("choose a connected AI provider")
                revised = await edit_view(
                    ctx.workspace_id,
                    current_payload,
                    body.instruction,
                    annotations=annotations,
                    connection_id=body.connection_id,
                    model=body.model,
                    grounding=grounding,
                )
            else:
                if body.candidate_view is None:
                    raise ViewArchitectError("paste a complete ViewSpec to review")
                revised = validate_candidate_view(body.candidate_view)
            row = await agent_harness.create_completed_job(
                workspace_id=ctx.workspace_id,
                kind="view.author",
                target_type="view",
                target_id=view_id,
                target_version=current_view.updated_at,
                payload=payload,
                result=revised,
                created_by=ctx.user_id,
                origin=body.source,
            )
    except (ViewArchitectError, ViewLayoutError, agent_harness.AgentHarnessError) as exc:
        status_code = (
            409 if isinstance(exc, agent_harness.AgentJobConflictError) else 422
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return AgentJobOut.model_validate(row)


@router.post(
    "/{view_id}/proposals",
    response_model=AgentJobOut,
    status_code=202,
    summary="Create one grounded, executable view proposal for review",
)
async def create_view_proposal(
    view_id: UUID,
    body: ViewProposalCreate,
    ctx: AuthContext = Depends(get_current_workspace),
) -> AgentJobOut:
    return await _create_view_proposal(view_id, body, ctx)


@router.post(
    "/{view_id}/harness-jobs",
    response_model=AgentJobOut,
    status_code=202,
    summary="Compatibility alias for queueing a grounded harness proposal",
)
async def create_view_harness_job(
    view_id: UUID,
    body: ViewHarnessJobCreate,
    ctx: AuthContext = Depends(get_current_workspace),
) -> AgentJobOut:
    return await _create_view_proposal(
        view_id,
        ViewProposalCreate(
            source="harness",
            instruction=body.instruction,
            annotations=body.annotations,
            harness_id=body.harness_id,
        ),
        ctx,
    )


@router.get(
    "/{view_id}/grounding",
    response_model=dict[str, Any],
    summary="Capture live RLS-scoped evidence for manual view authoring",
)
async def get_view_grounding(
    view_id: UUID,
    _: AuthContext = Depends(get_current_workspace),
) -> dict[str, Any]:
    _, current_payload = await _load_view_payload(view_id)
    return await capture_view_grounding(current_payload)


@router.get(
    "/{view_id}/open-proposal",
    response_model=AgentJobOut | None,
    summary="Recover this view's one durable unapplied proposal",
)
async def get_open_view_proposal(
    view_id: UUID,
    _: AuthContext = Depends(get_current_workspace),
) -> AgentJobOut | None:
    # Resolve the view under RLS first so a random UUID cannot become a target
    # existence oracle, then query the target directly rather than scanning a
    # bounded recent-job history.
    await _load_view_payload(view_id)
    row = await agent_harness.get_open_job_for_target(
        kind="view.author",
        target_type="view",
        target_id=view_id,
    )
    return AgentJobOut.model_validate(row) if row is not None else None


@router.post(
    "/{view_id}/author",
    response_model=ViewOut,
    summary="Apply a view revision from an explicit connected API or agent harness",
)
async def author_view(
    view_id: UUID,
    body: ViewAuthorRequest,
    ctx: AuthContext = Depends(get_current_workspace),
) -> ViewOut:
    current_view, _ = await _load_view_payload(view_id)
    annotations = [annotation.model_dump(mode="json") for annotation in body.annotations]
    proposal_id = body.proposal_id or body.harness_job_id
    try:
        if proposal_id is None:
            raise ViewArchitectError("create and review a proposal before applying a view change")
        if annotations:
            raise ViewArchitectError(
                "a proposal is frozen at creation; create a new proposal for changed annotations"
            )
        job = await agent_harness.get_job(proposal_id)
        if job is None or job["kind"] != "view.author" or job["target_id"] != view_id:
            raise ViewArchitectError("the proposal does not belong to this view")
        if (job.get("origin") or "harness") != body.source:
            raise ViewArchitectError("the proposal origin does not match the requested apply source")
        if job["status"] != "succeeded" or not isinstance(job.get("result"), dict):
            raise ViewArchitectError("the proposal has not produced a validated ViewSpec")
        if job.get("target_version") != current_view.updated_at:
            raise HTTPException(
                status_code=409,
                detail="this view changed after the proposal was created; create a fresh proposal",
            )
        revised = validate_candidate_view(job["result"])
        stored_review = job.get("review") or {}
        if not stored_review.get("ready_to_apply", False):
            issues = stored_review.get("blocking_issues") or [
                {"message": "proposal review is incomplete"}
            ]
            detail = "; ".join(str(issue.get("message", issue)) for issue in issues[:4])
            raise ViewArchitectError(detail)
        fresh_review = await agent_harness.review_result(
            str(job["kind"]), job.get("payload") or {}, revised
        )
        if not fresh_review.get("ready_to_apply", False):
            issues = fresh_review.get("blocking_issues") or [
                {"message": "live query verification failed"}
            ]
            detail = "; ".join(str(issue.get("message", issue)) for issue in issues[:4])
            raise ViewArchitectError(detail)
    except (ViewArchitectError, ViewLayoutError, agent_harness.AgentHarnessError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _apply_proposal_revision(
        view_id,
        proposal_id,
        revised,
        expected_version=current_view.updated_at,
    )


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
