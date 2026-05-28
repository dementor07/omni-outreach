"""Branch on whether the current contact carries a given tag."""

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


class HasTagConfig(BaseModel):
    tag: str = Field(min_length=1, max_length=64, description="Tag to test for on the contact")


MANIFEST = NodeManifest(
    type="condition.has_tag",
    category=NodeCategory.CONDITION,
    summary="Does the contact have a given tag?",
    config_schema=HasTagConfig,
    output_handles=(
        NodeHandle("true", "Contact has the tag"),
        NodeHandle("false", "Contact does not have the tag"),
    ),
    side_effect=SideEffect.READ,
    icon="tag",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = HasTagConfig(**ctx.config)
    tags = ctx.lead.get("tags") or ctx.lead.get("custom_fields", {}).get("tags") or []
    has = isinstance(tags, (list, tuple)) and cfg.tag in tags
    return NodeResult(handle="true" if has else "false", telemetry={"tag": cfg.tag, "matched": has})


register(MANIFEST, execute)
