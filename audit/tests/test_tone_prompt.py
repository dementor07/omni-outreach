"""TONE-PRESET-001 — the tone-preset → system-prompt renderer.

Locks that a preset's structured spec (the team's authored JSON) is faithfully
turned into prompt instructions: name + description, the word-count ceiling, the
voice/opening/value/closing sections, and the hard prohibitions (avoid +
anti-pitch). Pure renderer → no DB, no LLM. Also pins graceful degradation so a
malformed preset never wedges a compose.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

from app.services.tone_prompt import build_tone_system_prompt, word_count_bounds

_SEED = Path(__file__).resolve().parents[1].parent / "backend/app/data/message_tones.json"
_TONES = json.loads(_SEED.read_text(encoding="utf-8"))


def _tone(tone_id: int) -> dict:
    return next(t for t in _TONES if t["tone_id"] == tone_id)


def test_seed_has_all_twelve_tones():
    assert sorted(t["tone_id"] for t in _TONES) == list(range(1, 13))


@pytest.mark.parametrize("tone", _TONES, ids=lambda t: t["tone"])
def test_every_preset_renders_nonempty_with_name_and_length(tone):
    p = build_tone_system_prompt(tone, "email")
    assert tone["tone"] in p, "the tone name must appear in the prompt"
    assert "never exceed" in p, "the word-count ceiling must be enforced in the prompt"
    assert "message body ONLY" in p, "must instruct body-only output"


def test_word_count_bounds_from_spec():
    # tone 2 is the tight one: recommended 55, max 75.
    assert word_count_bounds(_tone(2)) == (55, 75)
    # tone 1: recommended 100, max 130.
    assert word_count_bounds(_tone(1)) == (100, 130)


def test_anti_pitch_rules_become_prohibitions():
    # the Event-Trigger tone has anti_pitch_rules that MUST surface as "NEVER".
    p = build_tone_system_prompt(_tone(2))
    assert "NEVER do the following" in p
    assert "Do NOT mention product" in p


def test_avoid_list_becomes_prohibitions():
    # every tone has an `avoid` list; it must render under the NEVER block.
    p = build_tone_system_prompt(_tone(1))
    assert "NEVER do the following" in p
    assert any(a.split(".")[0][:20] in p for a in _tone(1)["avoid"])


def test_followup_strategy_objects_are_flattened_not_crashing():
    # personalization/value lists are strings, but followup_strategies are objects;
    # the renderer must not choke on a tone that has them (it just isn't a rendered
    # section here, but _items must handle the mixed shape elsewhere).
    p = build_tone_system_prompt(_tone(2))
    assert isinstance(p, str) and len(p) > 200


def test_malformed_preset_degrades_gracefully():
    # missing everything but a name → still a usable, non-crashing prompt.
    p = build_tone_system_prompt({"tone": "Minimal"}, "linkedin")
    assert "Minimal" in p
    assert "never exceed" in p  # falls back to a sane default ceiling
    assert "linkedin" in p


def test_channel_is_reflected():
    p = build_tone_system_prompt(_tone(3), "linkedin")
    assert "linkedin" in p
