"""Score-based person verification BEFORE the paid Claude screen.

Runs inside the people fan-out (one child lead per discovered profile). It scores
the person's identity against the target company using cheap pure-Rust-equivalent
signals (snippet match, company-mismatch fast-path, decision-maker title,
LinkedIn URL) and branches:

  verified — score >= threshold → continue to ai.screen_person (Claude runs LAST)
  rejected — score below threshold or explicit company mismatch → drop, no Claude

This is the cost gate from omni_outreach_v3: identity is proven by score first;
Claude only screens contact-worthiness on the survivors. The weighted score +
breakdown are written to the lead's custom_fields for downstream lead scoring.

Absorbed from omni_outreach_v3 discovery.rs + plan.md Phase 1/5.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)
from app.services import people_scoring


class VerifyPersonConfig(BaseModel):
    item_field: str = Field("item", description="custom_fields key holding the person dict (from flow.for_each)")
    company_field: str = Field(
        "company_resolution",
        description="custom_fields key holding the resolved company (name carried under .name)",
    )
    pass_threshold: int = Field(40, description="Minimum verification score to pass (plan.md default 40)")


MANIFEST = NodeManifest(
    type="condition.verify_person",
    category=NodeCategory.CONDITION,
    summary="Score a discovered person's identity before the paid Claude screen",
    config_schema=VerifyPersonConfig,
    output_handles=(
        NodeHandle("verified", "Score >= threshold — proceed to Claude screen"),
        NodeHandle("rejected", "Score below threshold or company mismatch — drop"),
    ),
    side_effect=SideEffect.READ,
    icon="shield-check",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = VerifyPersonConfig(**ctx.config)
    cf = ctx.lead.get("custom_fields") or {}
    person = cf.get(cfg.item_field) or {}
    company = cf.get(cfg.company_field) or {}
    company_name = company.get("name") or cf.get("company_name") or ""

    title = person.get("title") or ""
    snippet = person.get("snippet")
    linkedin_url = person.get("linkedin_url")
    domain_known = bool(company.get("domain"))
    kg_known = bool(company.get("people_discovered"))

    # Hard fast-path: explicit different-company mention → reject, skip scoring.
    if people_scoring.is_company_mismatch(title, company_name):
        return NodeResult(
            handle="rejected",
            telemetry={"reason": "company_mismatch", "title": title, "company": company_name},
        )

    total, breakdown = people_scoring.verification_score(
        title=title,
        target_company=company_name,
        snippet=snippet,
        linkedin_url=linkedin_url,
        domain_known=domain_known,
        kg_known=kg_known,
    )
    passed = total >= cfg.pass_threshold

    # Stash the score breakdown so a downstream lead projection / ai.screen can
    # carry verification_details (plan.md Phase 5).
    cf_out = dict(cf)
    cf_out["verification"] = {"score": total, "breakdown": breakdown, "passed": passed}

    events = [
        {
            "event_type": "lead.custom_fields_updated",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {"custom_fields": {"verification": cf_out["verification"]}},
        }
    ]
    return NodeResult(
        handle="verified" if passed else "rejected",
        events=events,
        telemetry={"score": total, "threshold": cfg.pass_threshold, "company": company_name},
    )


register(MANIFEST, execute)
