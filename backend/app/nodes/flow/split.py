"""A/B split — deterministically route a lead down one of N weighted branches.

The orchestrator hashes the lead id against the cumulative weights so a given
lead always lands in the same branch (stable across retries).
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field, field_validator

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)

_MAX_BRANCHES = 4


class SplitConfig(BaseModel):
    weights: list[int] = Field(
        default=[50, 50],
        description="Percentage weight per branch (variant_a, variant_b, …). Must sum to 100.",
    )

    @field_validator("weights")
    @classmethod
    def _check(cls, v: list[int]) -> list[int]:
        if not 2 <= len(v) <= _MAX_BRANCHES:
            raise ValueError(f"between 2 and {_MAX_BRANCHES} branches required")
        if sum(v) != 100:
            raise ValueError("weights must sum to 100")
        return v


MANIFEST = NodeManifest(
    type="flow.split",
    category=NodeCategory.FLOW,
    summary="A/B test — deterministically route leads down weighted branches",
    config_schema=SplitConfig,
    output_handles=(
        NodeHandle("variant_a", "First weighted branch"),
        NodeHandle("variant_b", "Second weighted branch"),
        NodeHandle("variant_c", "Third weighted branch (if configured)"),
        NodeHandle("variant_d", "Fourth weighted branch (if configured)"),
    ),
    side_effect=SideEffect.READ,
    icon="shuffle",
)

_HANDLES = ("variant_a", "variant_b", "variant_c", "variant_d")


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SplitConfig(**ctx.config)
    lead_id = str(ctx.lead.get("id") or ctx.lead.get("contact_id") or "")
    bucket = int(hashlib.sha256(lead_id.encode()).hexdigest(), 16) % 100
    cumulative = 0
    for i, w in enumerate(cfg.weights):
        cumulative += w
        if bucket < cumulative:
            return NodeResult(handle=_HANDLES[i], telemetry={"bucket": bucket, "branch": i})
    return NodeResult(handle=_HANDLES[0], telemetry={"bucket": bucket, "branch": 0})


register(MANIFEST, execute)
