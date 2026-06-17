"""CONTRACT-2: the channel payload-rendering layer (Python → Rust contract).

The Rust handlers are designed around a self-contained payload (models.rs):
``body``/``subject`` arrive RENDERED, the Unipile sender account and transport
config arrive as plain payload fields, and the recipient identity
(``attendee_identifier``) is resolved per channel. The channel nodes, however,
emit only ``*_template`` strings and a connection name — until this layer
existed, every channel send reached the muscle starved (no body, no account,
no attendee) and failed validation inside the handler.

This module is pure (no settings import, no I/O) so the contract is unit-
testable in isolation. ``commands.build_command`` is the single call site —
the one seam where lead + contact + node payload + connection bundle coexist.

Template syntax: ``{{contact.first_name}}``, ``{{lead.custom_fields.role}}``,
``{{company}}`` — dotted paths over the contact/lead rows with a
custom_fields fallback at each root. Unknown variables render as "".
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.events import ChannelType
from app.services.email_tracking import inject_tracking

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")

# Channels whose payload this layer enriches. Sources/ai/crm commands pass
# through untouched — their nodes already emit self-contained payloads.
_UNIPILE_CHANNELS = frozenset(
    {
        ChannelType.LINKEDIN_DM,
        ChannelType.LINKEDIN_INMAIL,
        ChannelType.LINKEDIN_INVITE,
        ChannelType.LINKEDIN_PROFILE_VIEW,
        ChannelType.WHATSAPP,
        ChannelType.INSTAGRAM,
        ChannelType.TELEGRAM,
    }
)
_RENDERED_CHANNELS = _UNIPILE_CHANNELS | {
    ChannelType.EMAIL,
    ChannelType.SMS,
    ChannelType.VOICE,
    ChannelType.WEBHOOK,
}

# ``*_template`` payload key -> canonical rendered key the muscle reads.
_TEMPLATE_FIELDS: dict[str, str] = {
    "subject_template": "subject",
    "body_template": "body",
    "message_template": "body",
    "title_template": "title",
}

# Per-channel chat-session column persisted into lead.custom_fields by
# _apply_lead_mutations (CONTRACT-3) when send_chat opens a chat.
_CHAT_SESSION_KEY: dict[ChannelType, str] = {
    ChannelType.LINKEDIN_DM: "chat_id",
    ChannelType.WHATSAPP: "chat_id",
    ChannelType.INSTAGRAM: "ig_chat_id",
    ChannelType.TELEGRAM: "tg_chat_id",
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _dig(root: dict[str, Any], parts: list[str]) -> Any:
    """Walk a dotted path; at each miss, retry inside custom_fields."""
    node: Any = root
    for part in parts:
        if not isinstance(node, dict):
            return None
        if part in node:
            node = node[part]
            continue
        cf = _as_dict(node.get("custom_fields"))
        if part in cf:
            node = cf[part]
            continue
        return None
    return node


def render_template(
    template: str, *, lead: dict[str, Any], contact: dict[str, Any] | None
) -> str:
    """Substitute {{var}} placeholders from contact/lead data; unknown -> ""."""
    contact = contact or {}
    roots: dict[str, dict[str, Any]] = {"contact": contact, "lead": lead}

    def _lookup(match: re.Match[str]) -> str:
        parts = match.group(1).split(".")
        if parts[0] in roots:
            value = _dig(roots[parts[0]], parts[1:])
        else:
            # Bare name: try contact first (the documented convention is
            # {{contact.first_name}}, but {{first_name}}/{{company}} appear
            # in operator templates), then the lead.
            value = _dig(contact, parts)
            if value is None:
                value = _dig(lead, parts)
        if value is None or isinstance(value, (dict, list)):
            return ""
        return str(value)

    return _VAR_RE.sub(_lookup, template)


def _whatsapp_jid(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"{digits}@s.whatsapp.net" if digits else ""


def render_channel_payload(
    channel: ChannelType,
    payload: dict[str, Any],
    *,
    lead: dict[str, Any],
    contact: dict[str, Any] | None,
    bundle: dict[str, Any] | None,
    tracking_base: str | None = None,
    tracking_token: str | None = None,
) -> dict[str, Any]:
    """Return a NEW payload fulfilling the Rust handler contract.

    - every ``*_template`` field is rendered into its canonical key
      (subject/body/title) unless the node already provided one
    - Unipile channels: sender account + base from the connection bundle,
      chat-session reuse from lead.custom_fields, per-channel attendee
    - email: non-secret SMTP transport fields from the bundle; when
      ``tracking_base`` + ``tracking_token`` are supplied (T3), the rendered
      body gets an open pixel + click-redirect link rewrites
    Non-channel commands (sources/ai/crm) are returned unchanged.
    """
    if channel not in _RENDERED_CHANNELS:
        return payload

    bundle = bundle or {}
    contact = contact or {}
    lead_cf = _as_dict(lead.get("custom_fields"))
    contact_cf = _as_dict(contact.get("custom_fields"))
    out = dict(payload)

    for template_key, rendered_key in _TEMPLATE_FIELDS.items():
        template = out.get(template_key)
        if isinstance(template, str) and template and not out.get(rendered_key):
            out[rendered_key] = render_template(template, lead=lead, contact=contact)

    if channel in _UNIPILE_CHANNELS:
        if not out.get("unipile_account_id"):
            out["unipile_account_id"] = (
                bundle.get("account_id") or bundle.get("unipile_account_id") or ""
            )
        if not out.get("unipile_base") and bundle.get("base_url"):
            out["unipile_base"] = bundle["base_url"]
        # provider_id persisted by an earlier invite/profile_view (CONTRACT-3).
        if not out.get("provider_id") and lead_cf.get("provider_id"):
            out["provider_id"] = lead_cf["provider_id"]
        # Session reuse: a prior send_chat opened the chat and CONTRACT-3
        # persisted its id — follow-ups must land in the same thread.
        session_key = _CHAT_SESSION_KEY.get(channel)
        if session_key and not out.get("chat_id") and lead_cf.get(session_key):
            out["chat_id"] = lead_cf[session_key]
        if not out.get("attendee_identifier"):
            attendee = ""
            if channel == ChannelType.WHATSAPP:
                attendee = _whatsapp_jid(str(contact.get("phone") or ""))
            elif channel == ChannelType.INSTAGRAM:
                attendee = str(contact_cf.get("instagram_username") or "")
            elif channel == ChannelType.TELEGRAM:
                attendee = str(contact_cf.get("telegram_username") or "")
            # LinkedIn resolves via provider_id/linkedin_url in the handler.
            if attendee:
                out["attendee_identifier"] = attendee

    elif channel == ChannelType.EMAIL:
        # Non-secret transport config rides the payload; only smtp_password
        # stays behind the credential ref (email.rs redeems it by field).
        for key in ("smtp_host", "smtp_port", "smtp_username", "smtp_use_tls"):
            if out.get(key) is None and bundle.get(key) is not None:
                out[key] = bundle[key]
        if not out.get("from"):
            out["from"] = bundle.get("from") or bundle.get("smtp_username") or ""
        # T3: inject open pixel + click tracking into the rendered HTML body.
        # Opt-in per send: only when the caller supplied a signed token + base.
        if tracking_base and tracking_token and out.get("body"):
            out["body"] = inject_tracking(str(out["body"]), base=tracking_base, token=tracking_token)

    return out
