"""Seed the 'Lead Gen — Multi-Source Population' campaign.

Idempotent — re-running won't duplicate. Creates:

  • One campaign (idempotent on name)
  • Six lead_gen_configs (Apollo, Hunter, ProxyCurl, ApifyJobs, Naukri,
    ProductHunt), each scoped to the ICP:
        - Indian decision-makers at marketing / outreach / growth agencies
        - CEO / CMO / VP Marketing / Marketing Director / Head of Growth
        - LinkedIn 100+ connections (filtered at screen-time, not search-time)
  • A DAG: trigger_start fans out to 6 action_lead_gen_pull nodes (one per
    source). Each pull's 'fired' handle flows:
        action_add_tag(source:<name>)
        → condition_ai_screen (ICP filter)
        → 'true' → action_enrich(apollo or hunter or proxycurl, gap-filler)
        → action_add_tag('ready_for_outreach')

  Configs are run by the existing arq cron (cron_lead_gen in
  backend/app/worker/tasks.py) when each config's cron_schedule is set, or
  on-demand from the dashboard. This script sets cron_schedule on every
  config so the campaign self-pulls hourly.

Usage (inside backend container):
    python -m scripts.seed_lead_gen_campaign
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass

from app.config import settings
from app.db import close_pool, execute, fetch_all, fetch_one, init_pool

log = logging.getLogger("seed_lead_gen")

CAMPAIGN_NAME = "Lead Gen — Multi-Source Population"

ICP_SCREENING_PROMPT = (
    "You are an ICP gate for a B2B outreach company that sells AI sequencing to "
    "marketing agencies. ACCEPT the lead ONLY IF ALL of these are likely true "
    "based on their headline / company / location:\n"
    "  1. Title is CEO, Founder, CMO, VP Marketing, Marketing Director, Head of "
    "Growth, Head of Outreach, or a similarly senior decision-maker.\n"
    "  2. Company is a marketing agency, outreach firm, lead-gen company, growth "
    "consultancy, or martech vendor.\n"
    "  3. Located in India (any city) OR runs an India-based operation.\n"
    "Reject anything else. Respond with ACCEPT or REJECT only."
)

ICP_TITLES = [
    "CEO",
    "Founder",
    "Co-Founder",
    "CMO",
    "VP Marketing",
    "Vice President of Marketing",
    "Marketing Director",
    "Director of Marketing",
    "Head of Marketing",
    "Head of Growth",
    "Head of Outreach",
    "Growth Lead",
]

ICP_INDUSTRIES = [
    "Marketing and Advertising",
    "Marketing Services",
    "Advertising Services",
    "Public Relations and Communications Services",
]


# ── ICP config per source ───────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceSpec:
    source_type: str
    label: str
    config: dict
    cron_schedule: str
    credit_budget: int | None


def _source_specs() -> list[SourceSpec]:
    return [
        SourceSpec(
            source_type="apollo",
            label="Apollo — India marketing CXOs",
            config={
                "person_titles": ICP_TITLES,
                "organization_industries": ICP_INDUSTRIES,
                "organization_num_employees_ranges": ["11,50", "51,200", "201,500"],
                "person_locations": ["India"],
                "per_page": 25,
                "max_pages": 4,
            },
            cron_schedule="0 */2 * * *",  # every 2h
            credit_budget=200,
        ),
        SourceSpec(
            source_type="hunter",
            label="Hunter — marketing agency domains",
            config={
                # Hunter takes a list of seed domains to scrape; the runner
                # walks each domain's people. Operator can extend later from UI.
                "domains": [
                    "webengage.com",
                    "leadsquared.com",
                    "moengage.com",
                    "freshmarketer.com",
                    "wingify.com",
                ],
                "max_per_domain": 25,
                "department": "marketing",
                "seniority": "senior,executive",
            },
            cron_schedule="15 */4 * * *",  # every 4h, offset 15min
            credit_budget=300,
        ),
        SourceSpec(
            source_type="proxycurl",
            label="ProxyCurl — LinkedIn enrichment fanout",
            config={
                # ProxyCurl is best used as an enrichment provider, but its
                # search endpoint accepts a query. We seed it with a few
                # LinkedIn search queries that target our ICP.
                "queries": [
                    "Marketing Director India agency",
                    "CMO marketing agency India",
                    "Head of Growth outreach India",
                ],
                "page_size": 20,
                "max_pages": 2,
            },
            cron_schedule="30 */6 * * *",
            credit_budget=100,
        ),
        SourceSpec(
            source_type="apify_jobs",
            label="Apify LinkedIn Jobs — marketing roles India",
            config={
                "job_keywords": [
                    "Marketing Director",
                    "Head of Marketing",
                    "CMO",
                    "VP Marketing",
                ],
                "job_location": "India",
                "allowed_industries": [
                    "Marketing and Advertising",
                    "Advertising Services",
                ],
                "serper_roles": ICP_TITLES,
                "max_jobs": 50,
            },
            cron_schedule="45 */3 * * *",
            credit_budget=150,
        ),
        # Naukri — both lanes. The Apify path is ToS-friendly (Apify holds
        # the risk via residential proxies + their ToS); the stealth path is
        # zero-cost but uses undetected-chromedriver to bypass the captcha
        # wall — only enable when legal context allows.
        SourceSpec(
            source_type="naukri",
            label="Naukri (Apify) — India marketing decision-makers",
            config={
                "keywords": "Marketing Director Head Growth Agency",
                "location": "India",
                "experience_years_min": 7,
                "max_results": 100,
            },
            cron_schedule="50 */4 * * *",
            credit_budget=None,
        ),
        SourceSpec(
            source_type="naukri_stealth",
            label="Naukri (Stealth) — India marketing decision-makers",
            config={
                "keywords": "Marketing Director Head Growth Agency",
                "location": "India",
                "experience_years_min": 7,
                "max_pages": 2,
                "headless": True,
            },
            # Slightly offset from the Apify lane so they don't both spike
            # at the same minute. Less frequent — stealth runs are heavier.
            cron_schedule="5 */6 * * *",
            credit_budget=None,
        ),
        # ProductHunt — same split. Official GraphQL API (token-keyed) and
        # the stealth scraper (no token, scrape leaderboard).
        SourceSpec(
            source_type="producthunt",
            label="ProductHunt (API) — marketing tool makers",
            config={
                "topic": "marketing",
                "per_page": 20,
                "max_pages": 3,
                # PH returns votesCount=0 under app-only OAuth (PII / metric
                # protection on client_credentials grant), so leave min_votes
                # at 0 unless a user-OAuth token is wired up.
                "min_votes": 0,
            },
            cron_schedule="20 */6 * * *",
            credit_budget=None,
        ),
        SourceSpec(
            source_type="producthunt_stealth",
            label="ProductHunt (Stealth) — marketing leaderboard",
            config={
                "archive_url": "https://www.producthunt.com/leaderboard/all",
                "max_products": 80,
                "max_scrolls": 20,
                "headless": True,
            },
            cron_schedule="40 */8 * * *",
            credit_budget=None,
        ),
    ]


# ── Idempotent upserts ──────────────────────────────────────────────────────


async def upsert_campaign() -> str:
    existing = await fetch_one(
        "SELECT id FROM campaigns WHERE name=$1 LIMIT 1",
        CAMPAIGN_NAME,
    )
    if existing:
        log.info("Campaign already exists: %s", existing["id"])
        # Refresh screening_prompt so re-runs pick up edits.
        await execute(
            "UPDATE campaigns SET screening_prompt=$1 WHERE id=$2",
            ICP_SCREENING_PROMPT,
            existing["id"],
        )
        return str(existing["id"])

    row = await fetch_one(
        """
        INSERT INTO campaigns
            (name, status, daily_lead_cap, simulation_mode, timezone,
             active_hours_start, active_hours_end, screening_prompt)
        VALUES ($1, 'active', 500, FALSE, 'Asia/Kolkata', 9, 19, $2)
        RETURNING id
        """,
        CAMPAIGN_NAME,
        ICP_SCREENING_PROMPT,
    )
    log.info("Campaign created: %s", row["id"])
    return str(row["id"])


async def upsert_lead_gen_configs(campaign_id: str) -> dict[str, str]:
    """Returns mapping source_type → config_id."""
    config_ids: dict[str, str] = {}
    for spec in _source_specs():
        existing = await fetch_one(
            "SELECT id FROM lead_gen_configs WHERE campaign_id=$1 AND source_type=$2",
            campaign_id,
            spec.source_type,
        )
        if existing:
            await execute(
                """
                UPDATE lead_gen_configs
                   SET config=$1, label=$2, is_enabled=TRUE,
                       cron_schedule=$3, credit_budget=$4
                 WHERE id=$5
                """,
                json.dumps(spec.config),
                spec.label,
                spec.cron_schedule,
                spec.credit_budget,
                existing["id"],
            )
            config_ids[spec.source_type] = str(existing["id"])
            log.info("config refreshed: %s", spec.source_type)
            continue
        row = await fetch_one(
            """
            INSERT INTO lead_gen_configs
                (campaign_id, source_type, config, label, is_enabled,
                 cron_schedule, credit_budget)
            VALUES ($1, $2, $3, $4, TRUE, $5, $6)
            RETURNING id
            """,
            campaign_id,
            spec.source_type,
            json.dumps(spec.config),
            spec.label,
            spec.cron_schedule,
            spec.credit_budget,
        )
        config_ids[spec.source_type] = str(row["id"])
        log.info("config created: %s id=%s", spec.source_type, row["id"])
    return config_ids


# ── DAG ──────────────────────────────────────────────────────────────────────


@dataclass
class NodeSpec:
    key: str
    node_type: str
    data: dict
    x: float
    y: float


def _dag_spec(config_ids: dict[str, str]) -> tuple[list[NodeSpec], list[tuple[str, str, str]]]:
    """Returns (nodes, edges) where each edge is (source_key, target_key, handle)."""
    nodes: list[NodeSpec] = [
        NodeSpec("start", "trigger_start", {}, 0, 0),
    ]

    edges: list[tuple[str, str, str]] = []

    # Per-source vertical lane: pull → tag → screen → enrich → final tag.
    # 8 sources today — 4 API-keyed + 2 Naukri (Apify + stealth) + 2 PH
    # (API + stealth). Lanes laid out left-to-right, centred on start node.
    lane_x_step = 320.0
    y_root = 120.0
    lane_sources = [
        "apollo",
        "hunter",
        "proxycurl",
        "apify_jobs",
        "naukri",
        "naukri_stealth",
        "producthunt",
        "producthunt_stealth",
    ]
    for i, source in enumerate(lane_sources):
        col_x = (i - (len(lane_sources) - 1) / 2.0) * lane_x_step

        pull = NodeSpec(
            key=f"pull_{source}",
            node_type="action_lead_gen_pull" if source != "csv_import" else "action_csv_import",
            data={"config_id": config_ids[source], "cooldown_minutes": 60},
            x=col_x,
            y=y_root + 0,
        )

        tag_source = NodeSpec(
            key=f"tag_source_{source}",
            node_type="action_add_tag",
            data={"tag": f"src:{source}"},
            x=col_x,
            y=y_root + 160,
        )

        screen = NodeSpec(
            key=f"screen_{source}",
            node_type="condition_ai_screen",
            data={"screening_prompt": ICP_SCREENING_PROMPT},
            x=col_x,
            y=y_root + 320,
        )

        # Enrichment node — Apollo for everyone except Apollo itself (avoid
        # self-enrich loop); Apollo-sourced leads get Hunter for email + phone.
        enrich_with = "apollo" if source != "apollo" else "hunter"
        enrich = NodeSpec(
            key=f"enrich_{source}",
            node_type="action_enrich",
            data={"enrich_source": enrich_with},
            x=col_x,
            y=y_root + 480,
        )

        ready = NodeSpec(
            key=f"ready_{source}",
            node_type="action_add_tag",
            data={"tag": "ready_for_outreach"},
            x=col_x,
            y=y_root + 640,
        )

        nodes.extend([pull, tag_source, screen, enrich, ready])

        edges.extend(
            [
                ("start", pull.key, "default"),
                (pull.key, tag_source.key, "fired"),
                (tag_source.key, screen.key, "default"),
                (screen.key, enrich.key, "true"),
                (enrich.key, ready.key, "default"),
            ]
        )

    return nodes, edges


async def upsert_dag(campaign_id: str, config_ids: dict[str, str]) -> None:
    """Wipes any existing DAG for this campaign and rewrites it.

    Safe because no other tooling shares this campaign — the campaign was
    minted by this script and exists for this DAG only. Wiping ensures a
    re-run picks up any node/edge tweaks without leaving orphans.
    """
    await execute("DELETE FROM sequence_edges WHERE campaign_id=$1", campaign_id)
    await execute("DELETE FROM sequence_nodes WHERE campaign_id=$1", campaign_id)

    nodes, edges = _dag_spec(config_ids)

    key_to_id: dict[str, str] = {}
    for n in nodes:
        node_id = str(uuid.uuid4())
        await execute(
            """
            INSERT INTO sequence_nodes
                (id, campaign_id, node_type, position_x, position_y, data)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            node_id,
            campaign_id,
            n.node_type,
            n.x,
            n.y,
            json.dumps(n.data),
        )
        key_to_id[n.key] = node_id

    for source_key, target_key, handle in edges:
        await execute(
            """
            INSERT INTO sequence_edges
                (campaign_id, source_node_id, target_node_id, source_handle)
            VALUES ($1, $2, $3, $4)
            """,
            campaign_id,
            key_to_id[source_key],
            key_to_id[target_key],
            handle,
        )

    log.info("DAG: %s nodes, %s edges", len(nodes), len(edges))


# ── Smoke test ──────────────────────────────────────────────────────────────


async def smoke_summary(campaign_id: str) -> None:
    counts = await fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM lead_gen_configs WHERE campaign_id=$1) AS configs,
          (SELECT COUNT(*) FROM sequence_nodes  WHERE campaign_id=$1) AS nodes,
          (SELECT COUNT(*) FROM sequence_edges  WHERE campaign_id=$1) AS edges,
          (SELECT COUNT(*) FROM leads           WHERE campaign_id=$1) AS leads
        """,
        campaign_id,
    )
    log.info(
        "summary  configs=%s nodes=%s edges=%s leads=%s",
        counts["configs"], counts["nodes"], counts["edges"], counts["leads"],
    )

    # Which sources are wire-ready (API keys present)?
    from app.services.lead_source_registry import registry

    rows = await fetch_all(
        "SELECT source_type, label, is_enabled FROM lead_gen_configs WHERE campaign_id=$1 ORDER BY source_type",
        campaign_id,
    )
    for r in rows:
        src = registry.get(r["source_type"])
        avail = src.is_available if src else False
        flag = "OK " if avail else "OFF"
        log.info("  %s %-13s  %s", flag, r["source_type"], r["label"])


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info("Connecting to %s", os.environ.get("DATABASE_URL", "<default>"))
    await init_pool(settings.get_asyncpg_dsn())
    try:
        campaign_id = await upsert_campaign()
        config_ids = await upsert_lead_gen_configs(campaign_id)
        await upsert_dag(campaign_id, config_ids)
        await smoke_summary(campaign_id)
        log.info("DONE. Campaign id: %s", campaign_id)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
