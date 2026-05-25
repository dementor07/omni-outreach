"""Fat-payload resolver for the SOTA muscle.

The sequencer used to ship thin ActionCommands (just node.data + lead snapshot)
and rely on a second Python worker to look up templates, sender accounts, and
secrets. The muscle is a pure execution engine — it cannot do those lookups —
so this module pre-resolves everything the Rust handlers need:

  • template body + subject (rendered against the lead)
  • sender account non-secret fields (smtp_host, unipile_id, retell_agent_id, …)
  • node config (cooldown_minutes, csv_url, instruction, …)
  • per-lead proxy_settings (for LinkedIn especially)
  • an opaque ``credential_ref`` the muscle redeems for any actual secrets

Anything secret travels via a one-shot ``credential_ref`` minted into
``credential_refs`` (see app/routers/internal.py). The muscle redeems it on
demand via ``GET /internal/credentials/{ref}`` and releases it after use.

Returns a tuple ``(payload, credential_ref)`` where credential_ref may be
``None`` for channels that need no secrets (tag, webhook, lead_gen_pull, …).
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.events import ChannelType
from app.db import fetch_one
from app.services import renderer
from app.services.encryption import decrypt
from app.routers.internal import mint_credential_ref

log = logging.getLogger(__name__)


# Channels that contact the lead directly (used by ABM / blacklist gates).
DELIVERY_CHANNELS: frozenset[str] = frozenset(
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


def _maybe_decrypt(value: str | None) -> str | None:
    """Decrypt a Fernet-encrypted credential, or pass through obvious plaintext.

    Fernet tokens always start with ``gAAAAA`` (URL-safe base64 of the
    Fernet version byte 0x80). Anything else is treated as legacy plaintext.
    A token that LOOKS like Fernet but fails to decrypt is a real error
    (corrupted ciphertext, rotated key, tampering) and is raised instead of
    silently returning ciphertext bytes as the password.
    """
    if not value:
        return value
    if not value.startswith("gAAAAA"):
        return value  # legacy plaintext row
    return decrypt(value)


async def _resolve_template_for_node(node_id: str) -> dict | None:
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


def _public_id(linkedin_url: str | None) -> str | None:
    if not linkedin_url:
        return None
    return linkedin_url.strip().rstrip("/").split("?")[0].split("/in/")[-1]


async def _linkedin_account(lead: dict) -> dict | None:
    acct_id = lead.get("linkedin_account_id")
    if not acct_id:
        return None
    return await fetch_one("SELECT * FROM linkedin_accounts WHERE id=$1", acct_id)


async def _proxy_settings_for_account(account: dict | None) -> dict[str, str]:
    if not account:
        return {}
    raw = account.get("proxy_settings") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k in ("scheme", "host", "port", "username", "password"):
        v = raw.get(k)
        if v is not None and v != "":
            out[k] = str(v)
    return out


# ── Per-channel resolvers ────────────────────────────────────────────────────


async def _resolve_email(node: dict, lead: dict) -> tuple[dict, str | None]:
    config = node.get("data") or {}
    acct = await fetch_one(
        "SELECT * FROM email_accounts WHERE id=$1",
        config.get("email_account_id"),
    )
    if not acct:
        raise RuntimeError("email_account_id missing or invalid")
    template = await _resolve_template_for_node(node["id"])
    if not template:
        raise RuntimeError("email node has no template")

    subject = renderer.render(template["subject"] or "", lead)
    body = renderer.render(template["body"] or "", lead)

    payload: dict[str, Any] = {
        "from_name": acct.get("from_name"),
        "from_email": acct.get("from_email"),
        "smtp_host": acct.get("smtp_host"),
        "smtp_port": acct.get("smtp_port"),
        "smtp_username": acct.get("smtp_username"),
        "smtp_use_tls": bool(acct.get("smtp_use_tls", True)),
        "to_email": lead.get("email"),
        "subject": subject,
        "body_html": body,
    }
    ref = await mint_credential_ref("email", {"smtp_password": _maybe_decrypt(acct.get("smtp_password"))})
    return payload, ref


async def _resolve_linkedin_invite(node: dict, lead: dict) -> tuple[dict, str | None]:
    acct = await _linkedin_account(lead)
    if not acct:
        raise RuntimeError("linkedin_account_id missing on lead")
    payload: dict[str, Any] = {
        "unipile_account_id": acct.get("unipile_id"),
        "public_id": _public_id(lead.get("linkedin_url")),
        "provider_id": (node.get("data") or {}).get("provider_id"),
        "proxy_settings": await _proxy_settings_for_account(acct),
    }
    ref = await mint_credential_ref(
        "linkedin_invite",
        {"unipile_api_key": _maybe_decrypt(acct.get("unipile_dsn") or acct.get("api_key"))},
    )
    return payload, ref


async def _resolve_linkedin_chat(channel: str, node: dict, lead: dict) -> tuple[dict, str | None]:
    acct = await _linkedin_account(lead)
    if not acct:
        raise RuntimeError("linkedin_account_id missing on lead")
    template = await _resolve_template_for_node(node["id"])
    if not template:
        raise RuntimeError(f"{channel} node has no template")
    message = renderer.render(template["body"] or "", lead)
    payload: dict[str, Any] = {
        "unipile_account_id": acct.get("unipile_id"),
        "public_id": _public_id(lead.get("linkedin_url")),
        "provider_id": (node.get("data") or {}).get("provider_id"),
        "chat_id": lead.get("chat_id"),
        "message": message,
        "proxy_settings": await _proxy_settings_for_account(acct),
    }
    ref = await mint_credential_ref(
        channel,
        {"unipile_api_key": _maybe_decrypt(acct.get("unipile_dsn") or acct.get("api_key"))},
    )
    return payload, ref


async def _resolve_linkedin_inmail(node: dict, lead: dict) -> tuple[dict, str | None]:
    acct = await _linkedin_account(lead)
    if not acct:
        raise RuntimeError("linkedin_account_id missing on lead")
    template = await _resolve_template_for_node(node["id"])
    if not template:
        raise RuntimeError("inmail node has no template")
    subject = renderer.render(template["subject"] or "", lead)
    body = renderer.render(template["body"] or "", lead)
    payload: dict[str, Any] = {
        "unipile_account_id": acct.get("unipile_id"),
        "public_id": _public_id(lead.get("linkedin_url")),
        "provider_id": (node.get("data") or {}).get("provider_id"),
        "subject": subject,
        "message": body,
        "proxy_settings": await _proxy_settings_for_account(acct),
    }
    ref = await mint_credential_ref(
        "linkedin_inmail",
        {"unipile_api_key": _maybe_decrypt(acct.get("unipile_dsn") or acct.get("api_key"))},
    )
    return payload, ref


async def _resolve_linkedin_profile_view(node: dict, lead: dict) -> tuple[dict, str | None]:
    acct = await _linkedin_account(lead)
    if not acct:
        raise RuntimeError("linkedin_account_id missing on lead")
    payload: dict[str, Any] = {
        "unipile_account_id": acct.get("unipile_id"),
        "public_id": _public_id(lead.get("linkedin_url")),
        "proxy_settings": await _proxy_settings_for_account(acct),
    }
    ref = await mint_credential_ref(
        "linkedin_profile_view",
        {"unipile_api_key": _maybe_decrypt(acct.get("unipile_dsn") or acct.get("api_key"))},
    )
    return payload, ref


async def _resolve_whatsapp(node: dict, lead: dict) -> tuple[dict, str | None]:
    acct = await _linkedin_account(lead)
    if not acct:
        raise RuntimeError("linkedin_account_id missing on lead (whatsapp shares Unipile account)")
    template = await _resolve_template_for_node(node["id"])
    if not template:
        raise RuntimeError("whatsapp node has no template")
    message = renderer.render(template["body"] or "", lead)
    phone = lead.get("phone")
    attendee_id = f"{phone}@s.whatsapp.net" if phone else None
    payload: dict[str, Any] = {
        "unipile_account_id": acct.get("unipile_id"),
        "attendee_id": attendee_id,
        "chat_id": lead.get("chat_id"),
        "message": message,
        "proxy_settings": await _proxy_settings_for_account(acct),
    }
    ref = await mint_credential_ref(
        "whatsapp",
        {"unipile_api_key": _maybe_decrypt(acct.get("unipile_dsn") or acct.get("api_key"))},
    )
    return payload, ref


async def _resolve_instagram(node: dict, lead: dict) -> tuple[dict, str | None]:
    d = node.get("data") or {}
    acct = await fetch_one(
        "SELECT * FROM instagram_accounts WHERE id=$1",
        d.get("instagram_account_id"),
    )
    if not acct:
        raise RuntimeError("instagram_account_id missing on node")
    template = await _resolve_template_for_node(node["id"])
    if not template:
        raise RuntimeError("instagram node has no template")
    message = renderer.render(template["body"] or "", lead)
    payload: dict[str, Any] = {
        "unipile_account_id": acct.get("unipile_id"),
        "instagram_username": lead.get("instagram_username"),
        "ig_chat_id": lead.get("ig_chat_id"),
        "message": message,
    }
    ref = await mint_credential_ref(
        "instagram",
        {"unipile_api_key": _maybe_decrypt(acct.get("api_key"))},
    )
    return payload, ref


async def _resolve_telegram(node: dict, lead: dict) -> tuple[dict, str | None]:
    d = node.get("data") or {}
    acct = await fetch_one(
        "SELECT * FROM telegram_accounts WHERE id=$1",
        d.get("telegram_account_id"),
    )
    if not acct:
        raise RuntimeError("telegram_account_id missing on node")
    template = await _resolve_template_for_node(node["id"])
    if not template:
        raise RuntimeError("telegram node has no template")
    message = renderer.render(template["body"] or "", lead)
    payload: dict[str, Any] = {
        "unipile_account_id": acct.get("unipile_id"),
        "telegram_username": lead.get("telegram_username") or lead.get("phone"),
        "tg_chat_id": lead.get("tg_chat_id"),
        "message": message,
    }
    ref = await mint_credential_ref(
        "telegram",
        {"unipile_api_key": _maybe_decrypt(acct.get("api_key"))},
    )
    return payload, ref


async def _resolve_voice(node: dict, lead: dict) -> tuple[dict, str | None]:
    from app.config import settings

    config = node.get("data") or {}
    agent = await fetch_one(
        "SELECT * FROM voice_agents WHERE id=$1",
        config.get("voice_agent_id"),
    )
    if not agent:
        raise RuntimeError("voice_agent_id missing on node")
    field_mappings: dict = config.get("field_mappings") or {}
    dynamic_vars: dict[str, str] = {
        var_name: str(lead.get(field_name) or "")
        for var_name, field_name in field_mappings.items()
        if lead.get(field_name) is not None
    }
    payload: dict[str, Any] = {
        "retell_agent_id": agent.get("retell_agent_id"),
        "to_phone": lead.get("phone"),
        "from_number": settings.retell_from_number,
        "conversation_flow_id": config.get("retell_flow_id") if config.get("mode") == "flow" else None,
        "retell_llm_dynamic_variables": dynamic_vars,
        "metadata": {"lead_id": str(lead["id"]), "campaign_id": str(lead["campaign_id"])},
    }
    ref = await mint_credential_ref("voice", {"retell_api_key": settings.retell_api_key})
    return payload, ref


async def _resolve_sms(node: dict, lead: dict) -> tuple[dict, str | None]:
    from app.config import settings

    template = await _resolve_template_for_node(node["id"])
    if not template:
        raise RuntimeError("sms node has no template")
    message = renderer.render(template["body"] or "", lead)
    payload: dict[str, Any] = {
        "to_phone": lead.get("phone"),
        "message": message,
    }
    ref = await mint_credential_ref(
        "sms",
        {
            "twilio_account_sid": settings.twilio_account_sid,
            "twilio_auth_token": settings.twilio_auth_token,
            "twilio_from_number": settings.twilio_from_number,
        },
    )
    return payload, ref


async def _resolve_webhook(node: dict, lead: dict) -> tuple[dict, None]:
    d = node.get("data") or {}
    url = (d.get("url") or "").strip()
    method = (d.get("method") or "POST").upper()
    headers = d.get("headers") or {}
    body_template = d.get("body_template")
    if body_template:
        rendered = renderer.render(str(body_template), lead)
        body: Any = {"rendered": rendered}
    else:
        body = {
            "lead_id": str(lead["id"]),
            "campaign_id": str(lead["campaign_id"]),
            "email": lead.get("email"),
            "first_name": lead.get("first_name"),
            "company": lead.get("company"),
            "phone": lead.get("phone"),
        }
    payload: dict[str, Any] = {
        "url": url,
        "method": method,
        "headers": {str(k): str(v) for k, v in headers.items()},
        "body": body,
    }
    return payload, None


async def _resolve_tag(node: dict) -> tuple[dict, None]:
    d = node.get("data") or {}
    return {"tag": (d.get("tag") or "").strip()}, None


async def _resolve_enrich(node: dict, lead: dict) -> tuple[dict, str | None]:
    from app.config import settings

    d = node.get("data") or {}
    source = (d.get("enrich_source") or "").strip().lower()
    payload: dict[str, Any] = {
        "source": source,
        "linkedin_url": lead.get("linkedin_url"),
        "email": lead.get("email"),
        "first_name": lead.get("first_name"),
        "last_name": lead.get("last_name"),
        "company": lead.get("company"),
    }
    bundle = {
        "apollo_api_key": settings.apollo_api_key,
        "hunter_api_key": settings.hunter_api_key,
        "proxycurl_api_key": settings.proxycurl_api_key,
    }
    ref = await mint_credential_ref("enrich", bundle)
    return payload, ref


async def _resolve_hot_lead_alert(node: dict, lead: dict, campaign: dict) -> tuple[dict, str | None]:
    from app.config import settings

    d = node.get("data") or {}
    title = renderer.render(d.get("title") or "🔥 Hot lead", {**lead, "campaign_name": campaign.get("name", "")})
    body = renderer.render(d.get("body") or "Buy intent", {**lead, "campaign_name": campaign.get("name", "")})
    channel_ids = d.get("channel_ids") or []

    # Pull the operator-configured alert channels so the Rust handler can
    # fan out without ever talking to Postgres.
    if channel_ids:
        rows = await _fetch_channels(channel_ids)
    else:
        rows = await _fetch_channels(None)
    targets: list[dict] = []
    for row in rows:
        targets.append(
            {
                "kind": row["channel_type"],
                "target": row.get("webhook_url") or row.get("email"),
                "target_ref": "alert_bundle",
            }
        )

    payload: dict[str, Any] = {"title": title, "body": body, "targets": targets}
    ref = await mint_credential_ref(
        "hot_lead_alert",
        {"resend_api_key": settings.resend_api_key},
    )
    return payload, ref


async def _fetch_channels(channel_ids: list[str] | None) -> list[dict]:
    if channel_ids:
        from app.db import fetch_all

        return await fetch_all(
            "SELECT channel_type, webhook_url, email FROM notification_channels "
            "WHERE id = ANY($1::uuid[]) AND is_active=TRUE",
            channel_ids,
        )
    from app.db import fetch_all

    return await fetch_all(
        "SELECT channel_type, webhook_url, email FROM notification_channels WHERE is_active=TRUE",
    )


async def _resolve_transform(node: dict, lead: dict) -> tuple[dict, str | None]:
    from app.config import settings

    d = node.get("data") or {}
    instruction = renderer.render(str(d.get("prompt") or d.get("instruction") or ""), lead)
    payload: dict[str, Any] = {
        "instruction": instruction,
        "variable_name": str(d.get("variable_name") or "").strip(),
        "target_variable": str(d.get("target_variable") or "ai_draft").strip(),
        "tone": str(d.get("tone") or "professional"),
        "channel_hint": str(d.get("channel") or "email"),
        "max_words": int(d.get("max_words") or 120),
    }
    ref = await mint_credential_ref(
        "transform",
        {"anthropic_api_key": settings.anthropic_api_key},
    )
    return payload, ref


async def _resolve_leadgen(node: dict) -> tuple[dict, None]:
    # The muscle delegates back to the control plane (POST /internal/lead-gen/...).
    # All the muscle needs is the node config so it can pass it through.
    return dict(node.get("data") or {}), None


# ── Public entry point ───────────────────────────────────────────────────────


async def resolve_command_payload(
    channel: ChannelType,
    node: dict,
    lead: dict,
    campaign: dict,
) -> tuple[dict[str, Any], str | None]:
    """Returns (fat_payload, credential_ref).

    The fat_payload is everything the Rust handler needs that isn't secret.
    The credential_ref (if not None) is a one-shot opaque token the muscle
    redeems via GET /internal/credentials/{ref} to get the actual secrets.
    """
    try:
        if channel == ChannelType.EMAIL:
            return await _resolve_email(node, lead)
        if channel == ChannelType.LINKEDIN_INVITE:
            return await _resolve_linkedin_invite(node, lead)
        if channel == ChannelType.LINKEDIN_DM:
            return await _resolve_linkedin_chat("linkedin_dm", node, lead)
        if channel == ChannelType.LINKEDIN_INMAIL:
            return await _resolve_linkedin_inmail(node, lead)
        if channel == ChannelType.LINKEDIN_PROFILE_VIEW:
            return await _resolve_linkedin_profile_view(node, lead)
        if channel == ChannelType.WHATSAPP:
            return await _resolve_whatsapp(node, lead)
        if channel == ChannelType.INSTAGRAM:
            return await _resolve_instagram(node, lead)
        if channel == ChannelType.TELEGRAM:
            return await _resolve_telegram(node, lead)
        if channel == ChannelType.VOICE:
            return await _resolve_voice(node, lead)
        if channel == ChannelType.SMS:
            return await _resolve_sms(node, lead)
        if channel == ChannelType.WEBHOOK:
            return await _resolve_webhook(node, lead)
        if channel in (ChannelType.ADD_TAG, ChannelType.REMOVE_TAG):
            return await _resolve_tag(node)
        if channel == ChannelType.ENRICH:
            return await _resolve_enrich(node, lead)
        if channel == ChannelType.HOT_LEAD_ALERT:
            return await _resolve_hot_lead_alert(node, lead, campaign)
        if channel in (ChannelType.DATA_TRANSFORM, ChannelType.AI_COMPOSE):
            return await _resolve_transform(node, lead)
        if channel in (ChannelType.LEAD_GEN_PULL, ChannelType.CSV_IMPORT):
            return await _resolve_leadgen(node)
    except Exception as e:  # noqa: BLE001
        log.error("[command_resolver] %s: %s", channel.value, e)
        raise

    raise RuntimeError(f"no resolver for channel {channel.value}")
