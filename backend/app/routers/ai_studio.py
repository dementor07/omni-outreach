"""AI Studio — the surface behind Omni's AI/CRM features.

  GET  /ai/scores            lead scores (for CRM row badges + the Leads board)
  GET  /ai/scores/{lead_id}  one lead's latest score + reasons
  GET  /ai/jobs              AI run log (score / compose / enrich / classify)
  POST /ai/jobs              kick an AI job — publishes the node's queued event

Like everything else in v2, AI results are projections: a job publishes an
``ai.<kind>.queued`` event, the muscle runs the model and publishes
``ai.<kind>.completed`` / ``.failed``, and the projector materialises both
``omni_ai_jobs`` (run log) and ``omni_lead_scores`` (per-lead score).

This mirrors the HubSpot Breeze / Salesforce Einstein convention: lead
scoring, AI compose, enrichment, and classification as first-class,
auditable jobs rather than opaque inline calls.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all, fetch_one
from app.execution.lead_columns import lead_identity
from app.services.bus import publish_event

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────


class LeadScoreOut(BaseModel):
    lead_id: uuid.UUID
    contact_id: uuid.UUID | None
    score: int = Field(ge=0, le=100)
    tier: Literal["hot", "warm", "cold"]
    reasons: list[str]
    model: str | None
    scored_at: datetime
    identity: str | None = None


class LeadScoreSummary(BaseModel):
    total: int
    hot: int
    warm: int
    cold: int
    historical: int


class AiJobOut(BaseModel):
    id: uuid.UUID
    kind: Literal["score", "compose", "enrich", "classify", "screen"]
    status: Literal["queued", "running", "done", "failed"]
    entity_type: str | None
    entity_id: uuid.UUID | None
    input: dict[str, Any]
    output: dict[str, Any]
    model: str | None
    cost_usd: Decimal | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class AiJobCreate(BaseModel):
    kind: Literal["score", "compose", "enrich", "classify", "screen"]
    entity_type: str = Field("lead", description="What the job runs against (lead, contact, …)")
    entity_id: uuid.UUID | None = Field(None, description="Subject of the job")
    config: dict[str, Any] = Field(default_factory=dict, description="Job config (e.g. icp_description for score, instruction for compose)")
    lead: dict[str, Any] = Field(default_factory=dict, description="Lead/contact context the model needs")


class AiJobAccepted(BaseModel):
    job_id: uuid.UUID
    kind: str
    status: str = "queued"
    correlation_id: uuid.UUID


# ── Lead scores ──────────────────────────────────────────────────────────────


@router.get(
    "/scores",
    response_model=list[LeadScoreOut],
    summary="List lead scores (highest first)",
    description="Powers the score badges + tier chips on Leads/Contacts rows and the AI-prioritised lead board.",
)
async def list_scores(
    _: AuthContext = Depends(get_current_workspace),
    tier: Literal["hot", "warm", "cold"] | None = Query(None),
    include_historical: bool = Query(
        False,
        description="Include scores whose lead has since been deleted. Hidden by default.",
    ),
    limit: int = Query(200, ge=1, le=2000),
) -> list[LeadScoreOut]:
    select = """
        SELECT s.*, l.id AS identity_lead_id, l.custom_fields,
               c.first_name AS c_first_name, c.last_name AS c_last_name,
               c.email AS c_email
        FROM omni_lead_scores s
        LEFT JOIN omni_leads l ON l.id = s.lead_id
        LEFT JOIN omni_contacts c ON c.id = l.contact_id AND c.workspace_id = l.workspace_id
    """
    clauses: list[str] = []
    args: list[Any] = []
    if tier:
        args.append(tier)
        clauses.append(f"s.tier = ${len(args)}")
    if not include_historical:
        clauses.append("l.id IS NOT NULL")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)
    rows = await fetch_all(select + f"{where} ORDER BY s.score DESC LIMIT ${len(args)}", *args)
    return [_score_out(r) for r in rows]


def _score_out(row: dict[str, Any]) -> LeadScoreOut:
    contact = None
    if row.get("c_first_name") or row.get("c_last_name") or row.get("c_email"):
        contact = {
            "first_name": row.get("c_first_name"),
            "last_name": row.get("c_last_name"),
            "email": row.get("c_email"),
        }
    custom_fields = row.get("custom_fields") or {}
    identity = None
    if row.get("identity_lead_id"):
        identity = lead_identity(custom_fields, contact, str(row["lead_id"]))
    return LeadScoreOut.model_validate({**row, "identity": identity})


@router.get(
    "/scores/summary",
    response_model=LeadScoreSummary,
    summary="Exact lead-score tier counts",
)
async def score_summary(_: AuthContext = Depends(get_current_workspace)) -> LeadScoreSummary:
    row = await fetch_one(
        """
        SELECT
            COUNT(*) FILTER (WHERE l.id IS NOT NULL) AS total,
            COUNT(*) FILTER (WHERE l.id IS NOT NULL AND s.tier = 'hot') AS hot,
            COUNT(*) FILTER (WHERE l.id IS NOT NULL AND s.tier = 'warm') AS warm,
            COUNT(*) FILTER (WHERE l.id IS NOT NULL AND s.tier = 'cold') AS cold,
            COUNT(*) FILTER (WHERE l.id IS NULL) AS historical
        FROM omni_lead_scores s
        LEFT JOIN omni_leads l ON l.id = s.lead_id
        """
    )
    return LeadScoreSummary(**{k: int((row or {}).get(k) or 0) for k in LeadScoreSummary.model_fields})


@router.get(
    "/scores/{lead_id}",
    response_model=LeadScoreOut,
    summary="Fetch one lead's latest score + reasons",
)
async def get_score(lead_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> LeadScoreOut:
    row = await fetch_one(
        """
        SELECT s.*, l.id AS identity_lead_id, l.custom_fields,
               c.first_name AS c_first_name, c.last_name AS c_last_name,
               c.email AS c_email
        FROM omni_lead_scores s
        LEFT JOIN omni_leads l ON l.id = s.lead_id
        LEFT JOIN omni_contacts c ON c.id = l.contact_id AND c.workspace_id = l.workspace_id
        WHERE s.lead_id = $1
        """,
        lead_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="no score for this lead yet")
    return _score_out(row)


# ── AI jobs (run log) ──────────────────────────────────────────────────────


@router.get(
    "/jobs",
    response_model=list[AiJobOut],
    summary="AI Studio run log (most recent first)",
    description="Every score / compose / enrich / classify job with its status, output, model, and cost.",
)
async def list_jobs(
    _: AuthContext = Depends(get_current_workspace),
    kind: Literal["score", "compose", "enrich", "classify", "screen"] | None = Query(None),
    status: Literal["queued", "running", "done", "failed"] | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[AiJobOut]:
    clauses: list[str] = []
    args: list[Any] = []
    if kind:
        clauses.append(f"kind = ${len(args) + 1}")
        args.append(kind)
    if status:
        clauses.append(f"status = ${len(args) + 1}")
        args.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)
    rows = await fetch_all(
        f"SELECT * FROM omni_ai_jobs {where} ORDER BY created_at DESC LIMIT ${len(args)}",
        *args,
    )
    return [AiJobOut.model_validate(r) for r in rows]


@router.post(
    "/jobs",
    response_model=AiJobAccepted,
    status_code=202,
    summary="Kick an AI job",
    description=(
        "Publishes an ``ai.<kind>.queued`` event. The muscle runs the model and "
        "publishes ``ai.<kind>.completed`` / ``.failed``; the projector materialises "
        "the run into the AI Studio log (and, for scores, into lead_scores). 202 "
        "because the AI call is asynchronous."
    ),
)
async def create_job(body: AiJobCreate, ctx: AuthContext = Depends(get_current_workspace)) -> AiJobAccepted:
    correlation_id = uuid.uuid4()
    payload = {
        **body.config,
        "lead": body.lead,
        "correlation_id": str(correlation_id),
    }
    await publish_event(
        workspace_id=ctx.workspace_id,
        event_type=f"ai.{body.kind}.queued",
        entity_type=body.entity_type,
        entity_id=str(body.entity_id) if body.entity_id else None,
        payload=payload,
        actor_user_id=ctx.user_id,
        correlation_id=str(correlation_id),
    )
    return AiJobAccepted(job_id=correlation_id, kind=body.kind, correlation_id=correlation_id)
