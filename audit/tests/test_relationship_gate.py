"""Pre-send LinkedIn relationship gate (RELGATE-001).

A LinkedIn DM to a non-1st-degree connection 403s (subscription_required) —
proven live. Blindly POSTing burns the attempt and (in a sequence) wastes the
invite→wait→DM choreography. The muscle must resolve the recipient's
network_distance BEFORE opening a new chat and, when confirmed not connected,
route to a `not_connected` handle (no 403) so the campaign can branch.

Pins both halves: the muscle gate + the worker's honest terminalization of an
unwired `not_connected` handle. Static/source-faithful (house style).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
UNIPILE_RS = (REPO / "backend-rust/src/handlers/unipile.rs").read_text(encoding="utf-8")
TW_SRC = (REPO / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")


def _rs_fn(name: str) -> str:
    m = re.search(rf"(?:pub )?(?:async )?fn {name}\(.*?(?=\n(?:pub )?(?:async )?fn |\Z)", UNIPILE_RS, re.S)
    assert m, f"rust fn {name} not found"
    return m.group(0)


def test_distance_resolver_classifies_first_degree_and_returns_provider_id():
    body = _rs_fn("linkedin_profile_check")
    # ONE /users/{public_id} lookup answers both: degree + provider_id.
    assert "/api/v1/users/" in body
    assert "network_distance" in body
    assert "provider_id" in body, "the lookup must also return the provider_id (DM-ATTENDEE-001)"
    # 1st-degree (DISTANCE_1 / FIRST_DEGREE) => true; anything else => false.
    assert "FIRST" in body and "'1'" in body
    # unknown/resolve-failure => (None, None) (fail-open on the degree).
    assert "(None, None)" in body


def test_gate_only_opens_chat_for_first_degree_linkedin():
    body = _rs_fn("send_chat")
    # the gate runs only for LinkedIn DM (chat_id_col == "chat_id") opening a NEW
    # chat — WhatsApp/IG/TG and existing threads skip it.
    assert 'chat_id_col == "chat_id"' in body
    assert "linkedin_profile_check(" in body
    # a confirmed non-connection is HELD (skipped, not a burned send) and routed
    # to the not_connected handle.
    assert 'Some(false)' in body
    assert 'common::skipped(command, "not_connected")' in body
    assert 'next_handle".to_string(), json!("not_connected")' in body


def test_dm_resolves_attendee_from_linkedin_url_when_payload_has_none():
    # DM-ATTENDEE-001: an outbound-first DM carries only linkedin_url (no
    # pre-resolved provider_id). The attendee must fall back to the provider_id
    # resolved from the profile lookup, or the chat can't be opened.
    body = _rs_fn("send_chat")
    assert "resolved_provider_id" in body
    assert ".or_else(|| resolved_provider_id.clone())" in body
    # the payload id still wins when present (a follow-up / sequencer-resolved id).
    assert 'command.payload["attendee_identifier"]' in body
    assert 'command.payload["provider_id"]' in body


def test_gate_runs_before_the_chat_post():
    body = _rs_fn("send_chat")
    gate = body.find("linkedin_profile_check(")
    post = body.find("/api/v1/chats", body.find("attendees_ids"))
    assert gate != -1 and post != -1 and gate < post, (
        "the relationship check must precede opening the chat — otherwise the "
        "403 is already burned"
    )


def test_unwired_not_connected_handle_ends_honestly_not_completed():
    # a held lead whose campaign didn't wire a not_connected branch must NOT be
    # recorded as 'completed' (a false success polluting metrics + the objective
    # loop). It ends honestly.
    assert '"not_connected": "ended"' in TW_SRC
