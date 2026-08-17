"""ATS job-board sources — 12 first-class hiring-company discovery nodes.

source.greenhouse, source.ashby, source.smartrecruiters, source.bamboohr,
source.workday, source.icims, source.lever, source.workable, source.recruitee,
source.personio, source.rippling, source.breezy.

Each pulls hiring companies off one Applicant Tracking System. Discovery is two
stages: company slugs are harvested from the CommonCrawl index by the ATS
discovery worker into the GLOBAL omni_ats_slugs table (no per-workspace setup, no
keys); these nodes then ask the Rust muscle (ChannelType.ATS, handlers/ats.rs) to
fetch each slug's live jobs from that ATS's public API and write the companies to
``custom_fields[companies_key]`` — exactly the shape ``flow.for_each`` iterates,
one company per child lead. Same interior pipeline as source.naukri.

All 12 are KEYLESS and share the SAME setup (none) — so this is one ChannelType
with the platform as a parameter (like serper_people/searxng_people share a Rust
handler), but they stay DISTINCT NODES so each appears as its own named product
in the palette. Ported from Allen's CommonCrawl-CDX pipeline; see
[[project_ats_cdx_port]].
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

# (node suffix, human label, ATS home page, palette icon)
_PLATFORMS: list[tuple[str, str, str]] = [
    ("greenhouse", "Greenhouse", "building"),
    ("ashby", "Ashby", "building"),
    ("smartrecruiters", "SmartRecruiters", "building"),
    ("bamboohr", "BambooHR", "building"),
    ("workday", "Workday", "building"),
    ("icims", "iCIMS", "building"),
    ("lever", "Lever", "building"),
    ("workable", "Workable", "building"),
    ("recruitee", "Recruitee", "building"),
    ("personio", "Personio", "building"),
    ("rippling", "Rippling", "building"),
    ("breezy", "Breezy", "building"),
]


class ATSSourceConfig(BaseModel):
    max_companies: int = Field(
        25, ge=1, le=500,
        description="How many hiring companies (with ≥1 active job) to pull this run",
    )
    companies_key: str = Field(
        "companies",
        description="custom_fields key where the deduped company list lands for flow.for_each",
    )


def _make_execute(platform: str):
    async def execute(ctx: NodeContext) -> NodeResult:
        cfg = ATSSourceConfig(**ctx.config)
        correlation_id = ctx.correlation_id or str(uuid.uuid4())
        return NodeResult(
            handle="default",
            events=[
                {
                    # All 12 nodes emit the same intent; the muscle keys on `platform`.
                    "event_type": "source.ats.requested",
                    "entity_type": "workflow",
                    "entity_id": ctx.workflow_id,
                    "payload": {
                        "platform": platform,
                        "max_companies": cfg.max_companies,
                        "companies_key": cfg.companies_key,
                        "correlation_id": correlation_id,
                    },
                }
            ],
            telemetry={"correlation_id": correlation_id, "platform": platform},
        )

    return execute


def _register_all() -> None:
    for platform, label, icon in _PLATFORMS:
        manifest = NodeManifest(
            type=f"source.{platform}",
            category=NodeCategory.SOURCE,
            summary=f"Pull hiring companies from {label} job boards (CommonCrawl-indexed, no API key)",
            config_schema=ATSSourceConfig,
            output_handles=(
                NodeHandle("default", "Companies discovered; list lands in custom_fields[companies_key]"),
                NodeHandle("empty", "No companies with active jobs found"),
                NodeHandle("on_error", "Job API/slug fetch failed"),
            ),
            # Keyless: company slugs come from the global omni_ats_slugs table and
            # the job APIs are public. No per-workspace connection.
            side_effect=SideEffect.NETWORK,
            icon=icon,
        )
        register(manifest, _make_execute(platform))


_register_all()
