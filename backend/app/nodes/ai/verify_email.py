"""Verify a lead email before it reaches an outbound email node."""

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
from app.services import email_verification


class VerifyEmailConfig(BaseModel):
    email_field: str = Field(
        "email",
        description="Lead field containing the email address; falls back to custom_fields",
    )


MANIFEST = NodeManifest(
    type="enrich.email_verify",
    category=NodeCategory.ENRICH,
    summary="Check email syntax, disposable/role risk, and MX evidence before sending",
    config_schema=VerifyEmailConfig,
    output_handles=(
        NodeHandle("verified", "Mailbox verified by a trusted provider"),
        NodeHandle("valid_domain", "Syntax + MX pass; mailbox itself remains unverified"),
        NodeHandle("risky", "Role-based or otherwise risky address"),
        NodeHandle("invalid", "Invalid syntax, disposable domain, or no MX"),
        NodeHandle("unknown", "Verification could not complete"),
    ),
    capabilities=("dns:mx",),
    side_effect=SideEffect.NETWORK,
    icon="badge-check",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = VerifyEmailConfig(**ctx.config)
    custom_fields = ctx.lead.get("custom_fields") or {}
    email = ctx.lead.get(cfg.email_field) or custom_fields.get(cfg.email_field) or ""
    result = await email_verification.verify_and_save(ctx.workspace_id, str(email))
    event = {
        "event_type": "email.verification.completed",
        "entity_type": "lead",
        "entity_id": ctx.lead.get("id"),
        "payload": result.event_payload(),
    }
    return NodeResult(
        handle=result.status,
        events=[event],
        telemetry={
            "status": result.status,
            "reason": result.reason,
            "provider": result.provider,
            "mx_hosts": len(result.mx_hosts),
        },
    )


register(MANIFEST, execute)
