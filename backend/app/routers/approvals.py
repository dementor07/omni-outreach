"""Human-approval queue (CONTRACT-005).

flow.human_approval parks a lead and emits ``approval.requested`` (projected
into omni_approvals as pending). An operator reviews + resolves it here:

  GET   /approvals             → list pending approvals for the workspace
  PATCH /approvals/{id}/draft  → edit the AI-composed draft before approving (B1)
  POST  /approvals/{id}/resolve → approve/reject

Resolving does two things:
  1. emits ``approval.resolved`` (projector flips the row to the outcome), and
  2. emits a transition on outreach.transitions off the approval's node on the
     chosen handle, which un-parks the lead (the transition worker advances it
     down approved/rejected). This is the resume half of the park/resume pair.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import execute, fetch_all, fetch_one, system_scope
from app.services import bus
from app.services.bus import publish_event

router = APIRouter()


class ApprovalEvidence(BaseModel):
    """A fact source that was available to the compose step.

    This is deliberately derived from the lead snapshot instead of inferred from
    the prose in the draft.  Operators can therefore inspect the real source
    material without pretending that a fuzzy text match proves provenance.
    """

    kind: Literal["hiring", "post", "website", "profile"]
    label: str
    url: str | None = None
    excerpt: str | None = None


class ApprovalOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    node_id: uuid.UUID | None
    prompt: str
    draft: str | None
    status: str
    created_at: datetime
    # Which campaign parked this approval — lets the UI filter by campaign so an
    # operator can tell a campaign-specific problem (e.g. duplicate approvals in
    # one campaign) from a global one.
    campaign_id: uuid.UUID | None = None
    campaign_name: str | None = None
    prospect_name: str | None = None
    prospect_linkedin_url: str | None = None
    prospect_company: str | None = None
    # Provider-side id + human label of the LinkedIn seat that sent the invite.
    # The id disambiguates duplicate display names (two Hemanshu seats exist).
    sending_account_id: str | None = None
    sending_account_name: str | None = None
    evidence_sources: list[ApprovalEvidence] = Field(default_factory=list)


def _excerpt(value: Any, limit: int = 280) -> str | None:
    if not isinstance(value, str):
        return None
    clean = " ".join(value.split()).strip()
    if not clean:
        return None
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _approval_evidence(custom_fields: Any, linkedin_url: str | None) -> list[ApprovalEvidence]:
    """Normalize the enrichment facts handed to ai.compose into UI provenance."""
    if isinstance(custom_fields, str):
        try:
            custom_fields = json.loads(custom_fields)
        except (TypeError, ValueError):
            custom_fields = {}
    cf = custom_fields if isinstance(custom_fields, dict) else {}
    sources: list[ApprovalEvidence] = []

    hiring = _excerpt(cf.get("hiring_signal") or cf.get("job_signal"))
    if hiring:
        sources.append(ApprovalEvidence(
            kind="hiring",
            label="Hiring signal",
            url=cf.get("job_url") if isinstance(cf.get("job_url"), str) else None,
            excerpt=hiring,
        ))

    post = _excerpt(
        cf.get("latest_post_context")
        or cf.get("latest_post")
        or cf.get("recent_post")
        or cf.get("recent_posts_context")
    )
    if post:
        sources.append(ApprovalEvidence(
            kind="post", label="LinkedIn post", url=linkedin_url, excerpt=post,
        ))

    website = _excerpt(cf.get("website_summary") or cf.get("company_about"))
    if website:
        website_url = cf.get("website_url")
        sources.append(ApprovalEvidence(
            kind="website",
            label="Company website",
            url=website_url if isinstance(website_url, str) else None,
            excerpt=website,
        ))

    profile = _excerpt(cf.get("profile_about") or cf.get("profile_headline") or cf.get("headline"))
    if profile:
        sources.append(ApprovalEvidence(
            kind="profile", label="LinkedIn profile", url=linkedin_url, excerpt=profile,
        ))
    return sources


class ResolveBody(BaseModel):
    # Maps directly to a human_approval output handle.
    handle: Literal["approved", "rejected"]


class DraftBody(BaseModel):
    draft: str = Field(max_length=20000, description="The reviewed/edited AI draft")


@router.get("", response_model=list[ApprovalOut], summary="List pending approvals")
async def list_approvals(
    _: AuthContext = Depends(get_current_workspace),
    campaign_id: uuid.UUID | None = Query(None, description="Only approvals for this campaign"),
) -> list[ApprovalOut]:
    rows = await fetch_all(
        """
        SELECT a.id, a.lead_id, a.node_id, a.prompt, a.draft, a.status, a.created_at,
               l.workflow_id AS campaign_id, w.name AS campaign_name,
               COALESCE(
                   NULLIF(BTRIM(CONCAT_WS(' ', c.first_name, c.last_name)), ''),
                   NULLIF(BTRIM(CONCAT_WS(' ', l.custom_fields->>'first_name', l.custom_fields->>'last_name')), '')
               ) AS prospect_name,
               COALESCE(c.linkedin_url, l.custom_fields->>'linkedin_url') AS prospect_linkedin_url,
               COALESCE(c.company, l.custom_fields->>'company') AS prospect_company,
               sa.external_identity AS sending_account_id,
               sa.display_name AS sending_account_name,
               l.custom_fields AS lead_custom_fields
        FROM omni_approvals a
        LEFT JOIN omni_leads l ON l.id = a.lead_id AND l.workspace_id = a.workspace_id
        LEFT JOIN omni_workflows w ON w.id = l.workflow_id AND w.workspace_id = a.workspace_id
        LEFT JOIN omni_contacts c ON c.id = l.contact_id AND c.workspace_id = a.workspace_id
        LEFT JOIN omni_sending_accounts sa
          ON sa.workspace_id = a.workspace_id
         AND sa.channel_kind = 'linkedin'
         AND sa.external_identity = l.custom_fields->>'invite_account_id'
        WHERE a.status = 'pending'
          AND ($1::uuid IS NULL OR l.workflow_id = $1)
        ORDER BY a.created_at DESC, a.id DESC
        """,
        campaign_id,
    )
    out: list[ApprovalOut] = []
    for row in rows:
        data = dict(row)
        custom_fields = data.pop("lead_custom_fields", {})
        data["evidence_sources"] = _approval_evidence(
            custom_fields, data.get("prospect_linkedin_url")
        )
        out.append(ApprovalOut.model_validate(data))
    return out


@router.patch("/{approval_id}/draft", status_code=202, summary="Edit an approval's AI draft (B1)")
async def update_draft(
    approval_id: uuid.UUID,
    body: DraftBody,
    ctx: AuthContext = Depends(get_current_workspace),
) -> dict:
    row = await fetch_one(
        "SELECT id, status, correlation_id FROM omni_approvals WHERE id = $1",
        approval_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="approval not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"approval already {row['status']} — draft is frozen")

    # Event-sourced edit: the projector applies it to the pending row. Mirrors
    # every other state change in v2 (no direct UPDATE from the request path).
    await publish_event(
        workspace_id=ctx.workspace_id,
        event_type="approval.draft_updated",
        entity_type="approval",
        entity_id=str(approval_id),
        payload={"draft": body.draft, "edited_by": ctx.user_id},
        actor_user_id=ctx.user_id,
        correlation_id=str(row["correlation_id"]) if row.get("correlation_id") else None,
    )
    return {"ok": True}


@router.post("/{approval_id}/resolve", status_code=202, summary="Approve or reject a parked lead")
async def resolve_approval(
    approval_id: uuid.UUID,
    body: ResolveBody,
    ctx: AuthContext = Depends(get_current_workspace),
) -> dict:
    row = await fetch_one(
        "SELECT id, lead_id, node_id, status, correlation_id, draft FROM omni_approvals WHERE id = $1",
        approval_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="approval not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"approval already {row['status']}")

    correlation_id = str(row["correlation_id"]) if row.get("correlation_id") else None

    # APPROVAL-EDIT-001: carry the REVIEWED/EDITED draft onto the lead so the
    # downstream send renders the operator-approved text, not the original compose
    # output. flow.human_approval stores the draft under its draft_variable
    # (default 'ai_draft'); the channel template ({{ai_draft}}) reads that from
    # custom_fields. Without this, editing a draft in the queue was a no-op — the
    # unedited message shipped. Written SYNCHRONOUSLY before the resume transition
    # so the DM command (built after the resume) sees the approved text.
    if body.handle == "approved" and row.get("draft") and row.get("node_id"):
        node = await fetch_one(
            "SELECT config FROM omni_workflow_nodes WHERE id=$1 AND workspace_id=$2",
            row["node_id"], ctx.workspace_id,
        )
        draft_var = ((node or {}).get("config") or {}).get("draft_variable") or "ai_draft"
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET custom_fields = COALESCE(custom_fields,'{}'::jsonb) || $1::jsonb, "
                "updated_at = NOW() WHERE id=$2 AND workspace_id=$3",
                json.dumps({draft_var: row["draft"]}), str(row["lead_id"]), ctx.workspace_id,
            )

    # 1. Projection event: flips the omni_approvals row to the outcome.
    await publish_event(
        workspace_id=ctx.workspace_id,
        event_type="approval.resolved",
        entity_type="approval",
        entity_id=str(approval_id),
        payload={"handle": body.handle, "resolved_by": ctx.user_id},
        actor_user_id=ctx.user_id,
        correlation_id=correlation_id,
    )

    # 2. Resume the lead: emit a transition off the approval's node on the chosen
    #    handle. The transition worker un-parks the lead and advances it.
    transition = {
        "lead_id": str(row["lead_id"]),
        "source_node_id": str(row["node_id"]) if row.get("node_id") else None,
        "handle": body.handle,
        "event_type": "transition",
        "metadata": {
            "workspace_id": ctx.workspace_id,
            "correlation_id": correlation_id,
            "resolved_by": ctx.user_id,
        },
    }
    await bus._producer.send_and_wait(  # type: ignore[union-attr]
        bus.TRANSITIONS_TOPIC, value=transition, key=str(row["lead_id"])
    )

    return {"ok": True, "handle": body.handle}
