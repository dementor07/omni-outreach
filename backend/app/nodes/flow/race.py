"""Race N branches — first to produce a result wins, others are cancelled.

Used for "first channel that gets a response wins" patterns. The
orchestrator opens N parallel sub-paths; when the first one emits a
result event with a configured ``winner_event_type``, the others get a
``cancel`` signal.
"""

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


class RaceConfig(BaseModel):
    branches: int = Field(2, ge=2, le=8, description="How many parallel arms this race opens (each gets its own outgoing edge handle: branch_0, branch_1, …)")
    winner_event_types: list[str] = Field(
        default_factory=lambda: ["message.received", "deal.created"],
        description="An event matching any of these from a branch declares that branch the winner",
    )
    timeout_hours: int = Field(168, ge=1, le=720, description="If no winner emerges in this window, all branches are cancelled and the 'timeout' handle fires")


def _race_handles(branches: int) -> tuple[NodeHandle, ...]:
    arms = tuple(NodeHandle(f"branch_{i}", f"Arm {i} of the race") for i in range(branches))
    return arms + (NodeHandle("timeout", "No branch produced a winning event before the timeout"),)


# We register the manifest with the max branch count's handles; the runtime
# only forwards lead context to the configured-N arms.
MANIFEST = NodeManifest(
    type="flow.race",
    category=NodeCategory.FLOW,
    summary="Open N parallel branches; first to produce a winning event wins, others cancel",
    config_schema=RaceConfig,
    output_handles=_race_handles(8),
    side_effect=SideEffect.READ,
    icon="git-merge",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = RaceConfig(**ctx.config)
    return NodeResult(
        handle="branch_0",
        telemetry={"branches": cfg.branches, "winner_event_types": cfg.winner_event_types, "timeout_hours": cfg.timeout_hours},
    )


register(MANIFEST, execute)
