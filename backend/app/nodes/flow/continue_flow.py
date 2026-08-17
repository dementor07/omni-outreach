"""A hidden pass-through node used as a single exit for canvas building blocks."""

from __future__ import annotations

from pydantic import BaseModel

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class ContinueConfig(BaseModel):
    pass


MANIFEST = NodeManifest(
    type="flow.continue",
    category=NodeCategory.FLOW,
    display_name="Continue with enriched lead",
    summary="Single readable exit from a multi-stage canvas building block",
    config_schema=ContinueConfig,
    output_handles=(NodeHandle("default", "Continue to the next step"),),
    side_effect=SideEffect.READ,
    icon="arrow-right",
    visible_in_palette=False,
)


async def execute(ctx: NodeContext) -> NodeResult:
    return NodeResult(handle="default")


register(MANIFEST, execute)
