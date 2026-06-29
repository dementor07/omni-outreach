"""Composer authoring extensions — multi-channel, reply-window, AI-compose.

Three additive authoring gaps, each pinned so the composer keeps emitting a
runnable graph:

  REPLIED-WINDOW-001       — the condition.replied window is operator-set per
                             step (was hardcoded 365), default 30.
  MULTI-CHANNEL-AUTHOR-001 — a message step can be any of the 7 person channels,
                             not just email/linkedin; voice continues on `placed`.
  COMPOSE-WIRE-001         — a step can be AI-composed: an ai.compose node is
                             auto-wired before the send and the body is {{ai_draft}}.

All three stay ADDITIVE: a plain email/linkedin spec compiles exactly as before.
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


def _src() -> CampaignSourceSpec:
    return CampaignSourceSpec(provider="searxng", query="fintech founders")


def _edges(g):
    return {(e.source, e.source_handle, e.target) for e in g.edges}


# ── REPLIED-WINDOW-001 ───────────────────────────────────────────────────────


def test_reply_window_is_operator_set():
    g = compile_campaign_spec(CampaignSpec(name="rw", target_contacts=5, sources=[_src()], messages=[
        MessageStepSpec(channel="linkedin", mode="dm", message_template="hi", reply_window_days=14),
        MessageStepSpec(channel="linkedin", mode="dm", message_template="follow"),
    ]))
    windows = sorted(n.config["window_days"] for n in g.nodes if n.node_type == "condition.replied")
    assert windows[0] == 14, "first step's custom reply window must flow into condition.replied"


def test_reply_window_defaults_to_30_not_365():
    g = compile_campaign_spec(CampaignSpec(name="rw2", target_contacts=5, sources=[_src()], messages=[
        MessageStepSpec(channel="linkedin", mode="dm", message_template="hi"),
        MessageStepSpec(channel="linkedin", mode="dm", message_template="follow"),
    ]))
    w = [n.config["window_days"] for n in g.nodes if n.node_type == "condition.replied"]
    assert w and all(x == 30 for x in w), f"default reply window should be 30, got {w}"


# ── MULTI-CHANNEL-AUTHOR-001 ─────────────────────────────────────────────────


@pytest.mark.parametrize("chan", ["sms", "whatsapp", "instagram", "telegram"])
def test_body_template_channels_compile(chan):
    g = compile_campaign_spec(CampaignSpec(name=chan, target_contacts=5, sources=[_src()], messages=[
        MessageStepSpec(channel=chan, body_template="hey {{contact.first_name}}"),
    ]))
    node = next(n for n in g.nodes if n.node_type == f"channel.{chan}")
    assert node.config["body_template"] == "hey {{contact.first_name}}"


def test_voice_step_compiles_and_continues_on_placed():
    g = compile_campaign_spec(CampaignSpec(name="v", target_contacts=5, sources=[_src()], messages=[
        MessageStepSpec(channel="voice", retell_agent_id="agent_123"),
        MessageStepSpec(channel="linkedin", mode="dm", message_template="after the call"),
    ]))
    types = {n.node_type for n in g.nodes}
    assert "channel.voice" in types
    voice_node = next(n for n in g.nodes if n.node_type == "channel.voice")
    assert voice_node.config["retell_agent_id"] == "agent_123"
    # the sequence continuation must hang off `placed`, not `sent` (voice never
    # emits `sent`) — otherwise a voice step in a sequence dead-ends.
    assert any(s == voice_node.key and h == "placed" for s, h, _t in _edges(g)), (
        "voice step must continue on the `placed` handle"
    )


def test_voice_rejects_body_and_ai_compose():
    with pytest.raises(ValueError, match="retell_agent_id"):
        MessageStepSpec(channel="voice")  # no agent
    with pytest.raises(ValueError, match="ai_compose is not valid on a voice"):
        MessageStepSpec(channel="voice", retell_agent_id="a", ai_compose="draft it")


# ── COMPOSE-WIRE-001 ─────────────────────────────────────────────────────────


def test_ai_compose_inserts_compose_node_before_send():
    g = compile_campaign_spec(CampaignSpec(name="cw", target_contacts=5, sources=[_src()], messages=[
        MessageStepSpec(channel="email", ai_compose="a warm 2-line intro", ai_tone="warm"),
    ]))
    edges = _edges(g)
    assert any(n.node_type == "ai.compose" for n in g.nodes), "ai.compose node must be inserted"
    # the step's predecessor targets the compose node; compose feeds the send.
    assert ("create_contact", "default", "ai_compose_1") in edges
    assert ("ai_compose_1", "default", "message_1") in edges
    assert ("ai_compose_1", "on_error", "end_sequence_complete") in edges
    msg = next(n for n in g.nodes if n.key == "message_1")
    assert msg.config["body_template"] == "{{ai_draft}}", "AI-composed body must be the generated draft"
    compose = next(n for n in g.nodes if n.node_type == "ai.compose")
    assert compose.config["instruction"] == "a warm 2-line intro"
    assert compose.config["tone"] == "warm"


def test_ai_compose_relaxes_template_requirement():
    # an email step normally requires subject+body; with ai_compose it doesn't.
    step = MessageStepSpec(channel="email", ai_compose="draft a follow-up")
    assert step.ai_compose == "draft a follow-up"
    # but a linkedin INVITE can't be AI-composed (needs a real first line).
    with pytest.raises(ValueError, match="invite"):
        MessageStepSpec(channel="linkedin", mode="invite", ai_compose="x")


def test_plain_email_linkedin_spec_unchanged():
    # ADDITIVE guarantee: a spec using none of the new fields compiles a graph
    # whose message nodes are exactly the channel nodes (no ai.compose injected).
    g = compile_campaign_spec(CampaignSpec(name="plain", target_contacts=5, sources=[_src()], messages=[
        MessageStepSpec(channel="email", subject_template="s", body_template="b"),
        MessageStepSpec(channel="linkedin", mode="dm", message_template="m"),
    ]))
    assert not any(n.node_type == "ai.compose" for n in g.nodes)
    assert ("create_contact", "default", "message_1") in _edges(g)
