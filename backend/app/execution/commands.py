"""Build an ActionCommand for a canvas node and publish it to the muscle.

The dispatcher and transition worker both call ``dispatch_node`` to fire the
node a lead currently sits on. This module owns:

  - node type  -> ChannelType            (which muscle handler runs)
  - node config + lead -> command payload (rendered, self-contained)
  - connection name -> one-shot credential_ref (secret never in the payload)

A node whose ``side_effect`` is not NETWORK/MUTATE (conditions, delays) has no
muscle command — the orchestrator advances it via its returned handle without a
muscle round-trip. Those are handled by the dispatcher directly, not here.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.core.events import ChannelType
from app.db import fetch_all, fetch_one, system_scope
from app.execution.render import render_channel_payload
from app.services import bus, send_policy
from app.services.email_tracking import make_token
from app.services.encryption import decrypt

log = logging.getLogger(__name__)

# Node type -> muscle channel. Only side-effecting nodes appear here; anything
# absent is resolved locally by the dispatcher (conditions/flow) instead of
# being sent to the muscle.
NODE_CHANNEL: dict[str, ChannelType] = {
    "channel.email": ChannelType.EMAIL,
    "channel.sms": ChannelType.SMS,
    "channel.voice": ChannelType.VOICE,
    # One action = one node = one static channel — the four LinkedIn actions are
    # first-class nodes (the old channel.linkedin mode toggle needed a dispatcher
    # special-case that once mis-dispatched invites as DMs; see bug C1).
    "channel.linkedin_invite": ChannelType.LINKEDIN_INVITE,
    "channel.linkedin_dm": ChannelType.LINKEDIN_DM,
    "channel.linkedin_inmail": ChannelType.LINKEDIN_INMAIL,
    "channel.linkedin_profile_view": ChannelType.LINKEDIN_PROFILE_VIEW,
    "channel.whatsapp": ChannelType.WHATSAPP,
    "channel.instagram": ChannelType.INSTAGRAM,
    "channel.telegram": ChannelType.TELEGRAM,
    "channel.slack": ChannelType.WEBHOOK,
    "channel.webhook_out": ChannelType.WEBHOOK,
    # channel.n8n is a PRESET over webhook_out: it emits channel.webhook_out.queued
    # and rides the same SSRF-guarded Rust handle_webhook (zero Rust change).
    "channel.n8n": ChannelType.WEBHOOK,
    "crm.add_tag": ChannelType.ADD_TAG,
    "crm.remove_tag": ChannelType.REMOVE_TAG,
    "crm.hot_lead_alert": ChannelType.HOT_LEAD_ALERT,
    # Person-enrichment providers — first-class nodes (the old ai.enrich
    # enrich_source toggle is gone; migration 053 rewrote stored rows). All ride
    # the same ENRICH muscle channel; handle_enrich switches on enrich_source.
    "enrich.apollo_person": ChannelType.ENRICH,
    "enrich.hunter_email": ChannelType.ENRICH,
    "enrich.proxycurl_profile": ChannelType.ENRICH,
    "linkfinder.company_website": ChannelType.ENRICH,
    "linkfinder.company_phone": ChannelType.ENRICH,
    "linkfinder.company_email": ChannelType.ENRICH,
    "linkfinder.company_employee_count": ChannelType.ENRICH,
    "linkfinder.company_linkedin": ChannelType.ENRICH,
    "linkfinder.profile_info": ChannelType.ENRICH,
    "linkfinder.profile_email": ChannelType.ENRICH,
    "linkfinder.profile_phone": ChannelType.ENRICH,
    "linkfinder.company_page_info": ChannelType.ENRICH,
    "linkfinder.company_page_employees": ChannelType.ENRICH,
    "linkfinder.name_to_linkedin": ChannelType.ENRICH,
    "linkfinder.email_to_linkedin": ChannelType.ENRICH,
    "linkfinder.instagram_info": ChannelType.ENRICH,
    # Renidly rides the same ENRICH channel; handle_enrich switches on the
    # payload's enrich_source. Without this route the node publishes its intent
    # into a void and the lead stalls (cf. ENRICH-INTENT-001).
    "renidly.person_profile": ChannelType.ENRICH,
    "renidly.company_profile": ChannelType.ENRICH,
    "ai.compose": ChannelType.AI_COMPOSE,
    # Claude classifier handler — both screen variants share it. The asymmetric
    # error policy lives in the node's payload (on_error_handle), not here.
    "ai.screen_company": ChannelType.AI_SCREEN,
    "ai.screen_person": ChannelType.AI_SCREEN,
    # Apify-driven LinkedIn jobs source (multi-step actor protocol).
    "source.linkedin_jobs": ChannelType.APIFY,
    # Camoufox-driven Naukri.com jobs source (anti-detect headless scrape).
    "source.naukri": ChannelType.NAUKRI,
    # Apify-driven Indeed.com jobs source (curious_coder/indeed-scraper actor).
    "source.indeed": ChannelType.INDEED,
    # Per-company people search (multi-pattern x titles, dedupe) — two distinct
    # nodes (paid Serper / free SearXNG), shared Rust handler.
    "source.serper_people": ChannelType.SERPER_PEOPLE,
    "source.linkfinder_leads": ChannelType.LEADS_FINDER,
    "source.linkfinder_employees": ChannelType.LEADS_FINDER,
    "source.linkfinder_post_reactions": ChannelType.LEADS_FINDER,
    "source.searxng_people": ChannelType.SEARXNG_PEOPLE,
    # Company discovery — Auto-Pilot Target Mining. Four distinct sources, each
    # its own product/setup, NOT a provider toggle (handlers/discovery.rs).
    "source.searxng": ChannelType.SEARXNG,
    "source.serper_search": ChannelType.SERPER_SEARCH,
    "source.apollo": ChannelType.APOLLO,
    "source.clutch": ChannelType.CLUTCH,
    # APOLLO-DATA: native Apollo data layer. Each its own ChannelType (wire
    # contract verified in test_apollo_data + test_congruity).
    "source.apollo_people": ChannelType.APOLLO_PEOPLE,
    "source.renidly_job_changes": ChannelType.RENIDLY_JOB_CHANGES,
    "enrich.apollo_company": ChannelType.APOLLO_COMPANY_ENRICH,
    "source.apollo_jobs": ChannelType.APOLLO_JOBS,
    # UNIPILE-FULL: native LinkedIn search (fan-out lead-gen) + enrichment reads
    # + per-lead social actions. Each its own ChannelType (wire contract verified
    # in test_unipile_full + test_congruity).
    "source.linkedin_search": ChannelType.LINKEDIN_SEARCH,
    "enrich.linkedin_company": ChannelType.LINKEDIN_COMPANY_PROFILE,
    "enrich.linkedin_member": ChannelType.LINKEDIN_MEMBER_PROFILE,
    "channel.linkedin_react_post": ChannelType.LINKEDIN_REACT_POST,
    "channel.linkedin_comment_post": ChannelType.LINKEDIN_COMMENT_POST,
    "channel.linkedin_endorse": ChannelType.LINKEDIN_ENDORSE,
    "channel.linkedin_follow": ChannelType.LINKEDIN_FOLLOW,
    "channel.message_react": ChannelType.MESSAGE_REACT,
    "channel.invite_cancel": ChannelType.INVITE_CANCEL,
    # ATS job-board sources — 12 distinct nodes, one shared muscle channel
    # (ChannelType.ATS); the muscle keys on payload.platform. All keyless.
    "source.greenhouse": ChannelType.ATS,
    "source.ashby": ChannelType.ATS,
    "source.smartrecruiters": ChannelType.ATS,
    "source.bamboohr": ChannelType.ATS,
    "source.workday": ChannelType.ATS,
    "source.icims": ChannelType.ATS,
    "source.lever": ChannelType.ATS,
    "source.workable": ChannelType.ATS,
    "source.recruitee": ChannelType.ATS,
    "source.personio": ChannelType.ATS,
    "source.rippling": ChannelType.ATS,
    "source.breezy": ChannelType.ATS,
    # Every declarative HTTP node (sources built via http_node) routes to the
    # generic handler. The dispatcher detects these by the emitted intent
    # carrying channel="http_call".
    "__http_call__": ChannelType.HTTP_CALL,
}

# Provider tag (from the node manifest capability "connection:<provider>")
# used to look up the workspace connection that holds the secret.
_CHANNEL_PROVIDER: dict[ChannelType, str] = {
    ChannelType.EMAIL: "smtp",
    ChannelType.SMS: "twilio",
    ChannelType.VOICE: "retell",
    ChannelType.LINKEDIN_DM: "unipile",
    ChannelType.WHATSAPP: "unipile",
    ChannelType.INSTAGRAM: "unipile",
    ChannelType.TELEGRAM: "unipile",
}

# A sending account's coarse channel family (omni_sending_accounts.channel_kind).
# The muscle's ChannelType is finer-grained (LinkedIn has invite/dm/inmail/view
# variants), but a LinkedIn *seat* is one account regardless of action — so all
# LINKEDIN_* collapse to "linkedin". Only the outbound channels that can have a
# per-seat sending account appear here; absent channels never resolve an account
# and fall straight through to the legacy connection_name path.
_CHANNEL_KIND: dict[ChannelType, str] = {
    ChannelType.EMAIL: "email",
    ChannelType.SMS: "sms",
    ChannelType.VOICE: "voice",
    ChannelType.WHATSAPP: "whatsapp",
    ChannelType.INSTAGRAM: "instagram",
    ChannelType.TELEGRAM: "telegram",
    ChannelType.LINKEDIN_DM: "linkedin",
    ChannelType.LINKEDIN_INVITE: "linkedin",
    ChannelType.LINKEDIN_INMAIL: "linkedin",
    ChannelType.LINKEDIN_PROFILE_VIEW: "linkedin",
}

# ENRICH-HANDLE-001: the ChannelTypes whose NODES declare a `sent` output handle
# — real message/side-effect sends. build_command stamps metadata.next_handle
# ="sent" only for these; every other muscle node (enrich, tags, transforms,
# discovery sources, social reads) advances on "default", matching the handles
# those nodes actually declare. Getting this wrong terminalizes the lead at a
# non-existent `sent` edge (the Apollo enrich→create_contact break).
_SEND_HANDLE_CHANNELS: frozenset[ChannelType] = frozenset(
    set(_CHANNEL_KIND)
    | {
        ChannelType.WEBHOOK,  # channel.webhook_out / slack — nodes have a `sent` handle
        ChannelType.LINKEDIN_REACT_POST,
        ChannelType.LINKEDIN_COMMENT_POST,
        ChannelType.LINKEDIN_ENDORSE,
        ChannelType.LINKEDIN_FOLLOW,
        ChannelType.MESSAGE_REACT,
        ChannelType.INVITE_CANCEL,
    }
)


async def _load_pooled_accounts(workspace_id: str, workflow_id: str, channel_kind: str) -> list[dict[str, Any]]:
    """The campaign's pooled sending accounts for this channel family, with the
    counter columns send_policy.pick_lru needs. The DB only filters by membership
    + kind; eligibility (status/caps) + LRU ordering happen in pick_lru so the
    exact selection rule is the one locked by test_send_policy.py."""
    async with system_scope():
        rows = await fetch_all(
            """
            SELECT a.id, a.connection_id, a.channel_kind, a.external_identity,
                   a.status, a.daily_cap, a.hourly_cap, a.sends_today,
                   a.sends_this_hour, a.day_anchor, a.hour_anchor,
                   a.warmup_target, a.last_used_at
            FROM omni_sending_accounts a
            JOIN omni_campaign_sending_accounts p ON p.sending_account_id = a.id
            WHERE a.workspace_id = $1 AND p.workflow_id = $2 AND a.channel_kind = $3
            """,
            workspace_id, workflow_id, channel_kind,
        )
    return [dict(r) for r in rows]


async def _load_account_by_id(workspace_id: str, account_id: str) -> dict[str, Any] | None:
    """Load a single pinned sending account (node-level override)."""
    async with system_scope():
        row = await fetch_one(
            "SELECT id, connection_id, channel_kind, external_identity, status "
            "FROM omni_sending_accounts WHERE workspace_id=$1 AND id=$2",
            workspace_id, account_id,
        )
    return dict(row) if row else None


async def _load_accounts_by_connection_name(
    workspace_id: str, connection_name: str, channel_kind: str
) -> list[dict[str, Any]]:
    """SEND-ATTRIB-001: the sending accounts under the connection named on the
    node, for this channel family. The legacy connection_name path used to bypass
    per-seat caps entirely (no account resolved → no sending_account_id stamped →
    the increment never ran → the account daily/hourly cap was never enforced).
    Now a connection_name send still resolves a seat under that connection, so the
    cap is counted via the same pick_lru + increment path the pool path uses."""
    async with system_scope():
        rows = await fetch_all(
            """
            SELECT a.id, a.connection_id, a.channel_kind, a.external_identity,
                   a.status, a.daily_cap, a.hourly_cap, a.sends_today,
                   a.sends_this_hour, a.day_anchor, a.hour_anchor,
                   a.warmup_target, a.last_used_at
            FROM omni_sending_accounts a
            JOIN omni_connections c ON c.id = a.connection_id
            WHERE a.workspace_id = $1 AND c.name = $2 AND a.channel_kind = $3
            """,
            workspace_id, connection_name, channel_kind,
        )
    return [dict(r) for r in rows]


async def _connection_bundle_by_id(workspace_id: str, connection_id: str) -> dict[str, Any] | None:
    """Decrypt a connection's bundle by id (the account's parent connection holds
    the secret; the account only carries the sender identity)."""
    async with system_scope():
        row = await fetch_one(
            "SELECT credentials_encrypted FROM omni_connections WHERE workspace_id=$1 AND id=$2",
            workspace_id, connection_id,
        )
    if not row:
        return None
    return json.loads(decrypt(row["credentials_encrypted"]))


def _apply_account_to_bundle(bundle: dict[str, Any], account: dict[str, Any], channel: ChannelType) -> dict[str, Any]:
    """Override the bundle's sender identity with the chosen account's, leaving
    the secret untouched. render_channel_payload reads these exact keys
    (render.py): unipile account_id for social, "from" for email. Returns a NEW
    bundle (no mutation of the shared connection bundle)."""
    out = dict(bundle)
    ext = account.get("external_identity")
    kind = account.get("channel_kind")
    if kind == "email":
        out["from"] = ext
    elif kind in ("linkedin", "whatsapp", "instagram", "telegram"):
        out["account_id"] = ext
    elif kind in ("sms", "voice"):
        out["from"] = ext  # E.164 sender number
    return out


async def _resolve_sending_account(
    *,
    workspace_id: str,
    workflow_id: str | None,
    channel: ChannelType,
    node_account_id: str | None,
    account_pool: str | None,
    connection_name: str | None = None,
) -> dict[str, Any] | None:
    """Pick the sending account for this send, or None to fall back to the bare
    connection bundle. Precedence: node pin → campaign pool (LRU) → an LRU seat
    under the named connection (SEND-ATTRIB-001) → None.

    Resolving a seat even for the legacy connection_name path is what makes the
    per-seat rate cap actually apply: build_command stamps metadata.sending_account_id
    from whatever this returns, and the transition worker only counts/enforces the
    cap when that id is present. Returning None here (the old behaviour for
    connection_name) silently disabled the account cap."""
    channel_kind = _CHANNEL_KIND.get(channel)
    if channel_kind is None:
        return None  # channel can't have per-seat accounts

    def _pick(accts: list[dict[str, Any]]) -> dict[str, Any] | None:
        eligible = [a for a in accts if a.get("status") in ("active", "warming")]
        if not eligible:
            return None
        today = datetime.now(UTC).date()
        hour_bucket = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        return send_policy.pick_lru(eligible, today, hour_bucket)

    # 1. Node-level pin always wins (operator chose this exact seat on the node).
    if node_account_id:
        acct = await _load_account_by_id(workspace_id, node_account_id)
        # Honour the pin only if it's a live seat of the right family; otherwise
        # fall through rather than silently sending from an unintended account.
        if acct and acct.get("channel_kind") == channel_kind and acct.get("status") in ("active", "warming"):
            return acct
        return None

    # 2. Campaign pool: LRU among eligible. account_pool gates whether the pool is
    #    consulted at all — only "campaign"/"round_robin" rotate; explicit "single"
    #    or None means "no pool", defer to connection_name (below).
    if workflow_id and account_pool in ("campaign", "round_robin"):
        picked = _pick(await _load_pooled_accounts(workspace_id, workflow_id, channel_kind))
        if picked:
            return picked

    # 3. SEND-ATTRIB-001: legacy connection_name path — resolve an eligible seat
    #    under the named connection so the per-seat cap is counted + enforced.
    #    (A connection with no synced accounts still falls through to None and
    #    uses the bare bundle — unchanged behaviour, but then there's no seat to
    #    cap anyway.)
    if connection_name:
        picked = _pick(await _load_accounts_by_connection_name(workspace_id, connection_name, channel_kind))
        if picked:
            return picked
    return None


async def _load_connection_bundle(workspace_id: str, connection_name: str | None) -> dict[str, Any] | None:
    """Decrypt a workspace connection's credential bundle by name.
    Returns None when the node declares no connection (e.g. inline webhook)."""
    if not connection_name:
        return None
    async with system_scope():
        row = await fetch_one(
            "SELECT id, provider, credentials_encrypted FROM omni_connections WHERE workspace_id=$1 AND name=$2",
            workspace_id,
            connection_name,
        )
    if not row:
        log.warning("[dispatch] no connection %r for workspace %s", connection_name, workspace_id)
        return None
    bundle = json.loads(decrypt(row["credentials_encrypted"]))
    # MAILGUN-001: carry the connection identity (non-secret) so downstream can
    # tag a send with WHICH connection sent it — the Mailgun webhook resolves the
    # signing key from this exact connection, not "the most recent mailgun one"
    # (which breaks verification in a workspace with 2+ Mailgun connections).
    bundle.setdefault("_connection_id", str(row["id"]))
    bundle.setdefault("provider", row["provider"])
    return bundle


async def _mint_credential_ref(bundle: dict[str, Any] | None, channel: str) -> str | None:
    """Persist the bundle as a one-shot credential ref the muscle redeems."""
    if bundle is None:
        return None
    # mint_credential_ref persists the encrypted bundle and returns the ref.
    from app.routers.internal import mint_credential_ref

    return await mint_credential_ref(channel, bundle)


def _lead_context(lead: dict[str, Any], contact: dict[str, Any] | None) -> dict[str, Any]:
    """The wire-shape the Rust muscle deserializes as LeadContext (models.rs).

    CONTRACT-1: every Option field the Rust struct declares should be honestly
    populated when the data exists — previously headline/source and the social
    chat-session fields were simply never sent, so the muscle always saw None.
    Chat-session ids (chat_id/ig_chat_id/tg_chat_id) live in the LEAD's
    custom_fields (written back by _apply_lead_mutations when send_chat opens a
    chat); usernames/location come from the contact's custom_fields."""
    c = contact or {}
    lead_cf = lead.get("custom_fields") or {}
    if isinstance(lead_cf, str):
        lead_cf = json.loads(lead_cf)
    contact_cf = c.get("custom_fields") or {}
    if isinstance(contact_cf, str):
        contact_cf = json.loads(contact_cf)
    return {
        "id": str(lead["id"]),
        "campaign_id": str(lead.get("workflow_id") or lead["id"]),
        # A provider stack may run before crm.create_contact. In that case the
        # transition worker stores learned identity fields on the lead until a
        # contact exists. Contact columns always win once present.
        "email": c.get("email") or lead_cf.get("email"),
        "linkedin_url": c.get("linkedin_url") or lead_cf.get("linkedin_url"),
        "phone": c.get("phone") or lead_cf.get("phone"),
        "first_name": c.get("first_name") or lead_cf.get("first_name"),
        "last_name": c.get("last_name") or lead_cf.get("last_name"),
        "company": c.get("company") or lead_cf.get("company"),
        "headline": c.get("headline") or lead_cf.get("headline"),
        "location": contact_cf.get("location"),
        "source": c.get("source"),
        "chat_id": lead_cf.get("chat_id"),
        "ig_chat_id": lead_cf.get("ig_chat_id"),
        "tg_chat_id": lead_cf.get("tg_chat_id"),
        "instagram_username": contact_cf.get("instagram_username"),
        "telegram_username": contact_cf.get("telegram_username"),
        "extra_data": lead_cf,
    }


async def build_command(
    *,
    workspace_id: str,
    channel: ChannelType,
    lead: dict[str, Any],
    contact: dict[str, Any] | None,
    node_id: str,
    payload: dict[str, Any],
    connection_name: str | None,
    correlation_id: str | None = None,
    sending_account_id: str | None = None,
    account_pool: str | None = None,
) -> dict[str, Any]:
    """Assemble the ActionCommand envelope the muscle consumes.

    Sender resolution precedence (additive, backward-compatible):
      node pin → campaign pool (LRU) → legacy connection_name → provider default.
    A resolved sending account loads ITS connection's bundle (secret stays at the
    connection) and overrides only the sender identity; metadata.sending_account_id
    is stamped so the transition worker increments that account's rate counter on
    the confirmed send. When no account resolves, the legacy connection_name path
    runs unchanged — saved graphs that only set connection_name see zero change."""
    account = await _resolve_sending_account(
        workspace_id=workspace_id,
        workflow_id=str(lead.get("workflow_id")) if lead.get("workflow_id") else None,
        channel=channel,
        node_account_id=sending_account_id,
        account_pool=account_pool,
        connection_name=connection_name,
    )
    sending_account_id_used: str | None = None
    if account is not None:
        bundle = await _connection_bundle_by_id(workspace_id, str(account["connection_id"]))
        if bundle is not None:
            bundle = _apply_account_to_bundle(bundle, account, channel)
            sending_account_id_used = str(account["id"])
        else:
            # Account points at a deleted connection — don't send from a phantom
            # sender; fall back to the named connection.
            bundle = await _load_connection_bundle(workspace_id, connection_name)
    else:
        bundle = await _load_connection_bundle(workspace_id, connection_name)
    credential_ref = await _mint_credential_ref(bundle, channel.value)
    # T3: for email, mint a signed open/click tracking token so render injects
    # the pixel + link rewrites. Keyed to this workspace/lead/contact so the
    # public endpoints can attribute a hit without trusting the caller.
    tracking_base: str | None = None
    tracking_token: str | None = None
    if channel == ChannelType.EMAIL:
        tracking_base = settings.get_public_base_url()
        tracking_token = make_token(
            settings.secret_key,
            workspace_id=workspace_id,
            lead_id=str(lead["id"]) if lead.get("id") else None,
            contact_id=str(contact.get("id")) if contact and contact.get("id") else None,
        )
    # CONTRACT-2: fulfil the Rust handlers' self-contained-payload contract —
    # render *_template fields, copy non-secret transport/sender config from
    # the connection bundle, resolve the per-channel attendee identity, and
    # reuse persisted chat sessions. Without this every channel send starved.
    payload = render_channel_payload(
        channel, payload, lead=lead, contact=contact, bundle=bundle,
        tracking_base=tracking_base, tracking_token=tracking_token,
    )
    return {
        "command_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "channel": channel.value,
        "lead": _lead_context(lead, contact),
        "payload": payload,
        "credential_ref": credential_ref,
        "metadata": {
            "workspace_id": workspace_id,
            "node_id": node_id,
            "correlation_id": correlation_id or str(uuid.uuid4()),
            # Stamped only when a per-seat account was resolved; the transition
            # worker reads it to increment that account's rate counter on the
            # CONFIRMED send (exactly-once via processed_commands). Absent = the
            # legacy connection_name path; no per-account counter to bump.
            "sending_account_id": sending_account_id_used,
            # SEND-HANDLE-001: a successful SEND continues on the channel node's
            # declared `sent` handle. The orchestrator routes a status=sent result
            # on metadata.next_handle (default "default"); without this stamp every
            # channel send routed on "default", so a sequence wired on `sent` (what
            # the composer + the canvas emit) dead-ended after the first message.
            # The muscle echoes metadata unchanged, so this round-trips. A handler
            # that needs a DIFFERENT outcome (RELGATE not_connected / NOCHAT
            # no_thread / SMART-INVITE already_connected) overrides next_handle on
            # its own result, which wins.
            #
            # ENRICH-HANDLE-001: but this stamp is ONLY correct for real send
            # channels whose nodes declare a `sent` handle. Non-send muscle nodes
            # (ai.enrich, tags, transforms, discovery sources) also return
            # status=sent, but their nodes declare `default`/`on_error` handles —
            # NOT `sent`. Stamping "sent" on them made the orchestrator route on a
            # `sent` edge that doesn't exist, so the lead hit a leaf and
            # terminalized BEFORE the next node (e.g. an Apollo-enriched lead never
            # reached create_contact). Only the send channels get "sent"; every
            # other node advances on "default".
            "next_handle": "sent" if channel in _SEND_HANDLE_CHANNELS else "default",
        },
        "occurred_at": datetime.now(UTC).isoformat(),
    }


async def publish_command(command: dict[str, Any]) -> None:
    """Send the assembled command to the muscle, keyed by lead id for ordering."""
    await bus.publish_command(command, key=command["lead"]["id"])
