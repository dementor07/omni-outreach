"""Google Sheets lead source — pull one contact per row from a sheet range."""

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


class SheetsSourceConfig(BaseModel):
    connection_name: str = Field(description="Google OAuth connection (configured via Sign in with Google)")
    spreadsheet_id: str = Field(min_length=10, description="The ID portion of the sheet URL")
    sheet_name: str = Field("Sheet1", description="Tab name to read")
    header_row: int = Field(1, ge=1, description="1-indexed row that holds column headers")
    limit: int = Field(500, ge=1, le=5000)


MANIFEST = NodeManifest(
    type="source.sheets",
    category=NodeCategory.SOURCE,
    summary="Pull leads from a Google Sheets tab (header row = field names)",
    config_schema=SheetsSourceConfig,
    output_handles=(
        NodeHandle("default", "Emitted when 1+ rows have email or linkedin_url"),
        NodeHandle("empty", "Sheet had no usable rows"),
    ),
    capabilities=("connection:google",),
    side_effect=SideEffect.NETWORK,
    icon="sheets",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SheetsSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.sheets.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "connection_name": cfg.connection_name,
                "spreadsheet_id": cfg.spreadsheet_id,
                "sheet_name": cfg.sheet_name,
                "header_row": cfg.header_row,
                "limit": cfg.limit,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
