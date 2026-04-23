"""Multi-channel notifier — fan-out alerts to configured destinations.

Used by:
- `action_hot_lead_alert` dispatcher handler
- approvals ping on human_approval node creation (future)

Channels supported:
- slack   (incoming webhook URL)
- email   (via existing Resend config — falls back to noop if unset)
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings as app_settings
from app.db import fetch_all

log = logging.getLogger(__name__)


async def _send_slack(webhook_url: str, message: str, context: dict[str, Any]) -> None:
    text = message
    fields = [
        {"title": k.replace("_", " ").title(), "value": str(v), "short": True}
        for k, v in (context or {}).items()
        if v not in (None, "")
    ][:10]
    payload = {
        "text": text,
        "attachments": [{"color": "#ef4444", "fields": fields}] if fields else [],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(webhook_url, json=payload)
        r.raise_for_status()


async def _send_email(to_addr: str, subject: str, body: str) -> None:
    api_key = getattr(app_settings, "resend_api_key", "") or ""
    if not api_key:
        log.warning("[notifier] Resend API key not configured — skipping email alert")
        return
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": "alerts@omnioutreach.space",
                "to": [to_addr],
                "subject": subject,
                "text": body,
            },
        )
        if r.status_code >= 400:
            log.warning(f"[notifier] Resend rejected alert ({r.status_code}): {r.text[:200]}")


async def dispatch_alert(
    title: str,
    body: str,
    context: dict[str, Any] | None = None,
    channel_ids: list[str] | None = None,
) -> int:
    """Fan-out an alert to the configured notification channels.

    If channel_ids is provided, only those are used. Otherwise all active
    channels receive the alert. Returns count of successful deliveries.
    """
    query = "SELECT id, channel_type, name, config FROM notification_channels WHERE is_active = TRUE"
    params: list = []
    if channel_ids:
        params.append(channel_ids)
        query += " AND id = ANY($1::uuid[])"
    rows = await fetch_all(query, *params)

    if not rows:
        log.info("[notifier] No active channels; alert is a no-op")
        return 0

    delivered = 0
    for row in rows:
        ch_type = row["channel_type"]
        cfg = row["config"] or {}
        try:
            if ch_type == "slack":
                url = cfg.get("webhook_url")
                if not url:
                    log.warning(f"[notifier] Slack channel {row['id']} missing webhook_url")
                    continue
                await _send_slack(url, f"*{title}*\n{body}", context or {})
            elif ch_type == "email":
                to_addr = cfg.get("to")
                if not to_addr:
                    log.warning(f"[notifier] Email channel {row['id']} missing 'to' address")
                    continue
                await _send_email(to_addr, title, body)
            else:
                log.warning(f"[notifier] Unknown channel_type: {ch_type}")
                continue
            delivered += 1
        except Exception as e:
            log.warning(f"[notifier] {ch_type} channel {row['id']} failed: {e}")

    log.info(f"[notifier] Delivered alert to {delivered}/{len(rows)} channels")
    return delivered
