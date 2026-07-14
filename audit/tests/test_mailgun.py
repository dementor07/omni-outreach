"""MAILGUN-001 — Mailgun send provider + event webhooks.

Covers the pure, deterministic surfaces of the Mailgun integration:
  * the webhook HMAC verification (HMAC-SHA256 over timestamp+token, per Mailgun);
  * the event->resume-signal mapping (hard bounce vs transient, delivered/open/click);
  * the render layer choosing the Mailgun vs SMTP payload by connection provider;
  * the two new event nodes registering with the right handles.

Live send/webhook round-trips need the throwaway key + a deployed box, so they're
verified out-of-band; this locks the logic that decides what gets sent/resumed.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.nodes import discover, get  # noqa: E402
from app.routers.webhooks_in import _mailgun_signal, _verify_mailgun  # noqa: E402
from app.services import event_resume  # noqa: E402

discover()


# ── Webhook HMAC ─────────────────────────────────────────────────────────────


def _sign(signing_key: str, timestamp: str, token: str) -> str:
    return hmac.new(signing_key.encode(), f"{timestamp}{token}".encode(), hashlib.sha256).hexdigest()


def test_mailgun_hmac_accepts_a_valid_signature():
    sig = _sign("sk-123", "1700000000", "tok-abc")
    assert _verify_mailgun("sk-123", "1700000000", "tok-abc", sig) is True


def test_mailgun_hmac_rejects_a_tampered_signature():
    sig = _sign("sk-123", "1700000000", "tok-abc")
    # Wrong key, wrong token, wrong timestamp, and garbage all fail.
    assert _verify_mailgun("WRONG", "1700000000", "tok-abc", sig) is False
    assert _verify_mailgun("sk-123", "1700000000", "tok-XXX", sig) is False
    assert _verify_mailgun("sk-123", "9999999999", "tok-abc", sig) is False
    assert _verify_mailgun("sk-123", "1700000000", "tok-abc", "deadbeef") is False


def test_mailgun_hmac_rejects_missing_fields():
    assert _verify_mailgun("", "1", "t", "s") is False
    assert _verify_mailgun("k", "", "t", "s") is False
    assert _verify_mailgun("k", "1", "", "s") is False
    assert _verify_mailgun("k", "1", "t", "") is False


# ── Event -> signal mapping ──────────────────────────────────────────────────


def test_permanent_failure_is_a_hard_bounce():
    assert _mailgun_signal("failed", "permanent") == "email_bounced"
    # Legacy/alt event names for a hard bounce also map.
    assert _mailgun_signal("bounced", "") == "email_bounced"
    assert _mailgun_signal("permanent_fail", "") == "email_bounced"


def test_temporary_failure_is_not_a_bounce():
    # A transient (soft) failure must NOT fire the bounce branch.
    assert _mailgun_signal("failed", "temporary") is None


def test_engagement_events_map_to_existing_signals():
    assert _mailgun_signal("delivered", "") == "email_delivered"
    assert _mailgun_signal("opened", "") == "email_opened"
    assert _mailgun_signal("clicked", "") == "link_clicked"


def test_non_actionable_events_are_ignored():
    assert _mailgun_signal("unsubscribed", "") is None
    assert _mailgun_signal("complained", "") is None
    assert _mailgun_signal("stored", "") is None


def test_every_mapped_signal_has_a_resume_target():
    """Any signal _mailgun_signal can return must be resumable (present in the
    resume bridge) — otherwise the webhook wakes nothing."""
    for event, severity in [("delivered", ""), ("opened", ""), ("clicked", ""), ("failed", "permanent")]:
        signal = _mailgun_signal(event, severity)
        assert signal in event_resume._SIGNAL_RESUME, f"{signal} has no resume target"


# ── Render: provider selection ───────────────────────────────────────────────


def test_render_picks_mailgun_payload_for_a_mailgun_connection():
    from app.core.events import ChannelType
    from app.execution.render import render_channel_payload

    out = render_channel_payload(
        channel=ChannelType.EMAIL,
        contact={},
        lead={"email": "ada@example.com"},
        payload={"subject": "Hi", "body": "<p>Hi</p>"},
        bundle={"provider": "mailgun", "mailgun_domain": "mg.example.com", "mailgun_region": "", "from": "s@mg.example.com"},
    )
    assert out.get("provider") == "mailgun"
    assert out.get("mailgun_domain") == "mg.example.com"
    # No SMTP transport leaks into a Mailgun send.
    assert "smtp_host" not in out


def test_render_keeps_smtp_payload_for_a_non_mailgun_connection():
    from app.core.events import ChannelType
    from app.execution.render import render_channel_payload

    out = render_channel_payload(
        channel=ChannelType.EMAIL,
        contact={},
        lead={"email": "ada@example.com"},
        payload={"subject": "Hi", "body": "<p>Hi</p>"},
        bundle={"smtp_host": "smtp.example.com", "smtp_username": "u@example.com", "smtp_port": 587},
    )
    assert out.get("provider") != "mailgun"
    assert out.get("smtp_host") == "smtp.example.com"


# ── Event nodes ──────────────────────────────────────────────────────────────


def test_bounce_and_delivered_nodes_registered_with_handles():
    m_bounce, _ = get("event.email_bounced")
    assert {h.name for h in m_bounce.output_handles} == {"bounced", "timeout"}
    m_deliv, _ = get("event.email_delivered")
    assert {h.name for h in m_deliv.output_handles} == {"delivered", "timeout"}


# ── Gate fixes (review HIGH/MEDIUM) ──────────────────────────────────────────


def test_timestamp_freshness_rejects_replay():
    """MEDIUM (review): a stale/garbage timestamp must be rejected (replay window)."""
    from datetime import datetime, timezone

    from app.routers.webhooks_in import _mailgun_timestamp_fresh

    now = datetime.now(timezone.utc).timestamp()
    assert _mailgun_timestamp_fresh(str(int(now))) is True
    assert _mailgun_timestamp_fresh(str(int(now - 3600))) is False  # 1h old
    assert _mailgun_timestamp_fresh("not-a-timestamp") is False


def test_render_tags_send_with_the_connection_id():
    """HIGH #1 (review): a Mailgun send must carry the connection id so the
    webhook verifies against THAT connection's key, not the newest one."""
    from app.core.events import ChannelType
    from app.execution.render import render_channel_payload

    out = render_channel_payload(
        channel=ChannelType.EMAIL,
        contact={},
        lead={"email": "ada@example.com"},
        payload={"subject": "Hi", "body": "<p>Hi</p>"},
        bundle={
            "provider": "mailgun",
            "mailgun_domain": "mg.example.com",
            "_connection_id": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert out.get("mailgun_connection_id") == "11111111-1111-1111-1111-111111111111"
