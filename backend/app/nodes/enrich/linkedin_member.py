"""LinkedIn member profile enrichment (Unipile GET /users/{id}/profile).

Fetches a person's LinkedIn profile via a Unipile seat and merges the profile
fields (headline/company/role/location) onto the lead as an ``enrichment``
envelope. Resolves the target from the lead's linkedin_url (or a public_id in
config). Needs a Unipile connection + seat.
"""

from __future__ import annotations

import uuid

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


class LinkedInMemberProfileConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection")
    unipile_account_id: str = Field(min_length=1, description="Unipile seat (account id)")
    public_id: str | None = Field(None, description="Explicit LinkedIn public id (else resolved from linkedin_url)")


MANIFEST = NodeManifest(
    type="enrich.linkedin_member",
    category=NodeCategory.ENRICH,
    display_name="LinkedIn profile (Unipile)",
    summary="Enrich the lead with their LinkedIn profile via Unipile",
    config_schema=LinkedInMemberProfileConfig,
    output_handles=(
        NodeHandle("default", "Profile fetched; fields merged onto the lead"),
        NodeHandle("on_error", "Lookup failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="user-search",
    primary_fields=("connection_name", "unipile_account_id"),
    advanced_fields=("public_id",),
    visible_in_palette=False,
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInMemberProfileConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    payload = {
        "provider": "unipile",
        "connection_name": cfg.connection_name,
        "unipile_account_id": cfg.unipile_account_id,
        "correlation_id": correlation_id,
        "node_id": ctx.node_id,
        "lead_id": ctx.lead.get("id"),
    }
    if cfg.public_id:
        payload["public_id"] = cfg.public_id
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "enrich.linkedin_member.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": payload,
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
