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


def test_distance_resolver_classifies_first_degree():
    body = _rs_fn("linkedin_first_degree")
    # resolves via /users/{public_id} and reads network_distance.
    assert "/api/v1/users/" in body
    assert "network_distance" in body
    # 1st-degree (DISTANCE_1 / FIRST_DEGREE) => true; anything else => false.
    assert "FIRST" in body and "'1'" in body
    # unknown/resolve-failure => None (fail-open: a transient glitch must not
    # block a legitimately-connected recipient).
    assert "return None" in body or "None" in body


def test_gate_only_opens_chat_for_first_degree_linkedin():
    body = _rs_fn("send_chat")
    # the gate runs only for LinkedIn DM (chat_id_col == "chat_id") opening a NEW
    # chat — WhatsApp/IG/TG and existing threads skip it.
    assert 'chat_id_col == "chat_id"' in body
    assert "linkedin_first_degree(" in body
    # a confirmed non-connection is HELD (skipped, not a burned send) and routed
    # to the not_connected handle.
    assert 'Some(false)' in body
    assert 'common::skipped(command, "not_connected")' in body
    assert 'next_handle".to_string(), json!("not_connected")' in body


def test_gate_runs_before_the_chat_post():
    body = _rs_fn("send_chat")
    gate = body.find("linkedin_first_degree(")
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
