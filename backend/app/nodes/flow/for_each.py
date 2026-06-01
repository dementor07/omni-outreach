"""for_each — interior fan-out. The only primitive that turns one entity into
many *in the middle* of a graph (sources fan out only at the start).

A lead arriving here carries a collection in ``custom_fields[items_key]`` (put
there by the upstream node — e.g. a Serper search wrote ``people``). The
transition worker reads that collection and, for each element, spawns a **child
lead** (lineage back to this lead) that walks the ``each`` edge. The arriving
lead itself parks; when every child reaches the matching ``flow.join`` the
parent advances on ``done``.

The fan-out itself lives in the transition worker (``_fan_out``), because that
is where lead rows are created and edges are walked. ``execute`` only validates
config and reports intent — like ``flow.split``, the runtime does the routing.

Handles:
  each   — walked once per element (by each spawned child lead)
  done   — walked once by the parent after the join barrier releases
  empty  — collection was missing/empty: nothing to fan out, skip to done-side
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


class ForEachConfig(BaseModel):
    items_key: str = Field(
        description="Key in the lead's custom_fields holding the list to iterate "
        "(e.g. 'people' written by an upstream search node)",
    )
    item_field: str = Field(
        "item",
        description="custom_fields key each child lead receives its element under",
    )
    max_items: int = Field(
        500, ge=1, le=5000, description="Safety cap on children spawned per parent"
    )


MANIFEST = NodeManifest(
    type="flow.for_each",
    category=NodeCategory.FLOW,
    summary="Fan one lead into one child per element of a collection (interior map)",
    config_schema=ForEachConfig,
    output_handles=(
        NodeHandle("each", "Walked once per element by a spawned child lead"),
        NodeHandle("done", "Walked by the parent once all children reach the join"),
        NodeHandle("empty", "Collection was empty — nothing to iterate"),
    ),
    side_effect=SideEffect.READ,
    icon="repeat",
)


async def execute(ctx: NodeContext) -> NodeResult:
    # Routing is performed by the transition worker's _fan_out (it creates the
    # child lead rows and walks the `each` edge per element). Here we only
    # surface whether there was anything to iterate, for telemetry.
    cfg = ForEachConfig(**ctx.config)
    items = (ctx.lead.get("custom_fields") or {}).get(cfg.items_key) or []
    n = len(items) if isinstance(items, list) else 0
    return NodeResult(handle="each" if n else "empty", telemetry={"fanout": n})


register(MANIFEST, execute)
