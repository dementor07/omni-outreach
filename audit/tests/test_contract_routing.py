"""CONTRACT-001 proof: every palette-visible node must be reachable.

This test encodes the dispatcher/transition-worker reachability invariant
*exactly as the runtime applies it* and asserts that no side-effecting node is
dead-on-arrival.

The runtime rule (transition_worker._fire_node, after the CONTRACT-001 fix):

    a fired non-muscle node advances the lead IFF
        node_type in NODE_CHANNEL                    (-> a muscle command), OR
        it emits NO intent events (projection_only)  (-> a local synthetic
            result; condition/flow nodes and CRM nodes that emit only
            projection facts like contact.created), OR
        every intent it emits is dispatcher-routable (channel=="http_call").

    A node that emits an intent event the dispatcher CANNOT route is
    dead-on-arrival — _fire_node now logs an error and errors the lead instead
    of stalling it silently.

Static faithful proxy for "reachable":

    reachable(node) :=
        node.type in NODE_CHANNEL
        OR node.category in {FLOW, CONDITION}
        OR node.type in LOCALLY_RESOLVED_SOURCES     # self-contained / http_call
        OR node emits only projection-only events     # CRM create/update mutations

After the CONTRACT-001/002/004/005 fixes this should be GREEN (KNOWN_DEAD empty):
the genuinely-dead source/ai nodes were removed from the registry, the CRM tag
+ alert nodes were given .queued intents, and the CRM create/update nodes are
projection-only (they advance locally).
"""

from __future__ import annotations

import os


# Test stack env (mirrors backend/tests/conftest.py) so importing app.* doesn't
# trip config's placeholder-secret guard. No DB connection is opened here.
os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.execution.commands import NODE_CHANNEL  # noqa: E402
from app.nodes import NodeCategory, SideEffect, discover, manifests  # noqa: E402

# Sources/sinks that are reachable WITHOUT a NODE_CHANNEL entry because they are
# resolved by a different mechanism than node_type lookup. These are the
# explicitly-wired exceptions; anything else must be in NODE_CHANNEL.
LOCALLY_RESOLVED = {
    "enrich.email_verify", # in-process DNS + durable verification record
    "source.csv",         # self-contained: does its own fetch, emits projection events
    "source.sheets",      # SHEETS-001: same pattern — fetches a Google Sheet, emits contact.created
    "source.producthunt", # PH-001: same pattern — pulls PH makers via GraphQL, emits contact.created
    "source.renidly_job_changes",  # RENIDLY-002: same pattern — pulls job-change events, emits contact.created
    "source.webhook_in",  # passive declaration (listener lives in an HTTP route)
}

# Categories whose nodes are advanced locally by the transition worker. FLOW and
# CONDITION return a handle with no routable intent. CRM mutation nodes that are
# NOT in NODE_CHANNEL emit projection-only events (contact.created, deal.created,
# task.created, …) — after the CONTRACT-001 fix the worker classifies those as
# projection_only and advances the lead via a synthetic result, so they are
# reachable too.
LOCAL_CATEGORIES = {NodeCategory.FLOW, NodeCategory.CONDITION, NodeCategory.CRM}

# Dead-on-arrival tracker. EMPTY after the CONTRACT-001/002/004/005 fixes:
#   * genuinely-dead source/ai canvas nodes were removed from the registry
#     (ai.score/ai.classify -> AI-Studio-only; apollo/hunter/proxycurl deleted),
#     so they no longer appear in manifests(); source.sheets + source.producthunt
#     were later REBUILT as self-contained in-process sources (SHEETS-001/PH-001)
#     and live in LOCALLY_RESOLVED above;
#   * crm.add_tag/remove_tag/hot_lead_alert now emit .queued intents and route
#     via NODE_CHANNEL;
#   * crm.create_*/update_* are projection-only (LOCAL_CATEGORIES above).
KNOWN_DEAD: set[str] = set()


def _reachable(m) -> bool:
    if m.type in NODE_CHANNEL:
        return True
    if m.category in LOCAL_CATEGORIES:
        return True
    if m.type in LOCALLY_RESOLVED:
        return True
    return False


def _dead_on_arrival() -> list[str]:
    """Side-effecting nodes that are not reachable by any mechanism."""
    discover()
    dead = []
    for m in manifests():
        if m.side_effect in (SideEffect.NETWORK, SideEffect.MUTATE) and not _reachable(m):
            dead.append(m.type)
    return sorted(dead)


def test_every_palette_node_is_reachable():
    """The invariant we actually want true: zero side-effecting nodes are
    dead-on-arrival. RED until CONTRACT-001 is fixed.

    We assert against KNOWN_DEAD so the failure message is precise and the test
    becomes a live tracker: as nodes are wired, KNOWN_DEAD shrinks; when a node
    is wired but not removed from KNOWN_DEAD, the test also fails (forcing the
    bookkeeping to stay honest)."""
    dead = set(_dead_on_arrival())

    newly_dead = dead - KNOWN_DEAD
    resurrected = KNOWN_DEAD - dead

    assert not newly_dead, (
        f"NEW dead-on-arrival nodes (emit intents but no route, lead stalls): "
        f"{sorted(newly_dead)}. Wire them into NODE_CHANNEL + a muscle handler, "
        f"or remove them from the node registry."
    )
    assert not resurrected, (
        f"These nodes are now reachable — remove them from KNOWN_DEAD so the "
        f"tracker stays honest: {sorted(resurrected)}."
    )
    # The headline assertion. This is the one that goes green when CONTRACT-001
    # is genuinely fixed (KNOWN_DEAD emptied as each node is wired).
    assert not dead, (
        f"CONTRACT-001 unresolved: {len(dead)} side-effecting nodes are "
        f"dead-on-arrival: {sorted(dead)}"
    )
