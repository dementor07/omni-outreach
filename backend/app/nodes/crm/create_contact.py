"""Create a contact projection by emitting contact.created."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, HttpUrl

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class CreateContactConfig(BaseModel):
    email: EmailStr | None = None
    linkedin_url: HttpUrl | None = None
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    headline: str | None = None
    phone: str | None = None
    source: str = Field("workflow", description="Where this contact came from (workflow, manual, integration_name, …)")


MANIFEST = NodeManifest(
    type="crm.create_contact",
    category=NodeCategory.CRM,
    summary="Create a contact in the CRM (emits contact.created; projection picks up)",
    config_schema=CreateContactConfig,
    output_handles=(NodeHandle("default", "Contact event emitted"),),
    side_effect=SideEffect.MUTATE,
    icon="user-plus",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = CreateContactConfig(**ctx.config)
    if not cfg.email and not cfg.linkedin_url:
        return NodeResult(handle="default", error="CONTACT_REQUIRES_EMAIL_OR_LINKEDIN")
    contact_id = str(uuid.uuid4())
    events = [
        {
            "event_type": "contact.created",
            "entity_type": "contact",
            "entity_id": contact_id,
            "payload": {
                "email": cfg.email,
                "linkedin_url": str(cfg.linkedin_url) if cfg.linkedin_url else None,
                "first_name": cfg.first_name,
                "last_name": cfg.last_name,
                "company": cfg.company,
                "headline": cfg.headline,
                "phone": cfg.phone,
                "source": cfg.source,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"contact_id": contact_id})


register(MANIFEST, execute)
