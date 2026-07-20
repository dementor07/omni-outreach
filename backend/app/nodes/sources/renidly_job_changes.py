"""Renidly job-changes FAN-OUT lead source (RENIDLY-002).

Emits ``source.renidly_job_changes.requested``; the Rust muscle's
RenidlyJobChanges handler (``handlers/renidly.rs``) pulls
``GET /api/data/v1/job-changes/search`` and writes the deduped people rows under
``custom_fields[people_key]`` for the downstream ``flow.for_each(people)`` →
``crm.create_contact`` — the same shape as ``source.apollo_people``.

Each person just changed jobs (a ready-made lead). Going through the muscle is
what makes each one a LEAD enrolled in the campaign (create_contact attaches the
contact to the fanned-out lead) so the objective can measure progress — the
earlier in-process version only created global contacts, never campaign leads.
Needs a Renidly connection (api_key); the credential_ref is minted from the
``connection:renidly`` capability and redeemed in the muscle.
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


class RenidlyJobChangesConfig(BaseModel):
    connection_name: str = Field(min_length=1, max_length=200, description="Renidly connection (api_key)")
    limit: int = Field(3, ge=1, le=100, description="How many job-change people to pull per run")
    page: int = Field(
        1, ge=1, le=1000, description="Which page of the feed to pull (each page is a distinct set of people)"
    )
    randomize_page: bool = Field(
        False,
        description="Sample a RANDOM page in [1, max_page] each run so repeated runs pull fresh people (demos / continuous sampling). Overrides page.",
    )
    max_page: int = Field(20, ge=1, le=1000, description="Upper bound for randomize_page sampling")
    people_key: str = Field(
        "people",
        min_length=1,
        description="custom_fields key where the people list lands for flow.for_each",
    )


MANIFEST = NodeManifest(
    type="source.renidly_job_changes",
    category=NodeCategory.SOURCE,
    display_name="Job changes (Renidly)",
    summary="People who just changed jobs — fan-out lead source; writes custom_fields[people_key] for flow.for_each",
    config_schema=RenidlyJobChangesConfig,
    output_handles=(
        NodeHandle("default", "1+ job-changers found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No job-change events came back"),
        NodeHandle("on_error", "Renidly not connected or the call failed"),
    ),
    capabilities=("connection:renidly",),
    side_effect=SideEffect.NETWORK,
    icon="briefcase",
    primary_fields=("connection_name", "limit"),
    advanced_fields=("page", "randomize_page", "max_page", "people_key"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = RenidlyJobChangesConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "source.renidly_job_changes.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "renidly",
                    "connection_name": cfg.connection_name,
                    "limit": cfg.limit,
                    "page": cfg.page,
                    "randomize_page": cfg.randomize_page,
                    "max_page": cfg.max_page,
                    "people_key": cfg.people_key,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "renidly"},
    )


register(MANIFEST, execute)
