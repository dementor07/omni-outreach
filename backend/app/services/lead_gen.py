"""
Unified lead generation pipeline.
Replaces the single-pipeline job_search.py with a provider-dispatch model.
"""
from __future__ import annotations

import logging

from app.db import execute, fetch_one
from app.services import sequencer
from app.services.lead_source_registry import registry
from app.services.lead_sources.base import RawLead

log = logging.getLogger(__name__)


async def upsert_lead(campaign_id: str, lead: RawLead, source_type: str) -> bool:
    """Upsert a single RawLead into the DB. Returns True if newly inserted."""
    # Deduplicate by linkedin_url within campaign if available
    if lead.linkedin_url:
        existing = await fetch_one(
            "SELECT id FROM leads WHERE campaign_id=$1 AND linkedin_url=$2",
            campaign_id,
            lead.linkedin_url,
        )
        if existing:
            return False
    elif lead.email:
        # Fallback dedup by email
        existing = await fetch_one(
            "SELECT id FROM leads WHERE campaign_id=$1 AND email=$2",
            campaign_id,
            lead.email,
        )
        if existing:
            return False
    else:
        # No unique identifier — skip to avoid duplicates
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


async def run_lead_gen(campaign_id: str, config_id: str) -> None:
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

    run = await fetch_one(
        """
        INSERT INTO lead_gen_runs (campaign_id, config_id, source_type, status)
        VALUES ($1, $2, $3, 'running')
        RETURNING id
        """,
        campaign_id,
        config_id,
        source_type,
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
            SET status='done', leads_found=$1, leads_added=$2, finished_at=NOW()
            WHERE id=$3
            """,
            leads_found,
            leads_added,
            run_id,
        )
        log.info(f"[lead_gen:{run_id}] Done — {leads_added}/{leads_found} new leads")

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
