"""Race N branches — first arm to re-converge wins, the others are cancelled.

Used for "first path to finish wins" patterns (e.g. try email AND LinkedIn in
parallel; whichever completes its arm first proceeds, the slower one is dropped).

Semantics (implemented in the transition worker, alongside flow.for_each/join):
the worker spawns one child lead per ``branch_*`` outgoing edge. Each child walks
its arm in parallel. Wire every arm to a shared ``flow.join``; the FIRST child to
reach that join WINS — the parent advances down the race's ``done`` edge and the
losing siblings are set to status='cancelled'. If no arm reaches the join within
``timeout_hours``, the orchestrator fires the ``timeout`` handle.

This is "join, but first-instead-of-all" — it reuses the same proven, idempotent
fan-out/join machinery as flow.for_each (parent parks at status='waiting'; the
join barrier releases the parent). Winner selection is structural (first arm to
re-converge), not event-pattern matching — deterministic and traceable.

Wiring:
  - branch_0 … branch_{N-1}  → the start of each parallel arm
  - every arm ends at the SAME flow.join
  - the flow.join's downstream is the "winner continues here" path (the worker
    advances the parent down the race's ``done`` edge to it)
  - timeout                  → fallback path if no arm finishes in time
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
    branches: int = Field(
        2, ge=2, le=8,
        description="How many parallel arms this race opens (each gets its own outgoing edge handle: branch_0, branch_1, …). Wire every arm to a shared flow.join.",
    )
    timeout_hours: int = Field(
        168, ge=1, le=720,
        description="If no arm reaches the join in this window, the 'timeout' handle fires and remaining arms are cancelled.",
    )


def _race_handles(branches: int) -> tuple[NodeHandle, ...]:
    arms = tuple(NodeHandle(f"branch_{i}", f"Start of parallel arm {i}") for i in range(branches))
    return arms + (
        NodeHandle("done", "Winner path — the parent advances here when the first arm re-converges at the join"),
        NodeHandle("timeout", "No arm finished before the timeout; remaining arms cancelled"),
    )


# Registered with the max branch count's handles; the runtime only spawns a
# child per branch_* edge the operator actually wired.
MANIFEST = NodeManifest(
    type="flow.race",
    category=NodeCategory.FLOW,
    summary="Open N parallel arms; first to re-converge at the join wins, others cancel",
    config_schema=RaceConfig,
    output_handles=_race_handles(8),
    side_effect=SideEffect.READ,
    icon="git-merge",
)


async def execute(ctx: NodeContext) -> NodeResult:
    # Routing is performed by the transition worker's _race_fan_out (it creates
    # the per-arm child leads and walks each branch_* edge). Like flow.for_each,
    # execute() only validates config + reports intent for telemetry.
    cfg = RaceConfig(**ctx.config)
    return NodeResult(
        handle="branch_0",
        telemetry={"branches": cfg.branches, "timeout_hours": cfg.timeout_hours},
    )


register(MANIFEST, execute)
