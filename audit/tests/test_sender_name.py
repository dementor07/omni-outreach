"""SENDER-NAME-001 — a draft must be signed by the seat that actually sends it.

Campaign 2 shipped drafts signed "Johnsy" from Leena's seat because the name was
a literal in the node instruction. The seat is knowable at compose time: a
LinkedIn DM is pinned to whichever seat sent the invite, which commands.py
already reads as custom_fields.invite_account_id.

Also locks the prompt hygiene that caused the em dashes: the muscle's own system
prompt must not contain the punctuation it asks the model to avoid.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.execution import dispatcher  # noqa: E402

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
TRANSFORM_RS = ROOT / "backend-rust/src/handlers/transform.rs"


def _instruction(text: str) -> dict:
    return {"instruction": text}


@pytest.mark.asyncio
async def test_sender_token_resolves_to_the_seat_that_sent_the_invite(monkeypatch):
    async def fake_fetch_one(_q, *args):
        assert args[1] == "seat-leena"
        return {"display_name": "Leena Jose"}

    monkeypatch.setattr(dispatcher, "fetch_one", fake_fetch_one)
    payload = _instruction("sign as {{sender_first_name}} / {{sender_name}}")
    await dispatcher._resolve_sender_into_payload(
        "ws", payload, {"custom_fields": {"invite_account_id": "seat-leena"}}
    )
    assert payload["instruction"] == "sign as Leena / Leena Jose"


@pytest.mark.asyncio
async def test_a_different_seat_gets_a_different_signature(monkeypatch):
    """The exact defect: two seats on one campaign must not share a signature."""

    async def fake_fetch_one(_q, *args):
        return {"display_name": "Johnsy George"}

    monkeypatch.setattr(dispatcher, "fetch_one", fake_fetch_one)
    payload = _instruction("{{sender_first_name}}")
    await dispatcher._resolve_sender_into_payload(
        "ws", payload, {"custom_fields": {"invite_account_id": "seat-johnsy"}}
    )
    assert payload["instruction"] == "Johnsy"


@pytest.mark.asyncio
async def test_one_seat_on_the_campaign_is_unambiguous(monkeypatch):
    """No pinned invite seat, but a single-seat campaign leaves nothing to guess."""

    async def fake_fetch_one(_q, *_a):
        return None

    async def fake_fetch_all(_q, *_a):
        return [{"display_name": "Leena Jose"}]

    monkeypatch.setattr(dispatcher, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(dispatcher, "fetch_all", fake_fetch_all)
    payload = _instruction("{{sender_first_name}}")
    await dispatcher._resolve_sender_into_payload("ws", payload, {"workflow_id": "wf"})
    assert payload["instruction"] == "Leena"


@pytest.mark.asyncio
async def test_two_seats_and_no_pin_refuses_to_guess(monkeypatch):
    """Guessing is how the wrong name shipped. An unresolved token is dropped by
    strip_signature, which loses a first name rather than attributing the message
    to someone who did not send it."""

    async def fake_fetch_one(_q, *_a):
        return None

    async def fake_fetch_all(_q, *_a):
        return [{"display_name": "Leena Jose"}, {"display_name": "Johnsy George"}]

    monkeypatch.setattr(dispatcher, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(dispatcher, "fetch_all", fake_fetch_all)
    payload = _instruction("{{sender_first_name}}")
    await dispatcher._resolve_sender_into_payload("ws", payload, {"workflow_id": "wf"})
    assert payload["instruction"] == "{{sender_first_name}}"


@pytest.mark.asyncio
async def test_an_instruction_without_the_token_never_touches_the_database(monkeypatch):
    async def explode(*_a, **_k):
        raise AssertionError("no lookup should happen without a sender token")

    monkeypatch.setattr(dispatcher, "fetch_one", explode)
    monkeypatch.setattr(dispatcher, "fetch_all", explode)
    payload = _instruction("write a nice message")
    await dispatcher._resolve_sender_into_payload("ws", payload, {"custom_fields": {}})
    assert payload["instruction"] == "write a nice message"


@pytest.mark.asyncio
async def test_a_lookup_failure_never_wedges_the_compose(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("database is having a day")

    monkeypatch.setattr(dispatcher, "fetch_one", boom)
    payload = _instruction("{{sender_first_name}}")
    await dispatcher._resolve_sender_into_payload(
        "ws", payload, {"custom_fields": {"invite_account_id": "seat"}}
    )
    assert payload["instruction"] == "{{sender_first_name}}"


def test_the_muscle_never_models_the_punctuation_it_bans():
    """The compose system prompt contained an em dash while the operator
    instructions asked for none. Every first-DM draft came back with three."""
    source = TRANSFORM_RS.read_text(encoding="utf-8")
    prompt_lines = [
        line
        for line in source.splitlines()
        if '"' in line and not line.strip().startswith("//")
        and ("Output is the message body" in line or "Output the answer only" in line)
    ]
    assert prompt_lines, "compose/transform system prompts not found"
    for line in prompt_lines:
        assert EM_DASH not in line, f"em dash in a prompt string: {line.strip()}"
        assert EN_DASH not in line, f"en dash in a prompt string: {line.strip()}"


def test_the_muscle_states_the_dash_ban_in_its_default_system_prompt():
    source = TRANSFORM_RS.read_text(encoding="utf-8")
    assert "Never use em dashes or en dashes anywhere in the output" in source
