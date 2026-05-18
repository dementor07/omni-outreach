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
from app.core.events import TaskStatus
from app.db import execute, fetch_all, fetch_one
from app.services import email, linkedin, renderer, screener, sequencer, voice

log = logging.getLogger(__name__)

BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 300  # 5 minutes

# Channels that contact the lead directly. Used by the blacklist gate so that
# internal actions (tag mutation, enrichment, alerts) keep flowing for blocked
# leads while only outbound delivery is suppressed.
_DELIVERY_CHANNELS = frozenset(
    {
        "linkedin_invite",
        "linkedin_dm",
        "linkedin_inmail",
        "linkedin_profile_view",
        "email",
        "whatsapp",
        "sms",
        "instagram",
        "telegram",
        "voice",
        "webhook",
    }
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve_tz(lead: dict | None, campaign: dict) -> ZoneInfo:
    """Prefer the lead's timezone if set (Gap 7), otherwise fall back to campaign."""
    lead_tz = lead.get("timezone") if lead else None
    tz_name = lead_tz or campaign.get("timezone") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — bad data should not break the dispatcher
        return ZoneInfo("UTC")


def _in_active_hours(campaign: dict, lead: dict | None = None) -> bool:
    tz = _resolve_tz(lead, campaign)
    local_now = datetime.now(UTC).astimezone(tz)
    h = local_now.hour
    return campaign["active_hours_start"] <= h < campaign["active_hours_end"]


def _next_window_start(campaign: dict, lead: dict | None = None) -> datetime:
    tz = _resolve_tz(lead, campaign)
    local_now = datetime.now(UTC).astimezone(tz)
    start_h = campaign["active_hours_start"]
    if local_now.hour < start_h:
        next_window = local_now.replace(hour=start_h, minute=0, second=0, microsecond=0)
    else:
        next_window = (local_now + timedelta(days=1)).replace(hour=start_h, minute=0, second=0, microsecond=0)
    return next_window.astimezone(UTC)


def _public_id(linkedin_url: str) -> str:
    return linkedin_url.strip().rstrip("/").split("?")[0].split("/in/")[-1]


async def _log_event(
    lead_id: str, campaign_id: str, event_type: str, channel: str | None = None, meta: dict | None = None
) -> None:
    await execute(
        """
        INSERT INTO events (lead_id, campaign_id, event_type, channel, meta, occurred_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        """,
        lead_id,
        campaign_id,
        event_type,
        channel,
        meta or {},
    )


async def _resolve_template(node_id: str) -> dict | None:
    """Prefer a shared template referenced by node.data.template_id, fall back
    to the per-node template row. Returns a dict with at least body + subject."""
    node = await fetch_one("SELECT data FROM sequence_nodes WHERE id=$1", node_id)
    template_id = None
    if node and isinstance(node.get("data"), dict):
        template_id = (node["data"] or {}).get("template_id")
    if template_id:
        shared = await fetch_one(
            "SELECT subject, body FROM templates WHERE id=$1",
            template_id,
        )
        if shared:
            return shared
    return await fetch_one(
        "SELECT subject, body FROM templates WHERE node_id=$1 LIMIT 1",
        node_id,
    )


async def _mark_sent(queue_id: str) -> None:
    await execute(
        "UPDATE queue SET status='sent', sent_at=NOW(), locked_by=NULL WHERE id=$1",
        queue_id,
    )
    await execute(
        "UPDATE processed_commands SET status='sent', processed_at=NOW() WHERE command_id=$1",
        queue_id,
    )
    # Crown a race winner if the node lives downstream of a control_race.
    row = await fetch_one("SELECT lead_id, node_id FROM queue WHERE id=$1", queue_id)
    if row and row.get("node_id"):
        try:
            await sequencer.claim_race_winner_if_applicable(
                str(row["lead_id"]), str(row["node_id"])
            )
        except Exception as e:  # noqa: BLE001 — race plumbing must never break dispatch
            log.warning(f"[dispatcher] claim_race_winner failed: {e}")


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
            str(RETRY_DELAY_SECONDS),
            reason,
            queue_id,
        )
        return

    # Retries exhausted — mark failed AND look for an on_error edge so the
    # operator can pivot the lead to a fallback branch (Gap 2).
    await execute(
        """UPDATE queue SET status='failed', failure_reason=$1,
           dead_letter_reason=$1, locked_by=NULL WHERE id=$2""",
        reason,
        queue_id,
    )
    row = await fetch_one("SELECT lead_id, node_id FROM queue WHERE id=$1", queue_id)
    if not row or not row.get("node_id"):
        return
    has_on_error = await fetch_one(
        "SELECT 1 FROM sequence_edges WHERE source_node_id=$1 AND source_handle='on_error' LIMIT 1",
        row["node_id"],
    )
    if has_on_error:
        log.info(
            f"[dispatcher] task={queue_id} exhausted retries; routing lead "
            f"{row['lead_id']} via on_error from node {row['node_id']}"
        )
        try:
            await sequencer.queue_next_nodes(
                str(row["lead_id"]), str(row["node_id"]), "on_error"
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"[dispatcher] on_error routing failed: {e}")


# ── SOTA Registry ─────────────────────────────────────────────────────────────


class BaseHandler:
    """Blueprint for all outreach execution."""

    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        raise NotImplementedError("Subclasses must implement execute")

    async def emit_result(self, task_id: str, status: TaskStatus, error: str | None = None) -> None:
        """Mirror an execution receipt into ``stream_log`` so Flink/analytics can
        replay results even when Rust is not in the loop.

        Kept dependency-light on purpose: writes through ``execute()`` rather
        than importing ``bus`` to avoid a producer round-trip on every legacy
        dispatch. The Rust execution engine publishes the canonical receipt to
        ``outreach.results``; this is the legacy-path equivalent.
        """
        import json as _json

        from app.core.events import EventType
        from app.db import execute as _execute

        payload = _json.dumps(
            {
                "task_id": task_id,
                "status": status.value if hasattr(status, "value") else str(status),
                "error": error,
            }
        )
        try:
            await _execute(
                "INSERT INTO stream_log (event_type, payload, occurred_at) VALUES ($1, $2, NOW())",
                EventType.RESULT_TASK.value,
                payload,
            )
        except Exception as e:  # noqa: BLE001 — telemetry must never fail the dispatch
            log.warning("[dispatcher] emit_result failed (non-fatal): %s", e)


class HandlerRegistry:
    def __init__(self):
        self._handlers: dict[str, BaseHandler] = {}

    def register(self, channel: str, handler: BaseHandler):
        self._handlers[channel] = handler

    async def handle(self, task: dict, lead: dict, campaign: dict) -> bool:
        channel = task["channel"]
        handler = self._handlers.get(channel)
        if not handler:
            raise RuntimeError(f"No handler registered for channel: {channel}")
        return await handler.execute(task, lead, campaign)


registry = HandlerRegistry()


# ── Channel handlers ──────────────────────────────────────────────────────────


class LinkedInInviteHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
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
            tz,
            str(account["id"]),
        )
        daily_count = count_row["cnt"] if count_row else 0
        if daily_count >= account["daily_invite_cap"]:
            await execute(
                "UPDATE queue SET status='queued', locked_by=NULL, locked_at=NULL WHERE id=$1",
                task["id"],
            )
            return False

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
            {"provider_id": provider_id},
            task["id"],
        )
        await _log_event(lead["id"], lead["campaign_id"], "invite_sent", "linkedin_invite")
        await _mark_sent(task["id"])
        return True


registry.register("linkedin_invite", LinkedInInviteHandler())


class LinkedInDMHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
        if not account:
            raise RuntimeError("LinkedIn account not found")

        template = await _resolve_template(task["node_id"])
        if not template:
            raise RuntimeError("No template found for node")

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
        return True


registry.register("linkedin_dm", LinkedInDMHandler())


class LinkedInProfileViewHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
        if not account:
            raise RuntimeError("LinkedIn account not found")

        # Fetching the profile via Unipile actually triggers a profile view on LinkedIn
        profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), account["unipile_id"])
        distance = profile.get("network_distance")

        await execute(
            "UPDATE leads SET profile_viewed_at=NOW(), linkedin_distance=$1 WHERE id=$2", distance, lead["id"]
        )
        await _log_event(
            lead["id"], lead["campaign_id"], "profile_viewed", "linkedin_profile_view", {"distance": distance}
        )
        await _mark_sent(task["id"])
        return True


registry.register("linkedin_profile_view", LinkedInProfileViewHandler())


class LinkedInInMailHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
        if not account:
            raise RuntimeError("LinkedIn account not found")

        template = await _resolve_template(task["node_id"])
        if not template:
            raise RuntimeError("No template found for node")

        renderer.render(template["body"], lead)
        subject = renderer.render(template["subject"] or "", lead)

        payload = task.get("payload", {})
        provider_id = payload.get("provider_id")
        if not provider_id:
            profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), account["unipile_id"])
            provider_id = profile.get("provider_id") or profile.get("id")

        log.info(f"[dispatcher] Sending InMail to {provider_id} with subject {subject}")

        await execute("UPDATE leads SET inmail_sent_at=NOW() WHERE id=$1", lead["id"])
        await _log_event(lead["id"], lead["campaign_id"], "inmail_sent", "linkedin_inmail", {"subject": subject})
        await _mark_sent(task["id"])
        return True


registry.register("linkedin_inmail", LinkedInInMailHandler())


class WhatsAppHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        account = await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", lead["linkedin_account_id"])
        template = await _resolve_template(task["node_id"])
        message = renderer.render(template["body"], lead)

        if not lead.get("phone"):
            raise RuntimeError("No phone number")
        attendee_id = f"{lead['phone']}@s.whatsapp.net"

        data = await linkedin.start_chat_with_message(account["unipile_id"], attendee_id, message)
        if not lead.get("chat_id"):
            await execute("UPDATE leads SET chat_id=$1 WHERE id=$2", data["chat_id"], lead["id"])

        await _log_event(lead["id"], lead["campaign_id"], "dm_sent", "whatsapp")
        await _mark_sent(task["id"])
        return True


registry.register("whatsapp", WhatsAppHandler())


class InstagramHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        ig_acct_id = (node.get("data") or {}).get("instagram_account_id")
        if not ig_acct_id:
            raise RuntimeError("No instagram_account_id specified")

        account = await fetch_one("SELECT * FROM instagram_accounts WHERE id=$1", ig_acct_id)
        if not account:
            raise RuntimeError("Instagram account not found")

        template = await _resolve_template(task["node_id"])
        message = renderer.render(template["body"], lead)

        if not lead.get("instagram_username"):
            raise RuntimeError("No Instagram username")

        try:
            if not lead.get("ig_chat_id"):
                username = lead["instagram_username"]
                profile = await linkedin.get_profile(username, account["unipile_id"])
                provider_id = profile.get("provider_id") or profile.get("id")
                data = await linkedin.start_chat_with_message(account["unipile_id"], provider_id, message)
                await execute("UPDATE leads SET ig_chat_id=$1 WHERE id=$2", data["chat_id"], lead["id"])
            else:
                payload = task.get("payload", {})
                provider_id = payload.get("provider_id", "")
                await linkedin.send_message(lead["ig_chat_id"], message, account["unipile_id"], provider_id)

            await _log_event(lead["id"], lead["campaign_id"], "dm_sent", "instagram")
            await _mark_sent(task["id"])
            return True
        except linkedin.InvalidRecipientError as e:
            log.warning(f"Instagram DM failed for lead {lead['id']}: {e}")
            await execute(
                "UPDATE leads SET tags = array_append(tags, 'ig_dm_failed') WHERE id=$1 AND NOT ('ig_dm_failed' = ANY(tags))",
                lead["id"],
            )
            await execute("UPDATE queue SET status='skipped', failure_reason=$1 WHERE id=$2", str(e), task["id"])
            return True


registry.register("instagram", InstagramHandler())


class TelegramHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        tg_acct_id = (node.get("data") or {}).get("telegram_account_id")
        if not tg_acct_id:
            raise RuntimeError("No telegram_account_id specified")

        account = await fetch_one("SELECT * FROM telegram_accounts WHERE id=$1", tg_acct_id)
        if not account:
            raise RuntimeError("Telegram account not found")

        template = await _resolve_template(task["node_id"])
        message = renderer.render(template["body"], lead)

        identifier = lead.get("telegram_username") or lead.get("phone")
        if not identifier:
            raise RuntimeError("No Telegram identifier")

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
            return True
        except linkedin.InvalidRecipientError as e:
            log.warning(f"Telegram DM failed: {e}")
            await execute(
                "UPDATE leads SET tags = array_append(tags, 'tg_dm_failed') WHERE id=$1 AND NOT ('tg_dm_failed' = ANY(tags))",
                lead["id"],
            )
            await execute("UPDATE queue SET status='skipped', failure_reason=$1 WHERE id=$2", str(e), task["id"])
            return True


registry.register("telegram", TelegramHandler())


class EmailHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        config = node.get("data", {})
        acct = await fetch_one("SELECT * FROM email_accounts WHERE id=$1", config.get("email_account_id"))
        if not acct:
            raise RuntimeError("Email account not found")

        template = await _resolve_template(task["node_id"])
        if not template:
            raise RuntimeError("No template found")

        subject = renderer.render(template["subject"] or "", lead)
        body = renderer.render(template["body"], lead)

        smtp_password = acct["smtp_password"]
        try:
            from app.services.encryption import decrypt

            smtp_password = decrypt(smtp_password)
        except (ValueError, Exception):
            pass

        await email.send_email(
            from_name=acct["from_name"],
            from_email=acct["from_email"],
            smtp_host=acct["smtp_host"],
            smtp_port=acct["smtp_port"],
            smtp_username=acct["smtp_username"],
            smtp_password=smtp_password,
            smtp_use_tls=acct.get("smtp_use_tls", True),
            to_email=lead["email"],
            subject=subject,
            body_html=body,
        )
        await _log_event(lead["id"], lead["campaign_id"], "email_sent", "email")
        await _mark_sent(task["id"])
        return True


registry.register("email", EmailHandler())


class VoiceHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        config = node.get("data", {})
        agent = await fetch_one("SELECT * FROM voice_agents WHERE id=$1", config.get("voice_agent_id"))
        if not agent:
            raise RuntimeError("Voice agent not found")

        mode = config.get("mode", "simple")
        retell_flow_id = config.get("retell_flow_id") if mode == "flow" else None
        field_mappings: dict = config.get("field_mappings") or {}
        dynamic_vars: dict = {
            var_name: str(lead.get(lead_field) or "")
            for var_name, lead_field in field_mappings.items()
            if lead.get(lead_field) is not None
        }

        await voice.make_call(
            agent["retell_agent_id"],
            lead["phone"],
            metadata={"lead_id": str(lead["id"]), "campaign_id": str(lead["campaign_id"])},
            conversation_flow_id=retell_flow_id,
            retell_llm_dynamic_variables=dynamic_vars or None,
        )
        await _log_event(lead["id"], lead["campaign_id"], "call_made", "voice")
        await _mark_sent(task["id"])
        return True


registry.register("voice", VoiceHandler())


class SMSHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            raise RuntimeError("SMS not configured")

        phone = lead.get("phone")
        if not phone:
            raise RuntimeError("No phone")

        template = await _resolve_template(task["node_id"])
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
                raise RuntimeError(f"Twilio error: {r.text[:200]}")
            data = r.json()

        await _log_event(lead["id"], lead["campaign_id"], "sms_sent", "sms", {"twilio_sid": data.get("sid")})
        await _mark_sent(task["id"])
        return True


registry.register("sms", SMSHandler())


class WebhookHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        node_data = node.get("data") or {}
        webhook_url = (node_data.get("url") or "").strip()
        if not webhook_url:
            raise RuntimeError("No URL")

        method = (node_data.get("method") or "POST").upper()
        custom_headers = node_data.get("headers") or {}
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
                "company": lead.get("company"),
                "phone": lead.get("phone"),
            }

        import httpx

        headers = {"Content-Type": "application/json", **{str(k): str(v) for k, v in custom_headers.items()}}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.request(method, webhook_url, json=payload, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"Webhook {r.status_code}")

        await _log_event(lead["id"], lead["campaign_id"], "webhook_sent", "webhook", {"url": webhook_url})
        await _mark_sent(task["id"])
        return True


registry.register("webhook", WebhookHandler())


class AddTagHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        tag = (node.get("data") or {}).get("tag", "").strip()
        if not tag:
            raise RuntimeError("No tag")

        await execute(
            "UPDATE leads SET tags = array_append(tags, $1) WHERE id=$2 AND NOT ($1 = ANY(tags))", tag, lead["id"]
        )
        await _log_event(lead["id"], lead["campaign_id"], "tag_added", "add_tag", {"tag": tag})
        await _mark_sent(task["id"])
        return True


registry.register("add_tag", AddTagHandler())


class RemoveTagHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        tag = (node.get("data") or {}).get("tag", "").strip()
        if not tag:
            raise RuntimeError("No tag")

        await execute("UPDATE leads SET tags = array_remove(tags, $1) WHERE id=$2", tag, lead["id"])
        await _log_event(lead["id"], lead["campaign_id"], "tag_removed", "remove_tag", {"tag": tag})
        await _mark_sent(task["id"])
        return True


registry.register("remove_tag", RemoveTagHandler())


class HotLeadAlertHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        from app.services.notifier import dispatch_alert

        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        node_data = node.get("data") or {}
        title = renderer.render(
            node_data.get("title") or "🔥 Hot lead", {**lead, "campaign_name": campaign.get("name", "")}
        )
        body = renderer.render(
            node_data.get("body") or "Buy intent", {**lead, "campaign_name": campaign.get("name", "")}
        )
        channel_ids = node_data.get("channel_ids") or []

        await dispatch_alert(title, body, {}, channel_ids or None)
        await _log_event(lead["id"], lead["campaign_id"], "hot_lead_alert", "alert")
        await _mark_sent(task["id"])
        return True


registry.register("hot_lead_alert", HotLeadAlertHandler())


class EnrichHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        from app.services.lead_source_registry import registry as source_registry

        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        node_data = node.get("data") or {}
        source = source_registry.get(node_data.get("enrich_source", ""))
        if not source or not source.is_available:
            raise RuntimeError("Source unavailable")

        enriched = await source.enrich(dict(lead))
        updates = {
            k: getattr(enriched, k)
            for k in ["first_name", "last_name", "email"]
            if getattr(enriched, k) and not lead.get(k)
        }

        if updates:
            set_clause = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(updates.keys()))
            await execute(f"UPDATE leads SET {set_clause} WHERE id=$1", lead["id"], *updates.values())

        await _log_event(lead["id"], lead["campaign_id"], "lead_enriched", "enrich")
        await _mark_sent(task["id"])
        return True


registry.register("enrich", EnrichHandler())


class DataTransformHandler(BaseHandler):
    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        node_data = node.get("data") or {}
        var_name = node_data.get("variable_name", "").strip()
        if not var_name:
            raise RuntimeError("No variable_name")

        prompt = renderer.render(node_data.get("prompt", ""), lead)
        value = await screener.get_llm_response(f"Extract: {prompt}")

        if value:
            import json as _json

            extra = dict(lead.get("extra_data") or {})
            extra[var_name] = value.strip()
            await execute("UPDATE leads SET extra_data=$1 WHERE id=$2", _json.dumps(extra), lead["id"])

        await _log_event(lead["id"], lead["campaign_id"], "data_transformed", "data_transform")
        await _mark_sent(task["id"])
        await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))
        return True


registry.register("data_transform", DataTransformHandler())


class AIComposeHandler(BaseHandler):
    """Generate a per-lead message via LLM and persist it as a draft on the lead.

    Node data:
      - instruction (required): operator's prompt
      - channel (required): downstream channel hint ("email", "linkedin_dm", …)
      - tone (optional, default "professional")
      - max_words (optional, default 120)
      - target_variable (optional, default "ai_draft"): extra_data key to write

    Downstream messaging nodes can reference {{ai_draft}} (or the chosen target_variable)
    in their template body to use the generated text.
    """

    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", task["node_id"])
        node_data = node.get("data") or {}
        instruction = renderer.render(str(node_data.get("instruction", "")).strip(), lead)
        if not instruction:
            raise RuntimeError("action_ai_compose requires `instruction`")

        channel_hint = str(node_data.get("channel", "email")).strip() or "email"
        tone = str(node_data.get("tone", "professional")).strip() or "professional"
        try:
            max_words = int(node_data.get("max_words", 120))
        except (TypeError, ValueError):
            max_words = 120
        target_variable = str(node_data.get("target_variable", "ai_draft")).strip() or "ai_draft"

        body = await screener.generate_message(
            instruction=instruction,
            lead=lead,
            channel=channel_hint,
            tone=tone,
            max_words=max_words,
        )

        import json as _json

        extra = dict(lead.get("extra_data") or {})
        extra[target_variable] = body
        await execute(
            "UPDATE leads SET extra_data=$1 WHERE id=$2",
            _json.dumps(extra),
            lead["id"],
        )

        await _log_event(
            lead["id"],
            lead["campaign_id"],
            "ai_drafted",
            "ai_compose",
            {"variable": target_variable, "channel": channel_hint, "chars": len(body)},
        )
        await _mark_sent(task["id"])
        await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))
        return True


registry.register("ai_compose", AIComposeHandler())


class LeadGenPullHandler(BaseHandler):
    """Fire a lead-gen pull from inside the canvas, with per-campaign cooldown.

    Node data:
      - config_id (required): which lead_gen_config to run
      - cooldown_minutes (optional, default 60): minimum wait between pulls
        from this *node* (debounce key = campaign_id + node_id).

    Side effects:
      - Inserts a lead_gen_pull_runs row when it actually fires.
      - Branches downstream via source_handle:
          * 'fired'    — pull triggered, leads added
          * 'empty'    — pull triggered, zero leads added
          * 'cooldown' — within debounce window, did nothing
          * 'on_error' — handled by the standard _fail_task fallback
    """

    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        from app.services import lead_gen

        node_id = task.get("node_id")
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", node_id)
        d = (node.get("data") or {}) if node else {}
        config_id = d.get("config_id")
        try:
            cooldown_minutes = int(d.get("cooldown_minutes", 60))
        except (TypeError, ValueError):
            cooldown_minutes = 60
        cooldown_seconds = max(0, cooldown_minutes * 60)

        if not config_id:
            raise RuntimeError("action_lead_gen_pull requires `config_id`")

        # Debounce window check.
        recent = await fetch_one(
            """
            SELECT id, fired_at FROM lead_gen_pull_runs
            WHERE campaign_id=$1 AND node_id=$2
              AND fired_at >= NOW() - ($3 || ' seconds')::interval
            ORDER BY fired_at DESC LIMIT 1
            """,
            campaign["id"],
            node_id,
            str(cooldown_seconds),
        )
        if recent:
            log.info(
                f"[dispatcher] lead_gen_pull node={node_id} within cooldown "
                f"({cooldown_minutes}m); skipping. last_fired={recent['fired_at']}"
            )
            await _log_event(
                lead["id"], campaign["id"], "lead_gen_pull_skipped_cooldown", "lead_gen_pull",
                {"node_id": str(node_id), "cooldown_minutes": cooldown_minutes},
            )
            await _mark_sent(task["id"])
            await sequencer.queue_next_nodes(str(lead["id"]), str(node_id), "cooldown")
            return True

        # Fire the pull. lead_gen.run_lead_gen handles credit-budget gating internally.
        try:
            await lead_gen.run_lead_gen(
                campaign_id=str(campaign["id"]),
                config_id=str(config_id),
                triggered_by="canvas",
            )
        except RuntimeError as e:
            # Most likely credit-budget exhausted — log + route on_error so the
            # operator can branch to an alert. Don't blow up the sequence.
            log.warning(f"[dispatcher] lead_gen_pull node={node_id}: {e}")
            await _log_event(
                lead["id"], campaign["id"], "lead_gen_pull_blocked", "lead_gen_pull",
                {"reason": str(e)[:200]},
            )
            await execute(
                "UPDATE queue SET status='failed', failure_reason=$1 WHERE id=$2",
                str(e)[:500], task["id"],
            )
            await sequencer.queue_next_nodes(str(lead["id"]), str(node_id), "on_error")
            return True

        # Look up the most recent run for this config to inspect leads_added.
        run = await fetch_one(
            "SELECT id, leads_added FROM lead_gen_runs WHERE config_id=$1 "
            "ORDER BY started_at DESC LIMIT 1",
            config_id,
        )
        leads_added = int(run["leads_added"]) if run and run.get("leads_added") is not None else 0
        await execute(
            """
            INSERT INTO lead_gen_pull_runs
              (campaign_id, node_id, config_id, lead_gen_run_id, triggered_by_lead_id, cooldown_seconds, fired_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            """,
            campaign["id"],
            node_id,
            config_id,
            run["id"] if run else None,
            lead["id"],
            cooldown_seconds,
        )
        await _log_event(
            lead["id"], campaign["id"], "lead_gen_pull_fired", "lead_gen_pull",
            {"config_id": str(config_id), "leads_added": leads_added},
        )
        await _mark_sent(task["id"])
        await sequencer.queue_next_nodes(
            str(lead["id"]), str(node_id),
            "fired" if leads_added > 0 else "empty",
        )
        return True


registry.register("lead_gen_pull", LeadGenPullHandler())


class CsvImportHandler(BaseHandler):
    """Trigger a CSV import as a node. data.csv_url is the source.

    This is per-campaign, debounced like lead_gen_pull. It pulls the CSV with
    plain HTTP (no auth) and feeds it through the existing manual lead source
    upsert path. Useful for sales teams that drop a fresh CSV in a public
    bucket on a daily cron — the canvas can then pick it up automatically.
    """

    async def execute(self, task: dict, lead: dict, campaign: dict) -> bool:
        import csv as _csv
        import io as _io

        import httpx as _httpx

        from app.services import lead_gen as _lead_gen
        from app.services.lead_sources.base import RawLead as _RawLead

        node_id = task.get("node_id")
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", node_id)
        d = (node.get("data") or {}) if node else {}
        csv_url = str(d.get("csv_url", "")).strip()
        try:
            cooldown_minutes = int(d.get("cooldown_minutes", 60))
        except (TypeError, ValueError):
            cooldown_minutes = 60
        cooldown_seconds = max(0, cooldown_minutes * 60)
        if not csv_url:
            raise RuntimeError("action_csv_import requires `csv_url`")

        recent = await fetch_one(
            "SELECT fired_at FROM lead_gen_pull_runs "
            "WHERE campaign_id=$1 AND node_id=$2 AND fired_at >= NOW() - ($3 || ' seconds')::interval "
            "ORDER BY fired_at DESC LIMIT 1",
            campaign["id"], node_id, str(cooldown_seconds),
        )
        if recent:
            log.info(f"[dispatcher] csv_import node={node_id} cooldown skip")
            await _mark_sent(task["id"])
            await sequencer.queue_next_nodes(str(lead["id"]), str(node_id), "cooldown")
            return True

        async with _httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(csv_url)
        if r.status_code >= 400:
            raise RuntimeError(f"CSV fetch HTTP {r.status_code}")

        reader = _csv.DictReader(_io.StringIO(r.text))
        added = 0
        for row in reader:
            email = (row.get("email") or row.get("Email") or "").strip()
            li = (row.get("linkedin_url") or row.get("LinkedIn") or row.get("linkedin") or "").strip()
            if not email and not li:
                continue
            raw = _RawLead(
                first_name=(row.get("first_name") or row.get("First Name") or "").strip(),
                last_name=(row.get("last_name") or row.get("Last Name") or "").strip(),
                email=email or None,
                linkedin_url=li or None,
                phone=(row.get("phone") or "").strip() or None,
                company=(row.get("company") or row.get("Company") or "").strip(),
                headline=(row.get("headline") or row.get("Title") or "").strip(),
            )
            inserted = await _lead_gen.upsert_lead(str(campaign["id"]), raw, "csv_import")
            if inserted:
                added += 1

        await execute(
            "INSERT INTO lead_gen_pull_runs (campaign_id, node_id, cooldown_seconds, fired_at) "
            "VALUES ($1, $2, $3, NOW())",
            campaign["id"], node_id, cooldown_seconds,
        )
        await _log_event(
            lead["id"], campaign["id"], "csv_import_done", "csv_import",
            {"csv_url": csv_url[:200], "added": added},
        )
        await _mark_sent(task["id"])
        await sequencer.queue_next_nodes(
            str(lead["id"]), str(node_id),
            "fired" if added > 0 else "empty",
        )
        return True


registry.register("csv_import", CsvImportHandler())


async def _process_task(task: dict, worker_id: str) -> None:
    # Idempotency claim — task["id"] doubles as the dedupe key. If a prior worker
    # already executed this task but crashed before _mark_sent flipped the row,
    # the claim fails and we skip the side-effect. The queue-table status is
    # then advanced to 'sent' so the next run_once doesn't re-lock it.
    claim = await fetch_one(
        "INSERT INTO processed_commands (command_id, channel, task_id, lead_id, status) "
        "VALUES ($1, $2, $1, $3, 'claimed') ON CONFLICT (command_id) DO NOTHING "
        "RETURNING command_id",
        task["id"],
        task["channel"],
        task["lead_id"],
    )
    if claim is None:
        log.warning(f"[dispatcher] task={task['id']} already processed; advancing queue status")
        await _mark_sent(task["id"])
        return

    campaign = await fetch_one("SELECT * FROM campaigns WHERE id=$1", task["campaign_id"])
    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", task["lead_id"])

    if not campaign or not lead:
        await _fail_task(task["id"], "campaign or lead not found", task["retry_count"])
        return

    if not _in_active_hours(campaign, lead):
        next_start = _next_window_start(campaign, lead)
        await execute(
            "UPDATE queue SET status='queued', locked_by=NULL, locked_at=NULL, scheduled_at=$1 WHERE id=$2",
            next_start,
            task["id"],
        )
        return

    if campaign.get("simulation_mode"):
        log.info(f"[dispatcher:sim] task={task['id']} channel={task['channel']}")
        await _log_event(lead["id"], campaign["id"], f"simulated_{task['channel']}", task["channel"])
        await _mark_sent(task["id"])
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
                    lead["id"],
                    campaign["id"],
                    "blacklisted_skip",
                    ch,
                    {"reason": "lead matched blacklist"},
                )
                await execute(
                    "UPDATE queue SET status='skipped', failure_reason=$1 WHERE id=$2",
                    "blacklisted",
                    task["id"],
                )
                # Advance the DAG so the lead isn't stuck — this matches how
                # other "soft skip" paths (e.g. invalid IG recipient) behave.
                await sequencer.queue_next_nodes(str(lead["id"]), str(task["node_id"]))
                return

        # Cross-lead ABM gate (Gap 5): if any other lead at this company was
        # already contacted within company_lock_hours, skip this delivery.
        if ch in _DELIVERY_CHANNELS and lead.get("company_id"):
            lock_hours_raw = campaign.get("company_lock_hours")
            try:
                lock_hours = int(lock_hours_raw) if lock_hours_raw is not None else 0
            except (TypeError, ValueError):
                lock_hours = 0
            if lock_hours > 0:
                recent = await fetch_one(
                    """
                    SELECT 1 FROM queue q
                    JOIN leads l ON l.id = q.lead_id
                    WHERE l.company_id = $1 AND l.id <> $2
                      AND q.status = 'sent'
                      AND q.sent_at >= NOW() - ($3 || ' hours')::interval
                    LIMIT 1
                    """,
                    lead["company_id"],
                    lead["id"],
                    str(lock_hours),
                )
                if recent:
                    log.info(
                        f"[dispatcher] task={task['id']} held: another contact at "
                        f"company {lead['company_id']} reached within {lock_hours}h"
                    )
                    await execute(
                        "UPDATE queue SET status='queued', locked_by=NULL, locked_at=NULL, "
                        "scheduled_at=NOW() + ($1 || ' hours')::interval WHERE id=$2",
                        str(lock_hours),
                        task["id"],
                    )
                    return

        # SOTA Registry Dispatch
        success = await registry.handle(task, lead, campaign)
        if not success:
            # Handler indicated we should stop processing for now (e.g. daily cap)
            return
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
        BATCH_SIZE,
        worker_id,
    )
    if not tasks:
        return
    for task in tasks:
        await _process_task(task, worker_id)


async def _queue_invitations() -> None:
    campaigns = await fetch_all("SELECT * FROM campaigns WHERE status='active'")
    for campaign in campaigns:
        if not _in_active_hours(campaign):
            continue

        leads = await fetch_all(
            "SELECT * FROM leads WHERE campaign_id=$1 AND invited_at IS NULL "
            "AND linkedin_account_id IS NULL AND status='active' ORDER BY id LIMIT 100",
            campaign["id"],
        )
        if not leads:
            continue

        accounts = await fetch_all(
            "SELECT la.* FROM linkedin_accounts la "
            "JOIN campaign_linkedin_accounts cla ON cla.account_id=la.id "
            "WHERE cla.campaign_id=$1 AND la.is_active=TRUE",
            campaign["id"],
        )
        if not accounts:
            continue

        tz = campaign.get("timezone") or "UTC"
        counts_rows = await fetch_all(
            "SELECT l.linkedin_account_id, COUNT(*) AS cnt FROM queue q "
            "JOIN leads l ON l.id=q.lead_id WHERE q.channel='linkedin_invite' "
            "AND q.campaign_id=$1 AND q.status IN ('queued','locked','sent') "
            "AND q.scheduled_at >= DATE_TRUNC('day', NOW() AT TIME ZONE $2) "
            "GROUP BY l.linkedin_account_id",
            campaign["id"],
            tz,
        )
        counts = {str(r["linkedin_account_id"]): r["cnt"] for r in counts_rows}

        invite_node = await fetch_one(
            "SELECT id FROM sequence_nodes WHERE campaign_id=$1 AND node_type='action_linkedin_invite' LIMIT 1",
            campaign["id"],
        )

        for lead in leads:
            chosen = None
            for acct in sorted(accounts, key=lambda a: counts.get(str(a["id"]), 0)):
                if counts.get(str(acct["id"]), 0) < acct["daily_invite_cap"]:
                    chosen = acct
                    break
            if not chosen:
                break

            result = await fetch_one(
                "UPDATE leads SET linkedin_account_id=$1 WHERE id=$2 AND linkedin_account_id IS NULL RETURNING id",
                chosen["id"],
                lead["id"],
            )
            if not result:
                continue

            counts[str(chosen["id"])] = counts.get(str(chosen["id"]), 0) + 1
            await execute(
                "INSERT INTO queue (campaign_id, lead_id, node_id, channel, status, scheduled_at) "
                "VALUES ($1, $2, $3, 'linkedin_invite', 'queued', NOW()) ON CONFLICT DO NOTHING",
                campaign["id"],
                lead["id"],
                invite_node["id"] if invite_node else None,
            )


async def _check_acceptances() -> None:
    pending = await fetch_all(
        "SELECT l.*, la.unipile_id AS unipile_account_id FROM leads l "
        "JOIN linkedin_accounts la ON la.id=l.linkedin_account_id "
        "WHERE l.invited_at IS NOT NULL AND l.accepted_at IS NULL AND l.status='active' "
        "ORDER BY l.invited_at ASC LIMIT 100",
    )
    for lead in pending:
        try:
            profile = await linkedin.get_profile(_public_id(lead["linkedin_url"]), lead["unipile_account_id"])
            if profile.get("network_distance") != "FIRST_DEGREE":
                continue
            result = await fetch_one(
                "UPDATE leads SET accepted_at=NOW() WHERE id=$1 AND accepted_at IS NULL RETURNING id", lead["id"]
            )
            if not result:
                continue
            await _log_event(lead["id"], lead["campaign_id"], "invite_accepted", "linkedin_invite")
            await sequencer.schedule_sequence(str(lead["id"]))
        except Exception as e:
            log.warning(f"[acceptances] Lead {lead['id']} error: {e}")
