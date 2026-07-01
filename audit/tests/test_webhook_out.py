"""N8N-001 Part 2 — outbound webhook fan-out: filtering, HMAC, SSRF.

Pure/mocked. Covers:
  * the fixed customer-facing allow-list + fact→event mapping (no internal leak);
  * subscription filtering (event in list / empty=all / not-subscribed skipped);
  * the HMAC signature is correct + independently verifiable;
  * a private/loopback/metadata URL is rejected by the SSRF guard.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import webhook_events  # noqa: E402
from app.services.url_guard import UnsafeURLError, validate_outbound_url  # noqa: E402
from app.services.webhook_events import ALLOWED_EVENTS, map_fact, serialize, sign  # noqa: E402


# ── allow-list + fact mapping ──────────────────────────────────────────────────
def test_allow_list_is_customer_facing_only():
    """Only the documented customer-facing names (+ ping) are ever deliverable —
    no internal spine facts."""
    assert ALLOWED_EVENTS == frozenset(
        {"lead.replied", "invite.accepted", "campaign.run.completed",
         "lead.enriched", "lead.hot", "ping"}
    )


def test_fact_mapping_uses_real_emitted_fact_names():
    """The map keys are the ACTUAL facts the system emits today (grepped), and
    each maps to an allow-listed customer event. Internal facts map to None."""
    # Real facts (verified in the codebase).
    assert map_fact("message.received") == "lead.replied"
    assert map_fact("campaign.run.completed") == "campaign.run.completed"
    assert map_fact("crm.hot_lead_alert.queued") == "lead.hot"
    assert map_fact("lead.custom_fields_updated") == "lead.enriched"
    # Every mapped target is allow-listed.
    for target in webhook_events._FACT_TO_EVENT.values():
        assert target in ALLOWED_EVENTS
    # Internal spine facts are never deliverable.
    for internal in ("transition", "result_task", "send.outcome", "pipeline.metric", "channel.email.queued"):
        assert map_fact(internal) is None


# ── HMAC ────────────────────────────────────────────────────────────────────────
def test_hmac_signature_is_correct_and_verifiable():
    envelope = webhook_events.normalize_envelope(
        event="lead.replied", workspace_id="ws-1", data={"x": 1}, occurred_at="2026-07-01T00:00:00+00:00"
    )
    body = serialize(envelope)
    signature = sign("s3cr3t", body)
    assert signature.startswith("sha256=")
    # A receiver recomputes the same digest over the raw body bytes.
    expected = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    assert signature == f"sha256={expected}"
    # A different secret yields a different signature (authenticity).
    assert sign("other", body) != signature


def test_envelope_shape_is_stable():
    env = webhook_events.normalize_envelope(event="ping", workspace_id="w", data={"a": "b"})
    assert set(env) == {"event", "workspace_id", "occurred_at", "data"}
    assert env["event"] == "ping" and env["workspace_id"] == "w" and env["data"] == {"a": "b"}


# ── subscription filtering (the worker's _load_subscriptions predicate) ─────────
def _wants(event_types, event):
    """Mirror the worker filter: empty event_types = all; else membership."""
    return not event_types or event in event_types


def test_subscription_filtering():
    assert _wants([], "lead.replied") is True            # empty = all
    assert _wants(["lead.replied"], "lead.replied") is True
    assert _wants(["invite.accepted"], "lead.replied") is False  # not subscribed
    assert _wants(["lead.hot", "campaign.run.completed"], "lead.hot") is True


# ── SSRF ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",
        "http://localhost/hook",
        "http://10.1.2.3/hook",
        "http://192.168.0.1/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/x",
        "http://100.64.0.1/x",
        "ftp://example.com/x",
        "http://[::1]/x",
    ],
)
def test_ssrf_blocks_private_and_metadata(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url, resolve=False)


def test_ssrf_allows_public_https():
    assert validate_outbound_url("https://hooks.example.com/omni", resolve=False)
    assert validate_outbound_url("https://8.8.8.8/omni", resolve=False)


@pytest.mark.asyncio
async def test_deliver_one_blocks_unsafe_url_without_network():
    """deliver_one must SSRF-check at SEND and never POST to a blocked host."""
    status_code, error = await webhook_events.deliver_one(
        url="http://127.0.0.1/x", secret="s", event="ping", workspace_id="w", data={}
    )
    assert status_code is None and "unsafe" in (error or "").lower()
