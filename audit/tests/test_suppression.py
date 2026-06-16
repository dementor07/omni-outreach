"""T1 regression — contact-level suppression (DNC) enforced at outbound send.

The legacy `blacklists` table was dropped in migration 025; migration 031
rebuilds it as `omni_suppression_list` and the matcher in
`app.services.suppression` is enforced in `transition_worker._fire_node`
BEFORE any channel intent publishes. These tests cover the pure matcher (all
four kinds) + the wire-in invariant that the send seam actually calls it and
terminalizes 'suppressed' without publishing.

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from pathlib import Path

from app.services.suppression import match_suppression

BACKEND = Path(__file__).resolve().parents[2] / "backend"

CONTACT = {
    "email": "Jane@ACME.io",
    "phone": "+1 (555) 010-2020",
    "linkedin_url": "https://www.linkedin.com/in/jane-doe/",
}


def _rule(kind: str, value: str) -> dict:
    return {"kind": kind, "value": value}


# ── pure matcher ─────────────────────────────────────────────────────────────

def test_email_match_is_case_insensitive():
    blocked, reason = match_suppression(CONTACT, [_rule("email", "jane@acme.io")])
    assert blocked and reason == "email:jane@acme.io"


def test_domain_match_exact_and_subdomain():
    assert match_suppression(CONTACT, [_rule("domain", "acme.io")])[0]
    sub = {"email": "x@mail.acme.io"}
    assert match_suppression(sub, [_rule("domain", "acme.io")])[0]
    # a different domain does not match
    assert not match_suppression({"email": "x@other.com"}, [_rule("domain", "acme.io")])[0]


def test_phone_match_ignores_formatting():
    assert match_suppression(CONTACT, [_rule("phone", "15550102020")])[0]
    assert match_suppression(CONTACT, [_rule("phone", "+1-555-010-2020")])[0]


def test_linkedin_match_by_handle_or_fragment():
    assert match_suppression(CONTACT, [_rule("linkedin", "jane-doe")])[0]
    assert match_suppression(CONTACT, [_rule("linkedin", "linkedin.com/in/jane-doe")])[0]


def test_no_rules_and_no_contact_pass():
    assert match_suppression(CONTACT, []) == (False, None)
    assert match_suppression(None, [_rule("email", "x@y.com")]) == (False, None)


def test_unrelated_rule_does_not_match():
    blocked, _ = match_suppression(CONTACT, [_rule("email", "someone@else.com")])
    assert not blocked


# ── wire-in: the send seam enforces it ───────────────────────────────────────

def test_fire_node_enforces_suppression_before_publish():
    src = (BACKEND / "app" / "execution" / "transition_worker.py").read_text(encoding="utf-8")
    body = src.split("async def _fire_node", 1)[1]
    # the guard must run for outbound channels, terminalize 'suppressed', and
    # return BEFORE the publish_events call.
    assert "_OUTBOUND_SEND_CHANNELS" in body
    assert "suppression.is_suppressed" in body
    suppress_pos = body.find("is_suppressed")
    publish_pos = body.find("bus.publish_events")
    assert suppress_pos != -1 and publish_pos != -1
    assert suppress_pos < publish_pos, "DNC check must precede the channel intent publish"
    guard = body[suppress_pos - 400 : publish_pos]
    assert '"suppressed"' in guard, "a suppressed contact must terminalize 'suppressed'"


def test_suppressed_is_a_terminal_status():
    src = (BACKEND / "app" / "execution" / "transition_worker.py").read_text(encoding="utf-8")
    line = next(line for line in src.splitlines() if line.startswith("TERMINAL_STATUSES"))
    assert "suppressed" in line, "suppressed must be terminal so the guard claim is idempotent"
