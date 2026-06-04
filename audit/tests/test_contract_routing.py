"""CONTRACT-001 proof: every palette-visible node must be reachable.

This test encodes the dispatcher/transition-worker reachability invariant
*exactly as the runtime applies it* and asserts that no side-effecting node is
dead-on-arrival.

The runtime rule (transition_worker._fire_node, line ~382):

    a fired node advances the lead IFF
        node_type in NODE_CHANNEL                 (-> a muscle command)
      OR result.events == []                      (-> a local synthetic result)

A node that emits an intent event but whose node_type is absent from
NODE_CHANNEL gets NEITHER -> the lead stalls silently. So the static, faithful
proxy for "reachable" is:

    reachable(node) :=
        node.type in NODE_CHANNEL
        OR node.category in {FLOW, CONDITION}        # never emit routable intents
        OR node.type in LOCALLY_RESOLVED_SOURCES     # known self-contained / http_call

Any SOURCE/AI/CHANNEL/CRM node with a NETWORK/MUTATE side-effect that fails all
three is dead-on-arrival.

This test is RED today (8 known dead nodes) and turns GREEN when CONTRACT-001 is
fixed — at which point finding CONTRACT-001 may flip to FIXED in the dashboard.
"""

from __future__ import annotations

import os

import pytest

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
    "source.serper",      # emits http_call.requested -> dispatcher routes via payload.channel
    "source.csv",         # self-contained: does its own fetch, emits projection events
    "source.webhook_in",  # passive declaration (listener lives in an HTTP route)
}

# Categories whose nodes are advanced locally by the transition worker (they
# return a handle and emit no routable intent), so they never need a channel.
LOCAL_CATEGORIES = {NodeCategory.FLOW, NodeCategory.CONDITION}

# The known dead-on-arrival set as of the audit (CONTRACT-001). The test treats
# these as the current expected-failures so the suite documents the gap until
# it's fixed; remove a node from here as it gets wired.
KNOWN_DEAD = {
    # --- stall with NOTHING (CONTRACT-001 HIGH): no route, no projection ---
    "ai.score",
    "ai.classify",
    "source.apollo",
    "source.hunter",
    "source.proxycurl",
    "source.sheets",
    "source.producthunt",
    # NOTE: crm.hot_lead_alert is NOT listed here — it IS in NODE_CHANNEL so this
    # static reachability check considers it routable. Its real defect is that
    # its emitted event_type never passes dispatcher._is_intent (CONTRACT-002),
    # which a separate event_type-suffix test must prove, not this one.
    # --- stall AFTER a projection lands (CONTRACT-004 MEDIUM): the lead still
    #     stalls because the node emits events but has no channel, even though
    #     its projection event is applied. The runtime mechanism is identical to
    #     CONTRACT-001 (the _fire_node guard fails both arms); the audit graded
    #     them lower only because *some* state is persisted. The test is the
    #     honest superset and tracks them too. ---
    "crm.create_contact",
    "crm.create_deal",
    "crm.update_deal",
    "crm.create_task",
}


def _reachable(m) -> bool:
    if m.type in NODE_CHANNEL:
        # hot_lead_alert is a special case: it IS in NODE_CHANNEL but its emitted
        # event_type ("lead.hot_alert") never passes dispatcher._is_intent, so it
        # is unreachable in practice. We treat NODE_CHANNEL membership as
        # reachable here and let the dedicated CONTRACT-002 test cover the
        # event_type-suffix gap.
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
