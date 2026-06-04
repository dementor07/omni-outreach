"""Create a CRM task linked to the current contact (or its deal)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

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


class CreateTaskConfig(BaseModel):
    title_template: str = Field(min_length=1, max_length=200, description="Task title; supports {{contact.first_name}} variables")
    due_in_days: int = Field(3, ge=0, le=365)
    assign_to_user_id: str | None = Field(None, description="Workspace member id; defaults to the lead's owner")
    priority: str = Field("normal", description="low | normal | high")


MANIFEST = NodeManifest(
    type="crm.create_task",
    category=NodeCategory.CRM,
    summary="Create a CRM task linked to the current contact",
    config_schema=CreateTaskConfig,
    output_handles=(NodeHandle("default", "Task created"),),
    side_effect=SideEffect.MUTATE,
    icon="check-square",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = CreateTaskConfig(**ctx.config)
    contact_id = ctx.lead.get("contact_id") or ctx.lead.get("id")
    if not contact_id:
        return NodeResult(handle="default", error="TASK_MISSING_CONTACT")
    task_id = str(uuid.uuid4())
    events = [
        {
            "event_type": "task.created",
            "entity_type": "task",
            "entity_id": task_id,
            "payload": {
                # title_template is rendered by the projector against the lead
                # context; the raw template is carried here.
                "title_template": cfg.title_template,
                # ISO date string the projector inserts directly (was an opaque
                # ordinal int before — CONTRACT-004 cleanup).
                "due_date": (date.today() + timedelta(days=cfg.due_in_days)).isoformat(),
                "assign_to_user_id": cfg.assign_to_user_id,
                "priority": cfg.priority,
                "contact_id": str(contact_id),
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"task_id": task_id})


register(MANIFEST, execute)
