"""TONE-PRESET-001 wiring — the seams the pure renderer plugs into.

tone_prompt rendering is locked in test_tone_prompt.py. THIS pins the runtime
wiring so a refactor can't unhook it:

  - ai.compose forwards tone_id in its queued-event payload;
  - the dispatcher resolves a tone_id into payload.tone_instructions (Python
    side — the muscle is stateless) and is best-effort (never wedges a send);
  - the Rust muscle USES payload.tone_instructions, with a flat-tone fallback;
  - the composer carries ai_tone_id onto the ai.compose node it inserts.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

REPO = Path(__file__).resolve().parents[2]
DISPATCH_SRC = (REPO / "backend/app/execution/dispatcher.py").read_text(encoding="utf-8")
RUST_SRC = (REPO / "backend-rust/src/handlers/transform.rs").read_text(encoding="utf-8")


def test_ai_compose_node_forwards_tone_id():
    from app.nodes import discover, get

    discover()
    manifest, _fn = get("ai.compose")
    props = manifest.config_schema.model_json_schema()["properties"]
    assert "tone_id" in props, "ai.compose config must accept tone_id"


def test_dispatcher_resolves_tone_before_build_command():
    # the resolution must run for AI_COMPOSE with a tone_id, and BEFORE the
    # command is built (so tone_instructions is in the payload the muscle gets).
    body = DISPATCH_SRC
    assert "_resolve_tone_into_payload" in body
    resolve_at = body.find("await _resolve_tone_into_payload")
    build_at = body.find("await commands.build_command")
    assert resolve_at != -1 and build_at != -1 and resolve_at < build_at, (
        "tone resolution must happen before build_command"
    )
    # gated on the AI_COMPOSE channel + a present tone_id.
    assert "ChannelType.AI_COMPOSE" in body and 'command_payload.get("tone_id")' in body


def test_tone_resolution_is_best_effort():
    # a tone lookup failure must NOT wedge the compose — the helper swallows and
    # falls back to the flat tone (the body keeps a broad except + a log).
    m = re.search(r"async def _resolve_tone_into_payload\(.*?(?=\nasync def |\ndef )", DISPATCH_SRC, re.S)
    assert m, "_resolve_tone_into_payload not found"
    helper = m.group(0)
    assert "tone_instructions" in helper
    assert "except Exception" in helper, "tone resolution must be best-effort (never wedge a send)"
    assert "build_tone_system_prompt" in helper


def test_rust_uses_tone_instructions_with_fallback():
    # handle_ai_compose must prefer payload.tone_instructions, else the flat tone.
    assert 'get("tone_instructions")' in RUST_SRC, "muscle must read tone_instructions"
    # the fallback flat-tone format string must still exist.
    assert "You write {tone} outbound {channel} messages" in RUST_SRC


def test_composer_carries_ai_tone_id_onto_compose_node():
    from app.services.campaign_composer import (
        CampaignSourceSpec,
        CampaignSpec,
        MessageStepSpec,
        compile_campaign_spec,
    )

    g = compile_campaign_spec(
        CampaignSpec(
            name="tone",
            target_contacts=5,
            sources=[CampaignSourceSpec(provider="searxng", query="x")],
            messages=[MessageStepSpec(channel="email", ai_compose="warm intro", ai_tone_id=2)],
        )
    )
    compose = next(n for n in g.nodes if n.node_type == "ai.compose")
    assert compose.config.get("tone_id") == 2, "ai_tone_id must flow onto the ai.compose node"
