"""Shared factory for first-class LinkFinder enrichment nodes."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
)


class LinkFinderBaseConfig(BaseModel):
    connection_name: str = Field(min_length=1, max_length=200, description="LinkFinder connection (api_key)")


class CompanyNameConfig(LinkFinderBaseConfig):
    company_name: str | None = Field(None, max_length=255, description="Optional company-name override; defaults to the lead company")


class LinkedinCompanyUrlConfig(LinkFinderBaseConfig):
    linkedin_company_url: str = Field(min_length=1, max_length=500, description="LinkedIn company page URL")


class InstagramProfileConfig(LinkFinderBaseConfig):
    instagram_profile_url: str | None = Field(None, max_length=500, description="Optional Instagram profile URL; defaults to the lead Instagram username")


def make_manifest(
    *,
    node_type: str,
    display_name: str,
    summary: str,
    config_schema: type[BaseModel],
    icon: str = "database-zap",
) -> NodeManifest:
    return NodeManifest(
        type=node_type,
        category=NodeCategory.ENRICH,
        display_name=display_name,
        summary=summary,
        config_schema=config_schema,
        output_handles=(
            NodeHandle("default", "LinkFinder finished; continue with enriched data"),
            NodeHandle("on_error", "LinkFinder failed; continue through the fallback route"),
        ),
        capabilities=("connection:linkfinder",),
        side_effect=SideEffect.NETWORK,
        icon=icon,
        primary_fields=("connection_name",),
        advanced_fields=tuple(
            field
            for field in ("company_name", "linkedin_company_url", "instagram_profile_url")
            if field in config_schema.model_fields
        ),
        visible_in_palette=True,
    )


def make_execute(linkfinder_type: str, config_schema: type[BaseModel]):
    async def execute(ctx: NodeContext) -> NodeResult:
        cfg = config_schema(**ctx.config)
        correlation_id = ctx.correlation_id or str(uuid.uuid4())
        payload: dict[str, Any] = {
            "enrich_source": "linkfinder",
            "connection_name": cfg.connection_name,
            "linkfinder_type": linkfinder_type,
            "correlation_id": correlation_id,
            "node_id": ctx.node_id,
            "lead_id": ctx.lead.get("id"),
        }
        for key in ("company_name", "linkedin_company_url", "instagram_profile_url"):
            value = getattr(cfg, key, None)
            if value:
                payload[key] = value
        return NodeResult(
            handle="default",
            events=[
                {
                    "event_type": "ai.enrich.requested",
                    "entity_type": "lead",
                    "entity_id": ctx.lead.get("id"),
                    "payload": payload,
                }
            ],
            telemetry={"correlation_id": correlation_id, "provider": "linkfinder", "type": linkfinder_type},
        )

    return execute
