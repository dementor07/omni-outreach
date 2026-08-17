"""Remove a tag from the current contact."""

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


class RemoveTagConfig(BaseModel):
    tag: str = Field(min_length=1, max_length=64, description="Tag to remove")


MANIFEST = NodeManifest(
    type="crm.remove_tag",
    category=NodeCategory.CRM,
    summary="Remove a tag from the current contact",
    config_schema=RemoveTagConfig,
    output_handles=(NodeHandle("default", "Tag removed"),),
    side_effect=SideEffect.MUTATE,
    icon="tag",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = RemoveTagConfig(**ctx.config)
    contact_id = ctx.lead.get("contact_id") or ctx.lead.get("id")
    if not contact_id:
        return NodeResult(handle="default", error="TAG_MISSING_CONTACT")
    # CONTRACT-002: emit the .queued intent so the dispatcher routes it to the
    # REMOVE_TAG muscle channel (Rust returns lead_mutations.remove_tag, applied
    # to custom_fields.tags by the transition worker — CONTRACT-003).
    events = [
        {
            "event_type": "crm.remove_tag.queued",
            "entity_type": "contact",
            "entity_id": str(contact_id),
            "payload": {"tag": cfg.tag},
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"tag": cfg.tag})


register(MANIFEST, execute)
