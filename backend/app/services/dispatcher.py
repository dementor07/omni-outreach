"""
Core outreach dispatcher (Graph-based).

run_once()          — picks up queued tasks and executes them
_queue_invitations() — assigns LinkedIn accounts to new leads and queues invite tasks
_check_acceptances() — detects accepted connections and triggers sequence scheduling
"""
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings
from app.db import execute, fetch_all, fetch_one
from app.services import email, linkedin, renderer, sequencer, voice

log = logging.getLogger(__name__)

BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 300  # 5 minutes

# Channels that contact the lead directly. Used by the blacklist gate so that
# internal actions (tag mutation, enrichment, alerts) keep flowing for blocked
# leads while only outbound delivery is suppressed.
_DELIVERY_CHANNELS = frozenset({
    "linkedin_invite", "linkedin_dm", "linkedin_inmail", "linkedin_profile_view",
    "email", "whatsapp", "sms", "instagram", "telegram", "voice", "webhook",
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _in_active_hours(campaign: dict) -> bool:
    tz = ZoneInfo(campaign.get("timezone") or "UTC")
    local_now = datetime.now(UTC).astimezone(tz)
    h = local_now.hour
    return campaign["active_hours_start"] <= h < campaign["active_hours_end"]


def _next_window_start(campaign: dict) -> datetime:
    tz = ZoneInfo(campaign.get("timezone") or "UTC")
    local_now = datetime.now(UTC).astimezone(tz)
    start_h = campaign["active_hours_start"]
    if local_now.hour < start_h:
        next_window = local_now.replace(hour=start_h, minute=0, second=0, microsecond=0)
    else:
        next_window = (local_now + timedelta(days=1)).replace(
            hour=start_h, minute=0, second=0, microsecond=0
        )
    return next_window.astimezone(UTC)


def _public_id(linkedin_url: str) -> str:
    return linkedin_url.strip().rstrip("/").split("?")[0].split("/in/")[-1]


async def _log_event(
    lead_id: str, campaign_id: str, event_type: str,
    channel: str | None = None, meta: dict | None = None
) -> None:
    await execute(
        """
        INSERT INTO events (lead_id, campaign_id, event_type, channel, meta, occurred_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        """,
        lead_id, campaign_id, event_type, channel, meta or {},
    )


async def _mark_sent(queue_id: str) -> None:
    await execute(
        "UPDATE queue SET status='sent', sent_at=NOW(), locked_by=NULL WHERE id=$1",
        queue_id,
    )


async def _fail_task(queue_id: str, reason: str, current_retry: int) -> None:
    if current_retry < MAX_RETRIES:
        await execute(
            """
            UPDATE queue SET
                status='queued',
                retry_count=retry_count+1,
                scheduled_at=NOW() + ($1 || ' seconds')::interval,
                locked_by=NULL, locked_at=NULL,
                failure_reason=$2
            WHERE id=$3
            """,
            str(RETRY_DELAY_SECONDS), reason, queue_id,
        )
    else:
        await execute(
            """UPDATE queue SET status='failed', failure_reason=$1,
               dead_letter_reason=$1, locked_by=NULL WHERE id=$2""",
            reason, queue_id,
        )


# ── Channel handlers ──────────────────────────────────────────────────────────

async def _handle_linkedin_invite(task: dict, lead: dict, campaign: dict) -> None:
    account = await fetch_one(
        "SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"]
    )
    if not account:
        raise RuntimeError("LinkedIn account not found")

    # Daily cap check
    tz = campaign.get("timezone") or "UTC"
    count_row = await fetch_one(
        """
        SELECT COUNT(*) AS cnt FROM queue q
        WHERE q.channel='linkedin_invite'
          AND q.status='sent'
          AND q.sent_at >= DATE_TRUNC('day', NOW() AT TIME ZONE $1)
          AND q.payload->>'linkedin_account_id' = $2
        """,
        tz, str(account["id"]),
    )
    daily_count = count_row["cnt"] if count_row else 0
    if daily_count >= account["daily_invite_cap"]:
        await execute(
            "UPDATE queue SET status='queued', locked_by=NULL, locked_at=NULL WHERE id=$1",
            task["id"],
        )
        return

    provider_id = task.get("payload", {}).get("provider_id")
    if not provider_id:
        profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), account["unipile_id"])
        provider_id = profile.get("provider_id") or profile.get("id")
        if not provider_id:
            raise RuntimeError("Could not resolve provider_id from LinkedIn profile")

    await linkedin.send_invite(account["unipile_id"], provider_id)
    await execute("UPDATE leads SET invited_at=NOW() WHERE id=$1", lead["id"])
    await execute(
        "UPDATE queue SET payload=payload || $1 WHERE id=$2",
        {"provider_id": provider_id}, task["id"],
    )
    await _log_event(lead["id"], lead["campaign_id"], "invite_sent", "linkedin_invite")
    await _mark_sent(task["id"])


async def _handle_linkedin_dm(task: dict, lead: dict, campaign: dict) -> None:
    account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
    if not account: raise RuntimeError("LinkedIn account not found")

    template = await fetch_one("SELECT body FROM templates WHERE node_id=$1 LIMIT 1", task["node_id"])
    if not template: raise RuntimeError("No template found for node")

    message = renderer.render(template["body"], lead)

    if not lead.get("chat_id"):
        payload = task.get("payload", {})
        provider_id = payload.get("provider_id")
        if not provider_id:
            profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), account["unipile_id"])
            provider_id = profile.get("provider_id") or profile.get("id")
        data = await linkedin.start_chat_with_message(account["unipile_id"], provider_id, message)
        await execute("UPDATE leads SET chat_id=$1 WHERE id=$2", data["chat_id"], lead["id"])
    else:
        await linkedin.send_message(lead["chat_id"], message, account["unipile_id"])

    await _log_event(lead["id"], lead["campaign_id"], "dm_sent", "linkedin_dm")
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_linkedin_profile_view(task: dict, lead: dict, campaign: dict) -> None:
    account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
    if not account: raise RuntimeError("LinkedIn account not found")

    # Fetching the profile via Unipile actually triggers a profile view on LinkedIn
    profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), account["unipile_id"])
    distance = profile.get("network_distance")

    await execute("UPDATE leads SET profile_viewed_at=NOW(), linkedin_distance=$1 WHERE id=$2", distance, lead["id"])
    await _log_event(lead["id"], lead["campaign_id"], "profile_viewed", "linkedin_profile_view", {"distance": distance})
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_linkedin_inmail(task: dict, lead: dict, campaign: dict) -> None:
    account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
    if not account: raise RuntimeError("LinkedIn account not found")

    template = await fetch_one("SELECT subject, body FROM templates WHERE node_id=$1 LIMIT 1", task["node_id"])
    if not template: raise RuntimeError("No template found for node")

    renderer.render(template["body"], lead)
    subject = renderer.render(template["subject"] or "", lead)

    payload = task.get("payload", {})
    provider_id = payload.get("provider_id")
    if not provider_id:
        profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), account["unipile_id"])
        provider_id = profile.get("provider_id") or profile.get("id")

    # Unipile handles InMail via the chat endpoint or specific mail endpoint depending on subscription
    # Here we mock the specific InMail routing for the MVP
    log.info(f"[dispatcher] Sending InMail to {provider_id} with subject {subject}")

    await execute("UPDATE leads SET inmail_sent_at=NOW() WHERE id=$1", lead["id"])
    await _log_event(lead["id"], lead["campaign_id"], "inmail_sent", "linkedin_inmail", {"subject": subject})
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_whatsapp(task: dict, lead: dict, campaign: dict) -> None:
    account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
    template = await fetch_one("SELECT body FROM templates WHERE node_id=$1", task["node_id"])
    message = renderer.render(template["body"], lead)

    if not lead.get("phone"): raise RuntimeError("No phone number")
    attendee_id = f"{lead['phone']}@s.whatsapp.net"

    data = await linkedin.start_chat_with_message(account["unipile_id"], attendee_id, message)
    if not lead.get("chat_id"):
        await execute("UPDATE leads SET chat_id=$1 WHERE id=$2", data["chat_id"], lead["id"])

    await _log_event(lead["id"], lead["campaign_id"], "dm_sent", "whatsapp")
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_instagram(task: dict, lead: dict, campaign: dict) -> None:
    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    ig_acct_id = (node.get("data") or {}).get("instagram_account_id")
    if not ig_acct_id:
        raise RuntimeError("No instagram_account_id specified in node config")

    account = await fetch_one("SELECT * FROM instagram_accounts WHERE id=$1", ig_acct_id)
    if not account: raise RuntimeError("Instagram account not found")

    template = await fetch_one("SELECT body FROM templates WHERE node_id=$1 LIMIT 1", task["node_id"])
    if not template: raise RuntimeError("No template found for node")

    message = renderer.render(template["body"], lead)

    if not lead.get("instagram_username"):
        raise RuntimeError("Lead has no Instagram username")

    try:
        if not lead.get("ig_chat_id"):
            username = lead["instagram_username"]
            profile = await linkedin.get_profile(username, account["unipile_id"])
            provider_id = profile.get("provider_id") or profile.get("id")
            if not provider_id:
                raise RuntimeError("Could not resolve Instagram provider_id from username")

            data = await linkedin.start_chat_with_message(account["unipile_id"], provider_id, message)
            await execute("UPDATE leads SET ig_chat_id=$1 WHERE id=$2", data["chat_id"], lead["id"])
        else:
            payload = task.get("payload", {})
            provider_id = payload.get("provider_id", "")
            await linkedin.send_message(lead["ig_chat_id"], message, account["unipile_id"], provider_id)

        await _log_event(lead["id"], lead["campaign_id"], "dm_sent", "instagram")
        await _mark_sent(task["id"])
        await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))
    except linkedin.InvalidRecipientError as e:
        log.warning(f"Instagram DM failed for lead {lead['id']}: {e}")
        await execute("UPDATE leads SET tags = array_append(tags, 'ig_dm_failed') WHERE id=$1 AND NOT ('ig_dm_failed' = ANY(tags))", lead["id"])
        await execute("UPDATE queue SET status='skipped', failure_reason=$1 WHERE id=$2", str(e), task["id"])
        await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_telegram(task: dict, lead: dict, campaign: dict) -> None:
    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    tg_acct_id = (node.get("data") or {}).get("telegram_account_id")
    if not tg_acct_id:
        raise RuntimeError("No telegram_account_id specified in node config")

    account = await fetch_one("SELECT * FROM telegram_accounts WHERE id=$1", tg_acct_id)
    if not account: raise RuntimeError("Telegram account not found")

    template = await fetch_one("SELECT body FROM templates WHERE node_id=$1 LIMIT 1", task["node_id"])
    if not template: raise RuntimeError("No template found for node")

    message = renderer.render(template["body"], lead)

    identifier = lead.get("telegram_username") or lead.get("phone")
    if not identifier:
        raise RuntimeError("Lead has no Telegram username or phone number")

    try:
        if not lead.get("tg_chat_id"):
            data = await linkedin.start_chat_with_message(account["unipile_id"], identifier, message)
            await execute("UPDATE leads SET tg_chat_id=$1 WHERE id=$2", data["chat_id"], lead["id"])
        else:
            payload = task.get("payload", {})
            provider_id = payload.get("provider_id", "")
            await linkedin.send_message(lead["tg_chat_id"], message, account["unipile_id"], provider_id)

        await _log_event(lead["id"], lead["campaign_id"], "dm_sent", "telegram")
        await _mark_sent(task["id"])
        await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))
    except linkedin.InvalidRecipientError as e:
        log.warning(f"Telegram DM failed for lead {lead['id']}: {e}")
        await execute("UPDATE leads SET tags = array_append(tags, 'tg_dm_failed') WHERE id=$1 AND NOT ('tg_dm_failed' = ANY(tags))", lead["id"])
        await execute("UPDATE queue SET status='skipped', failure_reason=$1 WHERE id=$2", str(e), task["id"])
        await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_email(task: dict, lead: dict, campaign: dict) -> None:
    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    config = node.get("data", {})
    acct = await fetch_one("SELECT * FROM email_accounts WHERE id=$1", config.get("email_account_id"))
    if not acct: raise RuntimeError("Email account not found")

    template = await fetch_one("SELECT subject, body FROM templates WHERE node_id=$1", task["node_id"])
    if not template: raise RuntimeError("No template found")

    subject = renderer.render(template["subject"] or "", lead)
    body = renderer.render(template["body"], lead)

    # Decrypt SMTP password (supports both encrypted and legacy plaintext)
    smtp_password = acct["smtp_password"]
    try:
        from app.services.encryption import decrypt
        smtp_password = decrypt(smtp_password)
    except (ValueError, Exception):
        pass  # legacy plaintext password — use as-is

    await email.send_email(
        from_name=acct["from_name"], from_email=acct["from_email"],
        smtp_host=acct["smtp_host"], smtp_port=acct["smtp_port"],
        smtp_username=acct["smtp_username"], smtp_password=smtp_password,
        to_email=lead["email"], subject=subject, html_body=body
    )
    await _log_event(lead["id"], lead["campaign_id"], "email_sent", "email")
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_voice(task: dict, lead: dict, campaign: dict) -> None:
    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    config = node.get("data", {})
    agent = await fetch_one("SELECT * FROM voice_agents WHERE id=$1", config.get("voice_agent_id"))
    if not agent: raise RuntimeError("Voice agent not found")

    mode = config.get("mode", "simple")
    retell_flow_id = config.get("retell_flow_id") if mode == "flow" else None

    await voice.make_call(
        agent["retell_agent_id"], lead["phone"],
        metadata={"lead_id": str(lead["id"]), "campaign_id": str(lead["campaign_id"])},
        conversation_flow_id=retell_flow_id
    )
    await _log_event(lead["id"], lead["campaign_id"], "call_made", "voice")
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_sms(task: dict, lead: dict, campaign: dict) -> None:
    if not settings.twilio_account_sid or not settings.twilio_auth_token or not settings.twilio_from_number:
        raise RuntimeError("SMS provider not configured (set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER)")

    phone = lead.get("phone")
    if not phone:
        raise RuntimeError("Lead has no phone number")

    template = await fetch_one("SELECT body FROM templates WHERE node_id=$1", task["node_id"])
    if not template:
        raise RuntimeError("No template found for SMS node")
    message = renderer.render(template["body"], lead)

    import httpx
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            url,
            data={"From": settings.twilio_from_number, "To": phone, "Body": message},
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Twilio error {r.status_code}: {r.text[:200]}")
        data = r.json()

    await _log_event(
        lead["id"], lead["campaign_id"], "sms_sent", "sms",
        {"twilio_sid": data.get("sid"), "status": data.get("status")},
    )
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_webhook(task: dict, lead: dict, campaign: dict) -> None:
    """Outbound webhook — POSTs a lead payload to a user-configured URL."""
    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    node_data = node.get("data") or {}
    webhook_url = (node_data.get("url") or "").strip()
    if not webhook_url:
        raise RuntimeError("No webhook URL configured on node")
    if not webhook_url.startswith(("http://", "https://")):
        raise RuntimeError("Webhook URL must start with http:// or https://")

    method = (node_data.get("method") or "POST").upper()
    if method not in ("POST", "PUT", "PATCH"):
        raise RuntimeError(f"Unsupported webhook method: {method}")

    custom_headers = node_data.get("headers") or {}
    # Render body template if provided, otherwise send the lead as JSON
    body_template = node_data.get("body_template")
    if body_template:
        body = renderer.render(str(body_template), lead)
        payload = {"rendered": body}
    else:
        payload = {
            "lead_id": str(lead["id"]),
            "campaign_id": str(lead["campaign_id"]),
            "email": lead.get("email"),
            "first_name": lead.get("first_name"),
            "last_name": lead.get("last_name"),
            "linkedin_url": lead.get("linkedin_url"),
            "company": lead.get("company"),
            "headline": lead.get("headline"),
            "phone": lead.get("phone"),
            "tags": lead.get("tags") or [],
        }

    import httpx
    headers = {"Content-Type": "application/json", **{str(k): str(v) for k, v in custom_headers.items()}}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.request(method, webhook_url, json=payload, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Webhook {method} {webhook_url} → {r.status_code}: {r.text[:200]}")

    await _log_event(
        lead["id"], lead["campaign_id"], "webhook_sent", "webhook",
        {"url": webhook_url, "method": method, "status": r.status_code},
    )
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_add_tag(task: dict, lead: dict, campaign: dict) -> None:
    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    tag = (node.get("data") or {}).get("tag", "").strip()
    if not tag:
        raise RuntimeError("No tag specified in node config")

    await execute(
        "UPDATE leads SET tags = array_append(tags, $1) WHERE id=$2 AND NOT ($1 = ANY(tags))",
        tag, lead["id"]
    )
    await _log_event(lead["id"], lead["campaign_id"], "tag_added", "add_tag", {"tag": tag})
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_remove_tag(task: dict, lead: dict, campaign: dict) -> None:
    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    tag = (node.get("data") or {}).get("tag", "").strip()
    if not tag:
        raise RuntimeError("No tag specified in node config")

    await execute(
        "UPDATE leads SET tags = array_remove(tags, $1) WHERE id=$2",
        tag, lead["id"]
    )
    await _log_event(lead["id"], lead["campaign_id"], "tag_removed", "remove_tag", {"tag": tag})
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_hot_lead_alert(task: dict, lead: dict, campaign: dict) -> None:
    """Fan-out a hot-lead alert via the notifier service."""
    from app.services.notifier import dispatch_alert

    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    node_data = node.get("data") or {}
    title_template = node_data.get("title") or "🔥 Hot lead: {{first_name}} {{last_name}}"
    body_template = node_data.get("body") or (
        "{{first_name}} {{last_name}} at {{company}} is showing buying intent in campaign {{campaign_name}}.\n"
        "Last reply: {{last_reply_text}}"
    )
    channel_ids: list[str] = node_data.get("channel_ids") or []

    title = renderer.render(title_template, {**lead, "campaign_name": campaign.get("name", "")})
    body = renderer.render(body_template, {**lead, "campaign_name": campaign.get("name", "")})
    context = {
        "campaign": campaign.get("name", ""),
        "lead": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
        "email": lead.get("email") or "",
        "linkedin_url": lead.get("linkedin_url") or "",
        "last_reply": (lead.get("last_reply_text") or "")[:200],
    }

    delivered = await dispatch_alert(title, body, context, channel_ids or None)
    await _log_event(
        lead["id"], lead["campaign_id"], "hot_lead_alert", "alert",
        {"delivered": delivered, "channel_ids": channel_ids},
    )
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _handle_enrich(task: dict, lead: dict, campaign: dict) -> None:
    from app.services.lead_source_registry import registry

    node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
    node_data = node.get("data") or {}
    enrich_source = node_data.get("enrich_source", "").strip()
    fields: list[str] = node_data.get("fields", []) or []

    if not enrich_source:
        raise RuntimeError("No enrich_source configured on action_enrich node")

    source = registry.get(enrich_source)
    if not source:
        raise RuntimeError(f"Unknown lead source: {enrich_source}")
    if not source.is_available:
        raise RuntimeError(f"Lead source '{enrich_source}' not configured (missing API key)")
    if not source.supports_enrichment:
        raise RuntimeError(f"Lead source '{enrich_source}' does not support enrichment")

    enriched = await source.enrich(dict(lead))

    # Merge only the configured fields (or all non-empty if no fields filter)
    allowed = set(fields) if fields else {
        "first_name", "last_name", "email", "linkedin_url",
        "headline", "company", "company_linkedin_url",
    }
    updates: dict = {}
    for attr in allowed:
        val = getattr(enriched, attr, None)
        if val and not lead.get(attr):
            updates[attr] = val

    if updates:
        set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates.keys()))
        await execute(
            f"UPDATE leads SET {set_clause} WHERE id=$1",
            lead["id"], *updates.values(),
        )
        log.info(f"[dispatcher] Enriched lead {lead['id']} via {enrich_source}: {list(updates.keys())}")

    await _log_event(
        lead["id"], lead["campaign_id"], "lead_enriched", "enrich",
        {"source": enrich_source, "fields_filled": list(updates.keys())},
    )
    await _mark_sent(task["id"])
    await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))


async def _process_task(task: dict, worker_id: str) -> None:
    campaign = await fetch_one("SELECT * FROM campaigns WHERE id=$1", task["campaign_id"])
    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", task["lead_id"])

    if not campaign or not lead:
        await _fail_task(task["id"], "campaign or lead not found", task["retry_count"])
        return

    if not _in_active_hours(campaign):
        next_start = _next_window_start(campaign)
        await execute(
            "UPDATE queue SET status='queued', locked_by=NULL, locked_at=NULL, scheduled_at=$1 WHERE id=$2",
            next_start, task["id"],
        )
        return

    if campaign.get("simulation_mode"):
        log.info(f"[dispatcher:sim] task={task['id']} channel={task['channel']}")
        await _log_event(lead["id"], campaign["id"], f"simulated_{task['channel']}", task["channel"])
        await _mark_sent(task["id"])
        await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))
        return

    try:
        ch = task["channel"]

        # Blacklist gate (defense-in-depth — intake also filters, but operators
        # can blacklist a lead after they're already in the campaign).
        if ch in _DELIVERY_CHANNELS:
            from app.routers.blacklist import is_blacklisted
            blocked = False
            if lead.get("email") and await is_blacklisted(lead["email"], "email"):
                blocked = True
            elif lead.get("linkedin_url") and await is_blacklisted(lead["linkedin_url"], "linkedin_url"):
                blocked = True
            elif lead.get("company") and await is_blacklisted(lead["company"], "company"):
                blocked = True
            if blocked:
                log.info(f"[dispatcher] task={task['id']} skipped: lead {lead['id']} on blacklist")
                await _log_event(
                    lead["id"], campaign["id"], "blacklisted_skip", ch,
                    {"reason": "lead matched blacklist"},
                )
                await execute(
                    "UPDATE queue SET status='skipped', failure_reason=$1 WHERE id=$2",
                    "blacklisted", task["id"],
                )
                # Advance the DAG so the lead isn't stuck — this matches how
                # other "soft skip" paths (e.g. invalid IG recipient) behave.
                await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))
                return

        if ch == "linkedin_invite": await _handle_linkedin_invite(task, lead, campaign)
        elif ch == "linkedin_dm": await _handle_linkedin_dm(task, lead, campaign)
        elif ch == "linkedin_inmail": await _handle_linkedin_inmail(task, lead, campaign)
        elif ch == "linkedin_profile_view": await _handle_linkedin_profile_view(task, lead, campaign)
        elif ch == "whatsapp": await _handle_whatsapp(task, lead, campaign)
        elif ch == "instagram": await _handle_instagram(task, lead, campaign)
        elif ch == "telegram": await _handle_telegram(task, lead, campaign)
        elif ch == "email": await _handle_email(task, lead, campaign)
        elif ch == "voice": await _handle_voice(task, lead, campaign)
        elif ch == "sms": await _handle_sms(task, lead, campaign)
        elif ch == "webhook": await _handle_webhook(task, lead, campaign)
        elif ch == "add_tag": await _handle_add_tag(task, lead, campaign)
        elif ch == "remove_tag": await _handle_remove_tag(task, lead, campaign)
        elif ch == "enrich": await _handle_enrich(task, lead, campaign)
        elif ch == "hot_lead_alert": await _handle_hot_lead_alert(task, lead, campaign)
        else: raise RuntimeError(f"Unknown channel: {ch}")
    except Exception as e:
        log.exception(f"[dispatcher] task={task['id']} failed: {e}")
        await _fail_task(task["id"], str(e)[:500], task["retry_count"])


async def run_once(worker_id: str = "worker-0") -> None:
    tasks = await fetch_all(
        """
        WITH candidates AS (
            SELECT q.id FROM queue q
            JOIN campaigns c ON c.id = q.campaign_id
            WHERE q.status='queued' AND q.scheduled_at <= NOW() AND c.status='active'
            ORDER BY q.scheduled_at LIMIT $1 FOR UPDATE OF q SKIP LOCKED
        )
        UPDATE queue SET status='locked', locked_at=NOW(), locked_by=$2
        FROM candidates WHERE queue.id=candidates.id RETURNING queue.*
        """,
        BATCH_SIZE, worker_id,
    )
    if not tasks: return
    for task in tasks:
        await _process_task(task, worker_id)


async def _queue_invitations() -> None:
    campaigns = await fetch_all("SELECT * FROM campaigns WHERE status='active'")
    for campaign in campaigns:
        if not _in_active_hours(campaign): continue

        leads = await fetch_all(
            "SELECT * FROM leads WHERE campaign_id=$1 AND invited_at IS NULL AND linkedin_account_id IS NULL AND status='active' ORDER BY id LIMIT 100",
            campaign["id"],
        )
        if not leads: continue

        accounts = await fetch_all(
            "SELECT la.* FROM linkedin_accounts la JOIN campaign_linkedin_accounts cla ON cla.account_id=la.id WHERE cla.campaign_id=$1 AND la.is_active=TRUE",
            campaign["id"],
        )
        if not accounts: continue

        tz = campaign.get("timezone") or "UTC"
        counts_rows = await fetch_all(
            "SELECT l.linkedin_account_id, COUNT(*) AS cnt FROM queue q JOIN leads l ON l.id=q.lead_id WHERE q.channel='linkedin_invite' AND q.campaign_id=$1 AND q.status IN ('queued','locked','sent') AND q.scheduled_at >= DATE_TRUNC('day', NOW() AT TIME ZONE $2) GROUP BY l.linkedin_account_id",
            campaign["id"], tz,
        )
        counts = {str(r["linkedin_account_id"]): r["cnt"] for r in counts_rows}

        invite_node = await fetch_one("SELECT id FROM sequence_nodes WHERE campaign_id=$1 AND node_type='action_linkedin_invite' LIMIT 1", campaign["id"])

        for lead in leads:
            chosen = None
            for acct in sorted(accounts, key=lambda a: counts.get(str(a["id"]), 0)):
                if counts.get(str(acct["id"]), 0) < acct["daily_invite_cap"]:
                    chosen = acct
                    break
            if not chosen: break

            result = await fetch_one("UPDATE leads SET linkedin_account_id=$1 WHERE id=$2 AND linkedin_account_id IS NULL RETURNING id", chosen["id"], lead["id"])
            if not result: continue

            counts[str(chosen["id"])] = counts.get(str(chosen["id"]), 0) + 1
            await execute(
                "INSERT INTO queue (campaign_id, lead_id, node_id, channel, status, scheduled_at) VALUES ($1, $2, $3, 'linkedin_invite', 'queued', NOW()) ON CONFLICT DO NOTHING",
                campaign["id"], lead["id"], invite_node["id"] if invite_node else None,
            )


async def _check_acceptances() -> None:
    pending = await fetch_all(
        "SELECT l.*, la.unipile_id AS unipile_account_id FROM leads l JOIN linkedin_accounts la ON la.id=l.linkedin_account_id WHERE l.invited_at IS NOT NULL AND l.accepted_at IS NULL AND l.status='active' ORDER BY l.invited_at ASC LIMIT 100",
    )
    for lead in pending:
        try:
            profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), lead["unipile_account_id"])
            if profile.get("network_distance") != "FIRST_DEGREE": continue
            result = await fetch_one("UPDATE leads SET accepted_at=NOW() WHERE id=$1 AND accepted_at IS NULL RETURNING id", lead["id"])
            if not result: continue
            await _log_event(lead["id"], lead["campaign_id"], "invite_accepted", "linkedin_invite")
            await sequencer.schedule_sequence(str(lead["id"]))
        except Exception as e:
            log.warning(f"[acceptances] Lead {lead['id']} error: {e}")
