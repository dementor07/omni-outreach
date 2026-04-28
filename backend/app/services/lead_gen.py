"""
Unified lead generation pipeline.
Replaces the single-pipeline job_search.py with a provider-dispatch model.
"""
from __future__ import annotations

import logging
import os

from app.db import execute, fetch_one
from app.services import sequencer
from app.services.lead_source_registry import registry
from app.services.lead_sources.base import RawLead

log = logging.getLogger(__name__)


def _dedupe_scope() -> str:
    """`campaign` (default) or `global`. Controls whether a lead present in any
    campaign blocks reinsertion in another, or only within the same campaign."""
    return os.environ.get("LEAD_DEDUPE_SCOPE", "campaign").strip().lower()


async def upsert_lead(campaign_id: str, lead: RawLead, source_type: str) -> bool:
    """Upsert a single RawLead into the DB. Returns True if newly inserted."""
    # linkedin_url is the primary identifier — the DB has a NOT NULL constraint
    # and all outreach is LinkedIn-routed. Leads without it cannot be inserted.
    if not lead.linkedin_url:
        log.warning(f"[lead_gen] Skipping lead with no linkedin_url (email={lead.email})")
        return False

    # Blacklist gate — refuse to insert leads matching any blocked identifier.
    # Checked here (intake) so the lead never enters the campaign DAG; the
    # dispatcher does its own check at delivery time as defense-in-depth.
    from app.routers.blacklist import is_blacklisted

    if lead.email and await is_blacklisted(lead.email, "email"):
        log.info(f"[lead_gen] Skipping blacklisted email {lead.email}")
        return False
    if await is_blacklisted(lead.linkedin_url, "linkedin_url"):
        log.info(f"[lead_gen] Skipping blacklisted linkedin_url {lead.linkedin_url}")
        return False
    if lead.company and await is_blacklisted(lead.company, "company"):
        log.info(f"[lead_gen] Skipping blacklisted company {lead.company}")
        return False

    # Email verification gate (sprint #4) — reject provably undeliverable
    # addresses early so they never consume sequence credits. Only fires when
    # Hunter is configured; unknown/risky emails are allowed through with a warning.
    if lead.email:
        from app.config import settings as _settings
        if getattr(_settings, "hunter_api_key", None):
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=8) as _c:
                    _r = await _c.get(
                        "https://api.hunter.io/v2/email-verifier",
                        params={"email": lead.email, "api_key": _settings.hunter_api_key},
                    )
                if _r.status_code == 200:
                    _status = (_r.json().get("data") or {}).get("result", "unknown")
                    if _status == "undeliverable":
                        log.info(f"[lead_gen] Rejecting undeliverable email {lead.email}")
                        return False
                    if _status == "risky":
                        log.warning(f"[lead_gen] Risky email {lead.email} — allowing through")
            except Exception as _exc:
                log.warning(f"[lead_gen] Hunter verify failed for {lead.email}: {_exc}")

    # Cool-off window (sprint #13) — skip leads that had recent outreach in any
    # campaign within LEAD_COOLOFF_DAYS. Set env var to 0 (default) to disable.
    _cooloff_days = int(os.environ.get("LEAD_COOLOFF_DAYS", "0"))
    if _cooloff_days > 0:
        _recent = await fetch_one(
            """
            SELECT 1 FROM events e
            JOIN leads l ON l.id = e.lead_id
            WHERE l.linkedin_url = $1
              AND e.occurred_at >= NOW() - make_interval(days => $2)
            LIMIT 1
            """,
            lead.linkedin_url, _cooloff_days,
        )
        if _recent:
            log.info(
                f"[lead_gen] Skipping {lead.linkedin_url} — in cool-off window ({_cooloff_days}d)"
            )
            return False

    # Daily lead cap — campaigns.daily_lead_cap was previously dead config.
    # Enforce it here at intake so a noisy provider run can't drown the campaign.
    cap_row = await fetch_one(
        "SELECT daily_lead_cap FROM campaigns WHERE id=$1", campaign_id
    )
    if cap_row and cap_row["daily_lead_cap"]:
        cap = cap_row["daily_lead_cap"]
        count_row = await fetch_one(
            """
            SELECT COUNT(*) AS cnt
            FROM leads
            WHERE campaign_id = $1
              AND created_at >= DATE_TRUNC('day', NOW())
            """,
            campaign_id,
        )
        if count_row and count_row["cnt"] >= cap:
            log.info(f"[lead_gen] Campaign {campaign_id} hit daily_lead_cap={cap}; skipping")
            return False

    # Dedupe — defaults to within-campaign. Set LEAD_DEDUPE_SCOPE=global to
    # treat the lead as a duplicate when it exists in any campaign (closes the
    # cross-campaign re-contact gap from the lead-gen workflow audit).
    scope = _dedupe_scope()
    if scope == "global":
        existing = await fetch_one(
            "SELECT id FROM leads WHERE linkedin_url=$1 LIMIT 1",
            lead.linkedin_url,
        )
        if existing:
            log.info(
                f"[lead_gen] Skipping {lead.linkedin_url} — already present in another campaign (global dedupe)"
            )
            return False
    else:
        # Default: within-campaign dedupe
        existing = await fetch_one(
            "SELECT id FROM leads WHERE campaign_id=$1 AND linkedin_url=$2",
            campaign_id,
            lead.linkedin_url,
        )
        if existing:
            return False

    row = await fetch_one(
        """
        INSERT INTO leads
            (campaign_id, linkedin_url, email, first_name, last_name, headline,
             company, company_linkedin_url, job_url, source)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        RETURNING id
        """,
        campaign_id,
        lead.linkedin_url,
        lead.email,
        lead.first_name,
        lead.last_name,
        lead.headline,
        lead.company,
        lead.company_linkedin_url,
        lead.job_url,
        source_type,
    )

    if row:
        await sequencer.schedule_new_lead(str(row["id"]))
        return True
    return False


async def run_lead_gen(campaign_id: str, config_id: str, triggered_by: str = "manual") -> None:
    """
    Dispatch a lead gen run for the given config.
    Updates lead_gen_runs with status, counts, and errors.
    """
    config_row = await fetch_one("SELECT * FROM lead_gen_configs WHERE id=$1", config_id)
    if not config_row:
        raise ValueError(f"lead_gen_config {config_id} not found")

    source_type: str = config_row["source_type"]
    source_config: dict = config_row["config"] or {}

    source = registry.get(source_type)
    if not source:
        raise ValueError(f"Unknown lead source: {source_type}")
    if not source.is_available:
        raise RuntimeError(f"Lead source '{source_type}' is not available (missing API key)")

    # Credit budget gate (sprint #7b) — block run if the config has a budget
    # and previous runs have consumed it all.
    credit_budget = config_row.get("credit_budget")
    if credit_budget:
        used_row = await fetch_one(
            "SELECT COALESCE(SUM(credits_consumed), 0) AS total FROM lead_gen_runs WHERE config_id=$1 AND status='done'",
            config_id,
        )
        used = int(used_row["total"] if used_row else 0)
        if used >= credit_budget:
            raise RuntimeError(
                f"Credit budget of {credit_budget} exhausted ({used} consumed); run cancelled."
            )

    run = await fetch_one(
        """
        INSERT INTO lead_gen_runs (campaign_id, config_id, source_type, status, triggered_by)
        VALUES ($1, $2, $3, 'running', $4)
        RETURNING id
        """,
        campaign_id,
        config_id,
        source_type,
        triggered_by,
    )
    await execute(
        "UPDATE lead_gen_configs SET last_run_at=NOW() WHERE id=$1",
        config_id,
    )
    run_id = str(run["id"])
    log.info(f"[lead_gen:{run_id}] Starting source={source_type}")

    try:
        leads: list[RawLead] = await source.search(source_config)
        log.info(f"[lead_gen:{run_id}] {len(leads)} leads returned from source")

        leads_found = len(leads)
        leads_added = 0
        for lead in leads:
            added = await upsert_lead(campaign_id, lead, source_type)
            if added:
                leads_added += 1

        await execute(
            """
            UPDATE lead_gen_runs
            SET status='done', leads_found=$1, leads_added=$2,
                credits_consumed=$3, finished_at=NOW()
            WHERE id=$4
            """,
            leads_found,
            leads_added,
            leads_found,  # 1 credit per lead fetched from the source
            run_id,
        )
        log.info(
            f"[lead_gen:{run_id}] Done — {leads_added}/{leads_found} new leads "
            f"({leads_found} credits consumed)"
        )

    except Exception as e:
        log.error(f"[lead_gen:{run_id}] Error: {e}", exc_info=True)
        await execute(
            """
            UPDATE lead_gen_runs
            SET status='failed', error=$1, finished_at=NOW()
            WHERE id=$2
            """,
            str(e),
            run_id,
        )
        raise
