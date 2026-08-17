"""N8N-001 Part 3 — channel.n8n preset + callback resume + routing contract.

channel.n8n is a preset over channel.webhook_out: it MUST emit the same
channel.webhook_out.queued intent (so it rides the existing Rust handle_webhook —
zero Rust change) and route to ChannelType.WEBHOOK. With wait_for_callback it
parks the lead and carries a signed callback token. Pure/functional — no DB/Kafka.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.events import ChannelType  # noqa: E402
from app.execution.commands import NODE_CHANNEL  # noqa: E402
from app.nodes import NodeContext, discover, get  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _ctx(config, lead=None):
    return NodeContext(
        workspace_id="11111111-1111-1111-1111-111111111111",
        workflow_id="wf", node_id="node-1",
        config=config,
        lead=lead if lead is not None else {"id": "lead-1", "custom_fields": {"item": {"x": 1}}},
        correlation_id="corr-1",
    )


def test_channel_n8n_registers_and_routes_to_webhook():
    discover()
    manifest, _execute = get("channel.n8n")
    assert manifest.type == "channel.n8n"
    # Same muscle channel as webhook_out — zero Rust change.
    assert NODE_CHANNEL.get("channel.n8n") == ChannelType.WEBHOOK
    assert NODE_CHANNEL.get("channel.webhook_out") == ChannelType.WEBHOOK
    handles = {h.name for h in manifest.output_handles}
    assert {"sent", "on_error", "resumed", "timeout"} <= handles


def test_channel_n8n_emits_webhook_out_queued_with_lead_snapshot():
    _, execute = get("channel.n8n")
    result = _run(execute(_ctx({"webhook_url": "https://n8n.example.com/webhook/abc"})))
    assert result.handle == "sent"
    assert result.park is False
    assert len(result.events) == 1
    ev = result.events[0]
    # It rides the EXACT intent webhook_out emits.
    assert ev["event_type"] == "channel.webhook_out.queued"
    body = ev["payload"]["body"]
    assert body["lead"]["id"] == "lead-1"
    assert body["lead"]["custom_fields"] == {"item": {"x": 1}}
    assert ev["payload"]["url"] == "https://n8n.example.com/webhook/abc"
    assert ev["payload"]["method"] == "POST"


def test_wait_for_callback_parks_and_carries_token():
    _, execute = get("channel.n8n")
    result = _run(execute(_ctx({
        "webhook_url": "https://n8n.example.com/webhook/abc",
        "wait_for_callback": True,
        "callback_timeout_hours": 12,
    })))
    # Parks (mirrors event.invite_accepted) but STILL dispatches the POST.
    assert result.park is True
    assert result.telemetry.get("timeout_seconds") == 12 * 3600
    assert len(result.events) == 1
    body = result.events[0]["payload"]["body"]
    assert "callback_token" in body and body["callback_token"]
    assert "/n8n/callback/" in body["callback_url"]

    # The token is a valid, verifiable callback token for THIS lead/node.
    from app.config import settings
    from app.services.callback_token import parse_callback_token

    claims = parse_callback_token(settings.secret_key, body["callback_token"])
    assert claims == {
        "workspace_id": "11111111-1111-1111-1111-111111111111",
        "lead_id": "lead-1",
        "node_id": "node-1",
    }


def test_no_callback_token_when_not_waiting():
    _, execute = get("channel.n8n")
    result = _run(execute(_ctx({"webhook_url": "https://n8n.example.com/webhook/abc"})))
    body = result.events[0]["payload"]["body"]
    assert "callback_token" not in body and "callback_url" not in body


def test_extra_fields_merge_into_body():
    _, execute = get("channel.n8n")
    result = _run(execute(_ctx({
        "webhook_url": "https://n8n.example.com/webhook/abc",
        "include_lead": False,
        "extra": {"campaign": "Q3-outbound"},
    })))
    body = result.events[0]["payload"]["body"]
    assert body["campaign"] == "Q3-outbound"
    assert "lead" not in body  # include_lead False
