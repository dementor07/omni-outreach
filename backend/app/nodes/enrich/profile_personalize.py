"""Profile-based personalization enrichment (ported from outreach_automation's
`lead_enrichment_service.py`).

Gathers per-lead context so `ai.compose` writes a message that references the
person specifically rather than a template:

  - Unipile profile  → headline, about/summary, location   (GET /users/{public_id})
  - Unipile posts    → their latest post, ONLY if recent    (GET /users/{id}/posts)
  - Company website  → homepage text, HTML-stripped + capped (free httpx fetch)

Design carried over verbatim from the source pipeline:
  * RECENCY GATE — a stale post (older than `post_max_age_days`) is worse than
    none (reads as automated), so an old post yields nothing.
  * ANTI-HALLUCINATION — the post is wrapped with an explicit "N days old; don't
    treat time-bound wording as current" preamble before it reaches the model.
  * GRACEFUL DEGRADATION — every source degrades to "" and NEVER blocks the
    sequence; a total failure still routes onward (best-effort enrichment).

The fields land on the LEAD's custom_fields, written SYNCHRONOUSLY here (not via
the async projector) so the very next node — `ai.compose`, which forwards
`extra_data`/custom_fields to the model — sees them without a race. A
`lead.custom_fields_updated` event is also emitted for audit/webhooks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel, Field

from app.db import execute as db_execute
from app.db import fetch_all, system_scope
from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)
from app.services.unipile_client import UnipileClient, UnipileError

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_POST_DT_KEYS = ("parsed_datetime", "published_at", "posted_at", "created_at", "date")


class ProfilePersonalizeConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection (Settings → Integrations)")
    unipile_account_id: str | None = Field(
        None,
        description=(
            "Pin reads to one Unipile seat. Leave empty to ROTATE across the CAMPAIGN'S "
            "pooled seats (the same accounts that send this campaign's invites/DMs), "
            "deterministically per lead — so profile-view load spreads across the seats "
            "actually working the campaign instead of hammering one account."
        ),
    )
    post_max_age_days: int = Field(30, ge=1, le=365, description="Only reference a post newer than this")
    posts_to_keep: int = Field(
        15, ge=0, le=30,
        description=(
            "How many recent posts to keep as a signal digest (recent_posts_context) so ai.compose "
            "can find the BUYING SIGNAL (a hiring/growth/pipeline post) even when it isn't the newest. "
            "0 = keep only the single latest post."
        ),
    )
    website_chars: int = Field(2000, ge=200, le=8000, description="Max homepage characters to summarise")
    fetch_website: bool = Field(True, description="Also fetch + summarise the company website")


MANIFEST = NodeManifest(
    type="enrich.profile_personalize",
    category=NodeCategory.ENRICH,
    display_name="Profile personalization (Unipile)",
    summary="Enrich the lead with profile + recent post + website for personalized AI messages",
    config_schema=ProfilePersonalizeConfig,
    output_handles=(
        NodeHandle("default", "Enrichment attempted (best-effort); fields merged onto the lead"),
        NodeHandle("on_error", "Unrecoverable error (misconfiguration)"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="user-search",
    primary_fields=("connection_name", "unipile_account_id"),
    advanced_fields=("post_max_age_days", "website_chars", "fetch_website"),
)


def _public_id(linkedin_url: str) -> str:
    """The /in/<slug> public identifier from a LinkedIn profile URL."""
    if not linkedin_url:
        return ""
    m = re.search(r"/in/([^/?#]+)", linkedin_url)
    return (m.group(1) if m else "").strip()


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _post_dt(post: dict) -> datetime | None:
    for k in _POST_DT_KEYS:
        raw = post.get(k)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    return None


def _recent_post(items: list[dict], max_age_days: int) -> tuple[str, datetime | None]:
    """Newest post with usable text within the recency window; else ('', None)."""
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    best, best_dt = "", None
    for p in items or []:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        dt = _post_dt(p)
        if dt is None or dt < cutoff:
            continue
        if best_dt is None or dt > best_dt:
            best, best_dt = re.sub(r"\s+", " ", text)[:500], dt
    return best, best_dt


def _recent_posts_block(items: list[dict], max_age_days: int, keep: int) -> str:
    """Newest-first digest of up to `keep` recent posts within the window, each with
    its age, so ai.compose can find the BUYING SIGNAL (a hiring / growth / pipeline
    post) even when it is not the newest post. The single-latest-post field misses
    exactly this: the relevant signal is often an older post."""
    if keep <= 0:
        return ""
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    scored: list[tuple[datetime, str]] = []
    for p in items or []:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        dt = _post_dt(p)
        if dt is None or dt < cutoff:
            continue
        scored.append((dt, re.sub(r"\s+", " ", text)[:400]))
    scored.sort(key=lambda x: x[0], reverse=True)
    scored = scored[:keep]
    if not scored:
        return ""
    today = datetime.now(UTC).date()
    lines = [
        f"- ({dt.date().isoformat()}, {max(0, (today - dt.date()).days)}d ago) {text}"
        for dt, text in scored
    ]
    return (
        "Recent posts, newest first. Treat none of the time-bound wording as current. "
        "Pick the ONE that is the strongest buying signal for us (hiring for a marketing / social "
        "/ growth / SDR / sales / outreach role, or scaling, pipeline, lead-gen, distribution, "
        "outbound) and build the opening on THAT, relating what we do to it:\n" + "\n".join(lines)
    )


def _post_context(post: str, posted_at: datetime | None) -> str:
    """Anti-hallucination framing (verbatim intent from the source pipeline)."""
    if not post or posted_at is None:
        return ""
    date_str = posted_at.date().isoformat()
    age = max(0, (datetime.now(UTC).date() - posted_at.date()).days)
    return (
        f"Posted on {date_str}; {age} days old as of today. "
        f"Do not treat time-bound wording in the post as current or upcoming unless the post "
        f"explicitly contains a future date. Post text: {post}"
    )


async def _website_summary(url: str, cap: int) -> str:
    if not url:
        return ""
    if not url.startswith("http"):
        url = "http://" + url
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": _UA})
        if r.status_code != 200:
            return ""
        return _html_to_text(r.text)[:cap]
    except Exception as e:  # noqa: BLE001 — best-effort, never blocks
        log.info("[profile_personalize] website fetch failed for %s: %s", url, e)
        return ""


async def _resolve_website(client: UnipileClient, account_id: str, company: str) -> str:
    """Best-effort company website via Unipile company search → company detail."""
    if not company:
        return ""
    try:
        res = await client.linkedin_search(account_id, {"api": "classic", "category": "companies", "keywords": company})
        hits = res.get("items") or res.get("results") or (res if isinstance(res, list) else [])
        company_id = ""
        for h in hits if isinstance(hits, list) else []:
            company_id = str((h or {}).get("id") or (h or {}).get("company_id") or "").strip()
            if company_id:
                break
        if not company_id:
            return ""
        detail = await client.company_profile(account_id, company_id)
        return (detail.get("website") or detail.get("website_url") or detail.get("url") or "").strip()
    except Exception as e:  # noqa: BLE001
        log.info("[profile_personalize] company website resolve failed for %s: %s", company, e)
        return ""


async def _pick_seat(workspace_id: str, workflow_id: str | None, connection_name: str, lead_id: str) -> str:
    """The Unipile seat to read this lead through — rotated across the CAMPAIGN'S
    pooled seats (the same accounts that send its invites/DMs), else all seats
    under the connection. Deterministic per lead (hash of lead_id) so the same
    lead is always read by the same seat, and the cohort spreads across seats
    rather than concentrating profile views on one account."""
    async with system_scope():
        rows = []
        if workflow_id:
            rows = await fetch_all(
                "SELECT a.external_identity FROM omni_sending_accounts a "
                "JOIN omni_campaign_sending_accounts p ON p.sending_account_id = a.id "
                "WHERE a.workspace_id=$1 AND p.workflow_id=$2 AND a.channel_kind='linkedin' "
                "AND a.status IN ('active','warming')",
                workspace_id, workflow_id,
            )
        if not rows:  # no explicit pool → all seats under the connection (the campaign default)
            rows = await fetch_all(
                "SELECT a.external_identity FROM omni_sending_accounts a "
                "JOIN omni_connections c ON c.id = a.connection_id "
                "WHERE a.workspace_id=$1 AND c.name=$2 AND a.channel_kind='linkedin' "
                "AND a.status IN ('active','warming')",
                workspace_id, connection_name,
            )
    seats = sorted({(r["external_identity"] or "").strip() for r in rows} - {""})
    if not seats:
        return ""
    idx = int(hashlib.sha256(lead_id.encode("utf-8")).hexdigest(), 16) % len(seats)
    return seats[idx]


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ProfilePersonalizeConfig(**ctx.config)
    lead = ctx.lead or {}
    cf = lead.get("custom_fields") or {}
    if isinstance(cf, str):
        try:
            cf = json.loads(cf)
        except Exception:  # noqa: BLE001
            cf = {}
    linkedin_url = lead.get("linkedin_url") or cf.get("linkedin_url") or ""
    company = lead.get("company") or cf.get("company") or ""
    correlation_id = ctx.correlation_id or str(uuid.uuid4())

    enriched: dict[str, str] = {}
    # Seat to read through: a pinned one, else rotate across the campaign's pooled seats.
    seat = cfg.unipile_account_id or await _pick_seat(
        ctx.workspace_id, ctx.workflow_id, cfg.connection_name, str(lead.get("id") or "")
    )
    if not seat:
        log.warning("[profile_personalize] no active Unipile seat to read through")
        return NodeResult(handle="on_error", error="NO_UNIPILE_SEAT")
    try:
        client = await UnipileClient.for_workspace(ctx.workspace_id, connection_name=cfg.connection_name)
    except UnipileError as e:
        log.warning("[profile_personalize] no usable Unipile connection: %s", e)
        return NodeResult(handle="on_error", error="UNIPILE_NOT_CONFIGURED")

    # 1) Profile (headline / about / location) + provider_id for the posts call.
    provider_id = ""
    public_id = _public_id(linkedin_url)
    if public_id:
        try:
            prof = await client.member_profile(seat, public_id)
            headline = (prof.get("headline") or prof.get("occupation") or "").strip()
            about = (prof.get("summary") or prof.get("about") or "").strip()
            loc = prof.get("location")
            location = loc.strip() if isinstance(loc, str) else ""
            provider_id = str(prof.get("provider_id") or prof.get("id") or "").strip()
            if headline:
                enriched["profile_headline"] = headline
            if about:
                enriched["profile_about"] = about[:1500]
            if location:
                enriched["profile_location"] = location
        except UnipileError as e:
            log.info("[profile_personalize] profile fetch failed for %s: %s", public_id, e)

    # 2) Recent post (recency-gated) → anti-hallucination context.
    if provider_id:
        try:
            posts = await client.member_posts(seat, provider_id, limit=25)
            items = posts.get("items") if isinstance(posts, dict) else posts
            post, posted_at = _recent_post(items or [], cfg.post_max_age_days)
            if post:
                enriched["latest_post"] = post
                enriched["latest_post_at"] = posted_at.date().isoformat()
                enriched["latest_post_context"] = _post_context(post, posted_at)
            # The whole point: keep the recent history so compose can find the
            # buying signal even when it is not the newest post.
            block = _recent_posts_block(items or [], cfg.post_max_age_days, cfg.posts_to_keep)
            if block:
                enriched["recent_posts_context"] = block
        except UnipileError as e:
            log.info("[profile_personalize] posts fetch failed for %s: %s", provider_id, e)

    # 3) Website summary (free) — explicit URL on the lead, else resolve from company.
    if cfg.fetch_website:
        website_url = (cf.get("website") or cf.get("company_website") or cf.get("product_url") or cf.get("domain") or "").strip()
        if not website_url and company:
            website_url = await _resolve_website(client, seat, company)
        summary = await _website_summary(website_url, cfg.website_chars)
        if summary:
            enriched["website_summary"] = summary
            enriched["website_url"] = website_url

    # Persist SYNCHRONOUSLY so the next node (ai.compose) reads fresh custom_fields,
    # then emit the projection event for audit/webhooks. Empty enrichment is fine —
    # never block the sequence (graceful degradation).
    if enriched:
        async with system_scope():
            await db_execute(
                "UPDATE omni_leads SET custom_fields = COALESCE(custom_fields,'{}'::jsonb) || $1::jsonb, "
                "updated_at = NOW() WHERE id = $2 AND workspace_id = $3",
                json.dumps(enriched), str(lead.get("id")), ctx.workspace_id,
            )

    events = [
        {
            "event_type": "lead.custom_fields_updated",
            "entity_type": "lead",
            "entity_id": str(lead.get("id")),
            "payload": {"custom_fields": enriched, "correlation_id": correlation_id, "node_id": ctx.node_id},
        }
    ] if enriched else []
    return NodeResult(
        handle="default",
        events=events,
        telemetry={"correlation_id": correlation_id, "fields": sorted(enriched.keys())},
    )


register(MANIFEST, execute)
