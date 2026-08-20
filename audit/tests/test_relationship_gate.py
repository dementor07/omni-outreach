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
    # INVITE-TRUTH-001 moved the lookup into linkedin_profile_state, which
    # answers two more questions off the SAME call: the raw distance string, and
    # whether an invitation is already outstanding. linkedin_profile_check is now
    # a thin delegation kept for the callers that only want degree + id.
    body = _rs_fn("linkedin_profile_state")
    # ONE /users/{public_id} lookup answers all of it.
    assert "/api/v1/users/" in body
    assert "network_distance" in body
    assert "provider_id" in body, "the lookup must also return the provider_id (DM-ATTENDEE-001)"
    # 1st-degree (DISTANCE_1 / FIRST_DEGREE) => true; anything else => false.
    assert "FIRST" in body and "'1'" in body
    # unknown/resolve-failure => fail OPEN on the degree, so a lookup outage
    # never silently blocks every send.
    assert "(None, None, String::new(), false)" in body

    # the wrapper must stay a pure delegation — two resolvers that could drift
    # apart is how the gate ends up disagreeing with the invite.
    wrapper = _rs_fn("linkedin_profile_check")
    assert "linkedin_profile_state(" in wrapper
    assert "/api/v1/users/" not in wrapper


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


def test_invite_skips_when_already_connected():
    # SMART-INVITE-001: an invite to an existing 1st-degree connection is a
    # redundant no-op that strands the lead at await-acceptance. The handler must
    # resolve distance FIRST and, when already connected, SKIP the invite and
    # route via the `already_connected` handle (the engine owns this invariant).
    body = _rs_fn("handle_linkedin_invite")
    # INVITE-TRUTH-001 widened this read to also report whether an invitation is
    # already outstanding, so the invite path calls the four-value variant.
    assert "linkedin_profile_state(" in body, "the invite must resolve distance before firing"
    assert "already_connected" in body
    # the skip must come BEFORE the /users/invite POST (don't fire a redundant invite).
    skip = body.find("already_connected")
    invite_post = body.find("/api/v1/users/invite")
    assert skip != -1 and invite_post != -1 and skip < invite_post, (
        "the already-connected skip must precede the invite POST"
    )
    # it's a skipped (non-send) routed via next_handle, and it persists the
    # resolved provider_id + distance so downstream nodes see them.
    assert 'common::skipped(command, "already_connected")' in body
    assert 'next_handle".to_string(), json!("already_connected")' in body
    assert "linkedin_distance" in body and "provider_id" in body


def test_linkedin_manifests_declare_smart_handles():
    # TAXONOMY-001: the smart handles live on the ACTION that can emit them —
    # already_connected is the invite's skip; not_connected/no_thread are the
    # DM's relationship gate + degraded thread. InMail/profile-view emit neither.
    invite = (REPO / "backend/app/nodes/channels/linkedin_invite.py").read_text(encoding="utf-8")
    assert 'NodeHandle("already_connected"' in invite
    dm = (REPO / "backend/app/nodes/channels/linkedin_dm.py").read_text(encoding="utf-8")
    for h in ("not_connected", "no_thread"):
        assert f'NodeHandle("{h}"' in dm, f"channel.linkedin_dm must declare the {h} handle"


def test_unwired_not_connected_handle_ends_honestly_not_completed():
    # a held lead whose campaign didn't wire a not_connected branch must NOT be
    # recorded as 'completed' (a false success polluting metrics + the objective
    # loop). It ends honestly.
    assert '"not_connected": "ended"' in TW_SRC
