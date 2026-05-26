"""Create a CRM deal for the current lead's contact.

Emits a ``deal.created`` event. The ``deals_v`` projection picks it up
and the Kanban view sees the new card under the configured stage.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

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


class CreateDealConfig(BaseModel):
    name_template: str = Field(description="Deal name with {{contact.company}}-style variables")
    stage: str = Field(description="Initial pipeline stage (must exist in workspace pipeline config)")
    value: Decimal | None = Field(None, ge=0, description="Estimated deal value")
    currency: str = Field("USD", min_length=3, max_length=3)


MANIFEST = NodeManifest(
    type="crm.create_deal",
    category=NodeCategory.CRM,
    summary="Create a deal in the pipeline for the current contact",
    config_schema=CreateDealConfig,
    output_handles=(NodeHandle("default", "Deal created"),),
    side_effect=SideEffect.MUTATE,
    icon="briefcase",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = CreateDealConfig(**ctx.config)
    contact_id = ctx.lead.get("contact_id") or ctx.lead.get("id")
    if not contact_id:
        return NodeResult(handle="default", error="DEAL_MISSING_CONTACT")
    deal_id = str(uuid.uuid4())
    events = [
        {
            "event_type": "deal.created",
            "entity_type": "deal",
            "entity_id": deal_id,
            "payload": {
                "name": cfg.name_template,
                "stage": cfg.stage,
                "value": str(cfg.value) if cfg.value is not None else None,
                "currency": cfg.currency,
                "contact_id": str(contact_id),
                "company_id": ctx.lead.get("company_id"),
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"deal_id": deal_id})


register(MANIFEST, execute)
