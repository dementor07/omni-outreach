"""CONTRACT-2 regression — the channel payload-rendering layer.

The Rust handlers (email.rs / unipile.rs / sms.rs) consume a self-contained
payload: rendered ``body``/``subject``, ``unipile_account_id`` + attendee
identity for chat channels, SMTP transport fields for email. The channel
nodes emit only ``*_template`` + a connection name, so the contract is
fulfilled by ``app.execution.render.render_channel_payload``, called from
``commands.build_command`` (the one seam with lead + contact + bundle).

These are FUNCTIONAL tests of the pure renderer plus a wire-in assertion
that build_command actually routes through it. Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.events import ChannelType
from app.execution.render import render_channel_payload, render_template

BACKEND = Path(__file__).resolve().parents[2] / "backend"

LEAD = {
    "id": "lead-1",
    "custom_fields": {
        "chat_id": "chat-li-1",
        "ig_chat_id": "chat-ig-1",
        "tg_chat_id": "chat-tg-1",
        "provider_id": "ACoAA123",
        "role": "CTO",
    },
}
CONTACT = {
    "first_name": "Priya",
    "last_name": "Sharma",
    "company": "Acme",
    "phone": "+91 98765-43210",
    "email": "priya@acme.io",
    "custom_fields": {
        "instagram_username": "priya.builds",
        "telegram_username": "priya_s",
        "location": "Bengaluru",
    },
}
BUNDLE = {
    "api_key": "secret-key",
    "base_url": "https://api6.unipile.com:13670",
    "account_id": "uni-acct-9",
}


# ── template engine ──────────────────────────────────────────────────────────

def test_render_template_dotted_and_custom_fields():
    out = render_template(
        "Hi {{contact.first_name}} ({{lead.custom_fields.role}} at {{contact.company}}), "
        "from {{contact.location}}",
        lead=LEAD,
        contact=CONTACT,
    )
    # contact.location resolves through the contact's custom_fields fallback.
    assert out == "Hi Priya (CTO at Acme), from Bengaluru"


def test_render_template_bare_names_and_unknown_blank():
    out = render_template("{{first_name}} / {{role}} / {{nonexistent.var}}", lead=LEAD, contact=CONTACT)
    assert out == "Priya / CTO / "


# ── per-channel contracts ────────────────────────────────────────────────────

def test_whatsapp_payload_fulfils_send_chat_contract():
    payload = {"connection_name": "wa", "body_template": "Hi {{contact.first_name}}"}
    out = render_channel_payload(
        ChannelType.WHATSAPP, payload, lead=LEAD, contact=CONTACT, bundle=BUNDLE
    )
    assert out["body"] == "Hi Priya"
    assert out["unipile_account_id"] == "uni-acct-9"
    assert out["unipile_base"] == BUNDLE["base_url"]
    assert out["attendee_identifier"] == "919876543210@s.whatsapp.net"
    assert out["chat_id"] == "chat-li-1"  # session reuse (CONTRACT-3 persisted)
    # input payload must NOT be mutated
    assert "body" not in payload and "unipile_account_id" not in payload


def test_instagram_and_telegram_attendees_and_sessions():
    ig = render_channel_payload(
        ChannelType.INSTAGRAM, {"body_template": "x"}, lead=LEAD, contact=CONTACT, bundle=BUNDLE
    )
    tg = render_channel_payload(
        ChannelType.TELEGRAM, {"body_template": "x"}, lead=LEAD, contact=CONTACT, bundle=BUNDLE
    )
    assert ig["attendee_identifier"] == "priya.builds" and ig["chat_id"] == "chat-ig-1"
    assert tg["attendee_identifier"] == "priya_s" and tg["chat_id"] == "chat-tg-1"


def test_linkedin_dm_uses_message_template_and_provider_id():
    out = render_channel_payload(
        ChannelType.LINKEDIN_DM,
        {"message_template": "Hi {{contact.first_name}}", "mode": "dm"},
        lead=LEAD,
        contact=CONTACT,
        bundle=BUNDLE,
    )
    assert out["body"] == "Hi Priya"
    assert out["provider_id"] == "ACoAA123"
    assert out["chat_id"] == "chat-li-1"
    # LinkedIn identity resolves via provider_id/linkedin_url in the handler;
    # the renderer must not fabricate an attendee.
    assert "attendee_identifier" not in out


def test_linkedin_inmail_renders_subject():
    out = render_channel_payload(
        ChannelType.LINKEDIN_INMAIL,
        {"message_template": "Body", "subject_template": "For {{contact.company}}"},
        lead=LEAD,
        contact=CONTACT,
        bundle=BUNDLE,
    )
    assert out["subject"] == "For Acme" and out["body"] == "Body"


def test_email_payload_carries_transport_config_not_secret():
    bundle = {
        "smtp_host": "smtp.acme.io",
        "smtp_port": 465,
        "smtp_username": "outbound@acme.io",
        "smtp_use_tls": False,
        "smtp_password": "NEVER-IN-PAYLOAD",
    }
    out = render_channel_payload(
        ChannelType.EMAIL,
        {"subject_template": "Hello {{contact.first_name}}", "body_template": "<p>{{contact.company}}</p>"},
        lead=LEAD,
        contact=CONTACT,
        bundle=bundle,
    )
    assert out["subject"] == "Hello Priya" and out["body"] == "<p>Acme</p>"
    assert out["smtp_host"] == "smtp.acme.io" and out["smtp_port"] == 465
    assert out["smtp_use_tls"] is False
    assert out["from"] == "outbound@acme.io"  # falls back to smtp_username
    assert "smtp_password" not in out  # secret stays behind the credential ref


def test_existing_payload_values_win_and_sources_pass_through():
    out = render_channel_payload(
        ChannelType.WHATSAPP,
        {"body": "already rendered", "unipile_account_id": "acct-override", "chat_id": "chat-x"},
        lead=LEAD,
        contact=CONTACT,
        bundle=BUNDLE,
    )
    assert out["body"] == "already rendered"
    assert out["unipile_account_id"] == "acct-override"
    assert out["chat_id"] == "chat-x"

    src_payload = {"keywords": "python", "body_template": "not a channel"}
    assert (
        render_channel_payload(ChannelType.NAUKRI, src_payload, lead=LEAD, contact=CONTACT, bundle=None)
        is src_payload
    )


def test_missing_bundle_and_contact_degrade_without_crashing():
    out = render_channel_payload(
        ChannelType.WHATSAPP, {"body_template": "Hi {{contact.first_name}}"}, lead={"id": "l"}, contact=None, bundle=None
    )
    assert out["body"] == "Hi "
    assert out["unipile_account_id"] == ""
    assert "attendee_identifier" not in out  # no phone -> handler fails loud, not wrong


# ── wire-in: build_command must route through the renderer ──────────────────

def test_build_command_routes_payload_through_renderer():
    src = (BACKEND / "app" / "execution" / "commands.py").read_text(encoding="utf-8")
    body = src.split("async def build_command", 1)[1]
    assert re.search(r"render_channel_payload\(\s*channel,\s*payload", body), (
        "build_command no longer renders the channel payload — the Rust "
        "handlers will receive starved payloads again (CONTRACT-2)"
    )
    assert "_load_connection_bundle" in body, "bundle must feed the renderer, not just the credential ref"
