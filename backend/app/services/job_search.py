"""
Lead gen pipeline:
  1. Apify LinkedIn jobs scraper → raw job postings
  2. Industry filter (configurable, default IT Services + Software Dev)
  3. SERPER Google search → decision-maker LinkedIn profiles per company
  4. Upsert leads directly into DB
"""
import asyncio
import logging
import re

import httpx

from app.config import settings
from app.db import execute, fetch_one
from app.services import sequencer

log = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
SERPER_CONCURRENCY = 3
MAX_RETRIES = 3


# ── Apify ─────────────────────────────────────────────────────────────────────

async def run_apify_actor(actor_id: str, input_payload: dict) -> list[dict]:
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {settings.apify_api_key}"}

    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f"{base}/acts/{actor_id}/runs",
            headers=headers,
            json={"input": input_payload},
        )
        r.raise_for_status()
        run_id = r.json()["data"]["id"]
        log.info(f"Apify run started: {run_id}")

        while True:
            await asyncio.sleep(10)
            r = await client.get(f"{base}/actor-runs/{run_id}", headers=headers)
            r.raise_for_status()
            status = r.json()["data"]["status"]
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise RuntimeError(f"Apify run {run_id} ended with status: {status}")

        r = await client.get(
            f"{base}/actor-runs/{run_id}/dataset/items",
            headers=headers,
            params={"clean": "true"},
        )
        r.raise_for_status()
        return r.json()


# ── Industry filter ───────────────────────────────────────────────────────────

def filter_by_industry(jobs: list[dict], allowed: list[str]) -> list[dict]:
    allowed_lower = {s.lower() for s in allowed}
    seen_companies: set[str] = set()
    result = []
    for job in jobs:
        sector = (job.get("sector") or job.get("companyIndustry") or "").lower()
        company = job.get("companyName") or job.get("company") or ""
        if not company or company in seen_companies:
            continue
        if any(a in sector for a in allowed_lower):
            seen_companies.add(company)
            result.append(job)
    log.info(f"Industry filter: {len(jobs)} jobs → {len(result)} unique companies")
    return result


# ── SERPER decision-maker search ──────────────────────────────────────────────

def _is_linkedin_profile(url: str) -> bool:
    return bool(re.search(r"linkedin\.com/in/", url))


def _clean_role(title: str, company_name: str) -> str:
    if not title:
        return ""
    title = re.sub(re.escape(company_name), "", title, flags=re.IGNORECASE)
    for sep in ["|", "-", ",", "•", "–"]:
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            if parts:
                title = parts[0]
                break
    keywords = ["CEO", "Founder", "CTO", "CMO", "Marketing", "Director", "Manager", "VP", "Chief", "Head"]
    if any(k.lower() in title.lower() for k in keywords):
        return title.strip()
    return ""


async def search_decision_makers(
    client: httpx.AsyncClient,
    company_name: str,
    roles: list[str],
    max_per_company: int,
) -> list[dict]:
    headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}
    found: list[dict] = []
    seen_urls: set[str] = set()

    for role in roles:
        if len(found) >= max_per_company:
            break

        for attempt in range(MAX_RETRIES):
            try:
                query = f'{role} at {company_name} site:linkedin.com/in'
                r = await client.post(
                    SERPER_URL,
                    headers=headers,
                    json={"q": query, "num": 5},
                    timeout=30,
                )
                if r.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                r.raise_for_status()

                for item in r.json().get("organic", []):
                    link = item.get("link", "")
                    title = item.get("title", "")
                    if _is_linkedin_profile(link) and link not in seen_urls:
                        seen_urls.add(link)
                        name = title.split(" - ")[0].strip()
                        parts = name.split()
                        role_clean = _clean_role(
                            " - ".join(title.split(" - ")[1:]), company_name
                        ) or role
                        found.append({
                            "linkedin_url": link,
                            "first_name": parts[0] if parts else "",
                            "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
                            "headline": role_clean,
                        })
                        if len(found) >= max_per_company:
                            break
                break
            except Exception as e:
                log.warning(f"SERPER error for '{role}' at '{company_name}': {e}")
                break

        await asyncio.sleep(0.5)

    return found


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def upsert_leads(campaign_id: str, company: dict, profiles: list[dict]) -> int:
    added = 0
    for p in profiles:
        existing = await fetch_one(
            "SELECT id FROM leads WHERE campaign_id=$1 AND linkedin_url=$2",
            campaign_id, p["linkedin_url"],
        )
        if existing:
            continue

        lead = await fetch_one(
            """
            INSERT INTO leads
                (campaign_id, linkedin_url, first_name, last_name, headline,
                 company, company_linkedin_url, job_url, source)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'job_search')
            RETURNING id
            """,
            campaign_id,
            p["linkedin_url"],
            p.get("first_name", ""),
            p.get("last_name", ""),
            p.get("headline", ""),
            company.get("companyName") or company.get("company", ""),
            company.get("companyLinkedInUrl") or company.get("companyUrl", ""),
            company.get("jobUrl") or company.get("url", ""),
        )

        if lead:
            await sequencer.schedule_new_lead(str(lead["id"]))
            added += 1

    return added


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run_job_search(campaign_id: str, config_id: str) -> str:
    config = await fetch_one(
        "SELECT * FROM job_search_configs WHERE id=$1", config_id
    )
    if not config:
        raise ValueError(f"Config {config_id} not found")

    run = await fetch_one(
        """
        INSERT INTO job_search_runs (campaign_id, config_id, status)
        VALUES ($1, $2, 'running') RETURNING id
        """,
        campaign_id, config_id,
    )
    run_id = str(run["id"])

    try:
        # 1. Apify scrape
        log.info(f"[run:{run_id}] Apify actor {config['apify_actor_id']}")
        jobs_raw = await run_apify_actor(
            config["apify_actor_id"],
            {
                "queries": config["job_keywords"],
                "location": config.get("job_location") or "",
                "maxResults": config["max_companies"] * 5,
            },
        )
        await execute(
            "UPDATE job_search_runs SET jobs_scraped=$1 WHERE id=$2",
            len(jobs_raw), run_id,
        )

        # 2. Industry filter
        companies = filter_by_industry(jobs_raw, config["allowed_industries"])
        companies = companies[: config["max_companies"]]
        await execute(
            "UPDATE job_search_runs SET companies_filtered=$1 WHERE id=$2",
            len(companies), run_id,
        )

        # 3. SERPER decision-maker search (concurrent)
        sem = asyncio.Semaphore(SERPER_CONCURRENCY)
        leads_found = 0
        leads_added = 0

        async def process_company(company: dict) -> None:
            nonlocal leads_found, leads_added
            async with sem:
                async with httpx.AsyncClient() as client:
                    profiles = await search_decision_makers(
                        client,
                        company.get("companyName") or company.get("company", ""),
                        list(config["serper_roles"]),
                        config["max_leads_per_company"],
                    )
                leads_found += len(profiles)
                added = await upsert_leads(campaign_id, company, profiles)
                leads_added += added
                log.info(
                    f"[run:{run_id}] {company.get('companyName','?')} "
                    f"→ {len(profiles)} found, {added} new"
                )

        await asyncio.gather(*[process_company(c) for c in companies])

        # 4. Finish
        await execute(
            """
            UPDATE job_search_runs
            SET status='done', leads_found=$1, leads_added=$2, finished_at=NOW()
            WHERE id=$3
            """,
            leads_found, leads_added, run_id,
        )
        log.info(f"[run:{run_id}] Done — {leads_added} new leads added")

    except Exception as e:
        log.exception(f"[run:{run_id}] Pipeline failed")
        await execute(
            "UPDATE job_search_runs SET status='failed', error=$1, finished_at=NOW() WHERE id=$2",
            str(e), run_id,
        )
        raise

    return run_id
