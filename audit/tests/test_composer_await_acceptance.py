"""CampaignSpec await_acceptance extension — the hardened invite flow, declared.

The composer is the full-funnel abstraction (sources -> companies -> people ->
enrichment -> contact -> optional messages). This pins the additive
await_acceptance extension that makes the hardened invite->wait->DM sequence
expressible WITHOUT rebuilding the abstraction, and guarantees it stays
additive: lead-gen-only and enrichment-only specs compile unchanged, messages
stay optional.
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

from app.services.campaign_composer import (
    CampaignSourceSpec,
    CampaignSpec,
    MessageStepSpec,
    compile_campaign_spec,
)


def _leadgen_source() -> CampaignSourceSpec:
    return CampaignSourceSpec(provider="searxng", query="fintech founders")


def test_leadgen_only_spec_still_compiles_no_messages():
    # the tool is also lead-gen + enrichment: a spec with NO messages must
    # compile a full funnel that ends at contact creation (additive guarantee).
    g = compile_campaign_spec(
        CampaignSpec(name="leadgen", target_contacts=10, sources=[_leadgen_source()])
    )
    types = {n.node_type for n in g.nodes}
    assert "crm.create_contact" in types
    assert not any(t.startswith("channel.") for t in types), "no messages => no send nodes"
    assert g.objective["metric"] == "contacts"


def test_enrichment_only_spec_compiles_unchanged():
    from app.services.campaign_composer import EnrichmentStageSpec

    g = compile_campaign_spec(
        CampaignSpec(
            name="enrich",
            target_contacts=10,
            sources=[_leadgen_source()],
            enrichment=[EnrichmentStageSpec(provider="apollo", connection_name="apollo-1")],
        )
    )
    types = [n.node_type for n in g.nodes]
    assert "ai.enrich" in types
    assert not any(t.startswith("channel.") for t in types)


def test_await_acceptance_compiles_the_wait_between_invite_and_next_step():
    g = compile_campaign_spec(
        CampaignSpec(
            name="hardened",
            target_contacts=10,
            sources=[_leadgen_source()],
            messages=[
                MessageStepSpec(
                    channel="linkedin", mode="invite", message_template="Hi",
                    await_acceptance=True, delay_after={"amount": 1, "unit": "minutes"},
                ),
                MessageStepSpec(channel="linkedin", mode="dm", message_template="Thanks!"),
            ],
        )
    )
    types = [n.node_type for n in g.nodes]
    assert "event.invite_accepted" in types, "await_acceptance must compile the wait node"
    edges = {(e.source, e.source_handle, e.target) for e in g.edges}
    # invite -> wait (on sent), wait -> delay (on accepted), wait -> end (timeout)
    assert ("message_1", "sent", "await_accept_1") in edges
    assert ("await_accept_1", "accepted", "delay_1") in edges
    assert ("await_accept_1", "timeout", "end_sequence_complete") in edges
    # the DM (message_2) is reached only AFTER the delay — never directly off the
    # invite. So we never DM before the connection is accepted.
    assert ("delay_1", "default", "message_2") in edges
    assert not any(s == "message_1" and t == "message_2" for s, _h, t in edges)
    # a non-connection / no-thread degrade from the invite send ends honestly.
    assert ("message_1", "not_connected", "end_sequence_complete") in edges
    # SMART-INVITE-001: an already-connected recipient skips the invite AND the
    # wait, going straight to the same delay->next-step the accepted path uses —
    # so invite->await->DM auto-navigates for connected people, no manual branch.
    assert ("message_1", "already_connected", "delay_1") in edges


def test_await_acceptance_rejected_on_non_invite_step():
    # the flag is only meaningful on a linkedin invite; anything else is a spec
    # error (caught at validation, not silently ignored).
    with pytest.raises(ValueError, match="await_acceptance"):
        MessageStepSpec(channel="linkedin", mode="dm", message_template="x", await_acceptance=True)
    with pytest.raises(ValueError, match="await_acceptance"):
        MessageStepSpec(
            channel="email", subject_template="s", body_template="b", await_acceptance=True
        )


def test_non_await_invite_keeps_the_plain_replied_flow():
    # an invite WITHOUT await_acceptance compiles like any message (replied-check
    # then delay) — backward compatible, no wait node injected.
    g = compile_campaign_spec(
        CampaignSpec(
            name="plain",
            target_contacts=10,
            sources=[_leadgen_source()],
            messages=[
                MessageStepSpec(channel="linkedin", mode="invite", message_template="Hi"),
                MessageStepSpec(channel="linkedin", mode="dm", message_template="Yo"),
            ],
        )
    )
    types = [n.node_type for n in g.nodes]
    assert "event.invite_accepted" not in types
    assert "condition.replied" in types
