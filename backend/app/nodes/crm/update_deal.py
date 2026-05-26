"""Move a deal to a new stage by emitting deal.stage_changed."""

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


class UpdateDealConfig(BaseModel):
    new_stage: str = Field(min_length=1, description="Target stage name (must exist in the workspace pipeline)")


MANIFEST = NodeManifest(
    type="crm.update_deal",
    category=NodeCategory.CRM,
    summary="Move the current lead's deal to a new pipeline stage",
    config_schema=UpdateDealConfig,
    output_handles=(
        NodeHandle("default", "Deal stage updated"),
        NodeHandle("on_error", "Lead had no associated deal"),
    ),
    side_effect=SideEffect.MUTATE,
    icon="trending-up",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = UpdateDealConfig(**ctx.config)
    deal_id = ctx.lead.get("deal_id")
    if not deal_id:
        return NodeResult(handle="on_error", error="DEAL_NOT_FOUND_ON_LEAD")
    events = [
        {
            "event_type": "deal.stage_changed",
            "entity_type": "deal",
            "entity_id": deal_id,
            "payload": {"stage": cfg.new_stage},
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"deal_id": deal_id, "new_stage": cfg.new_stage})


register(MANIFEST, execute)
