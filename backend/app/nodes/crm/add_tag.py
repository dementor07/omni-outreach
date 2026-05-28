"""Add a tag to the current contact."""

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


class AddTagConfig(BaseModel):
    tag: str = Field(min_length=1, max_length=64, description="Tag to add (e.g. 'replied', 'icp', 'hot')")


MANIFEST = NodeManifest(
    type="crm.add_tag",
    category=NodeCategory.CRM,
    summary="Add a tag to the current contact",
    config_schema=AddTagConfig,
    output_handles=(NodeHandle("default", "Tag added"),),
    side_effect=SideEffect.MUTATE,
    icon="tag",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = AddTagConfig(**ctx.config)
    contact_id = ctx.lead.get("contact_id") or ctx.lead.get("id")
    if not contact_id:
        return NodeResult(handle="default", error="TAG_MISSING_CONTACT")
    events = [
        {
            "event_type": "contact.tag_added",
            "entity_type": "contact",
            "entity_id": str(contact_id),
            "payload": {"tag": cfg.tag},
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"tag": cfg.tag})


register(MANIFEST, execute)
