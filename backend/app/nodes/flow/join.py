"""join — the barrier sibling of ``flow.for_each``. Regroups N child leads back
to one once they all complete.

When a child lead spawned by a ``flow.for_each`` reaches a ``flow.join``, the
transition worker increments the parent's ``fanout_done`` counter and ends the
child (it has done its work — its data was persisted by whatever sink ran
between the for_each and here). When ``fanout_done`` reaches the parent's
``fanout_total``, the barrier releases: the parent lead advances on the
for_each's ``done`` edge, carrying on as a single entity.

Like ``flow.for_each``, the barrier accounting lives in the transition worker
(``_join_arrive``) because it mutates lead rows. ``execute`` is a no-op marker.

Handles:
  default — the parent walks this once the barrier releases (children never do)
"""

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


class JoinConfig(BaseModel):
    pass


MANIFEST = NodeManifest(
    type="flow.join",
    category=NodeCategory.FLOW,
    summary="Barrier — wait for all for_each children, then continue as one lead",
    config_schema=JoinConfig,
    output_handles=(NodeHandle("default", "Released once all children have arrived"),),
    side_effect=SideEffect.READ,
    icon="git-merge",
)


async def execute(ctx: NodeContext) -> NodeResult:
    # Barrier accounting is performed by the transition worker (_join_arrive).
    # Reaching here as a child is handled before execute() is ever called.
    return NodeResult(handle="default")


register(MANIFEST, execute)
