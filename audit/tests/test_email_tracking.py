"""T3 regression — email open/click tracking.

The crypto + injection are pure, so these are REAL behavioural assertions (not
source-grep): a tampered/forged token must not attribute, the pixel + link
rewrites must land in the body, and the click decoder must refuse non-http
destinations (no open redirect). Plus the wire-in invariants: render injects on
email when a token is supplied, build_command mints one, the projector logs the
hit, and the public router is mounted.

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from pathlib import Path

from app.core.events import ChannelType
from app.execution.render import render_channel_payload
from app.services.email_tracking import (
    _b64url,
    decode_click_url,
    inject_tracking,
    make_token,
    parse_token,
)

BACKEND = Path(__file__).resolve().parents[2] / "backend"
COMMANDS = (BACKEND / "app" / "execution" / "commands.py").read_text(encoding="utf-8")
PROJECTOR = (BACKEND / "app" / "projector" / "main.py").read_text(encoding="utf-8")
MAIN = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
MIGRATION = (BACKEND / "alembic" / "versions" / "034_email_tracking.py").read_text(encoding="utf-8")

SECRET = "test-secret"


# ── token: signed + tamper-proof ──────────────────────────────────────────────

def test_token_roundtrip():
    t = make_token(SECRET, workspace_id="ws", lead_id="l", contact_id="c")
    assert parse_token(SECRET, t) == {"workspace_id": "ws", "lead_id": "l", "contact_id": "c"}


def test_token_rejects_tamper_and_wrong_secret():
    t = make_token(SECRET, workspace_id="ws", lead_id="l", contact_id="c")
    assert parse_token(SECRET, t[:-4] + "AAAA") is None  # tampered sig
    assert parse_token("other-secret", t) is None         # wrong key
    assert parse_token(SECRET, "garbage") is None          # malformed


# ── injection: pixel + link rewrite ───────────────────────────────────────────

def test_inject_adds_pixel_and_rewrites_links():
    t = make_token(SECRET, workspace_id="ws", lead_id="l", contact_id="c")
    html = inject_tracking('<a href="https://example.com/x">go</a>', base="https://h.io", token=t)
    assert f"https://h.io/track/open/{t}.gif" in html, "open pixel must be appended"
    assert f"https://h.io/track/click/{t}?u=" in html, "links must be rewritten to the redirect"
    assert 'width="1"' in html


def test_inject_does_not_double_wrap_tracker_links():
    t = make_token(SECRET, workspace_id="ws", lead_id="l", contact_id="c")
    already = f'<a href="https://h.io/track/click/{t}?u=abc">x</a>'
    out = inject_tracking(already, base="https://h.io", token=t)
    # the existing tracker link is left alone (only the pixel is appended)
    assert out.count("/track/click/") == 1


def test_click_decoder_blocks_open_redirect():
    assert decode_click_url(_b64url(b"https://safe.com")) == "https://safe.com"
    assert decode_click_url(_b64url(b"javascript:alert(1)")) is None
    assert decode_click_url("not-base64!!") is None


# ── wire-in: render injects on email when a token is supplied ─────────────────

def test_render_injects_tracking_into_email_body():
    out = render_channel_payload(
        ChannelType.EMAIL,
        {"body": '<p>hi <a href="https://x.io">link</a></p>'},
        lead={"id": "l1"},
        contact={"id": "c1", "email": "a@b.io"},
        bundle={},
        tracking_base="https://h.io",
        tracking_token="tok123",
    )
    assert "/track/open/tok123.gif" in out["body"]
    assert "/track/click/tok123?u=" in out["body"]


def test_render_leaves_email_untouched_without_token():
    out = render_channel_payload(
        ChannelType.EMAIL,
        {"body": "plain body"},
        lead={"id": "l1"},
        contact={"email": "a@b.io"},
        bundle={},
    )
    assert out["body"] == "plain body", "no token => no injection (opt-in per send)"


def test_build_command_mints_email_token():
    body = COMMANDS.split("async def build_command", 1)[1]
    assert "ChannelType.EMAIL" in body and "make_token" in body
    assert "get_public_base_url" in body


def test_projector_logs_open_and_click():
    assert "email.opened" in PROJECTOR and "email.clicked" in PROJECTOR
    assert "_project_email_tracking" in PROJECTOR
    assert "INSERT INTO omni_email_tracking" in PROJECTOR


def test_tracking_router_mounted_and_migration_rls():
    assert 'tracking.router, prefix="/track"' in MAIN
    assert "CREATE TABLE IF NOT EXISTS omni_email_tracking" in MIGRATION
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "event_type IN ('open', 'click')" in MIGRATION
    assert 'down_revision = "033"' in MIGRATION
