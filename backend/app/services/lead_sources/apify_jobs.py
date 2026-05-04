"""
Apify LinkedIn Jobs + SERPER decision-maker search.
This is the original pipeline, extracted into the provider pattern.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import settings

from .base import LeadSource, RawLead
from .utils import is_linkedin_profile, clean_role

log = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
SERPER_CONCURRENCY = 3
MAX_RETRIES = 3
APIFY_BASE = "https://api.apify.com/v2"

DEFAULT_INDUSTRIES = ["IT Services", "Software Dev", "Software Development", "Information Technology"]
DEFAULT_ROLES = ["CEO", "CTO", "CMO", "VP Sales", "Head of Marketing", "Founder", "Director"]


# ── Apify ─────────────────────────────────────────────────────────────────────

async def _run_apify_actor(actor_id: str, input_payload: dict) -> list[dict]:
    headers = {"Authorization": f"Bearer {settings.apify_api_key}"}
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f"{APIFY_BASE}/acts/{actor_id}/runs",
            headers=headers,
            json={"input": input_payload},
        )
        r.raise_for_status()
        run_id = r.json()["data"]["id"]
        log.info(f"[apify] run started: {run_id}")

        while True:
            await asyncio.sleep(10)
            r = await client.get(f"{APIFY_BASE}/actor-runs/{run_id}", headers=headers)
            r.raise_for_status()
            status = r.json()["data"]["status"]
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise RuntimeError(f"Apify run {run_id}: {status}")

        r = await client.get(
            f"{APIFY_BASE}/actor-runs/{run_id}/dataset/items",
            headers=headers,
            params={"clean": "true"},
        )
        r.raise_for_status()
        return r.json()


# ── Industry filter ───────────────────────────────────────────────────────────

def _filter_by_industry(jobs: list[dict], allowed: list[str]) -> list[dict]:
    allowed_lower = {s.lower() for s in allowed}
    seen: set[str] = set()
    result = []
    for job in jobs:
        sector = (job.get("sector") or job.get("companyIndustry") or "").lower()
        company = job.get("companyName") or job.get("company") or ""
        if not company or company in seen:
            continue
        if any(a in sector for a in allowed_lower):
            seen.add(company)
            result.append(job)
    return result


# ── SERPER decision-maker lookup ──────────────────────────────────────────────

async def _search_decision_makers(
    company_name: str,
    roles: list[str],
    max_per_company: int,
) -> list[RawLead]:
    headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}
    found: list[RawLead] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient() as client:
        for role in roles:
            if len(found) >= max_per_company:
                break
            for attempt in range(MAX_RETRIES):
                try:
                    r = await client.post(
                        SERPER_URL,
                        headers=headers,
                        json={"q": f'{role} at {company_name} site:linkedin.com/in', "num": 5},
                        timeout=30,
                    )
                    if r.status_code == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    r.raise_for_status()
                    for item in r.json().get("organic", []):
                        link = item.get("link", "")
                        title = item.get("title", "")
                        if is_linkedin_profile(link) and link not in seen_urls:
                            seen_urls.add(link)
                            name = title.split(" - ")[0].strip()
                            parts = name.split()
                            role_clean = clean_role(
                                " - ".join(title.split(" - ")[1:]), company_name
                            ) or role
                            found.append(RawLead(
                                first_name=parts[0] if parts else "",
                                last_name=" ".join(parts[1:]) if len(parts) > 1 else "",
                                linkedin_url=link,
                                headline=role_clean,
                                company=company_name,
                            ))
                            if len(found) >= max_per_company:
                                break
                    break
                except Exception as e:
                    log.warning(f"[serper] '{role}' at '{company_name}': {e}")
                    break
            await asyncio.sleep(0.5)

    return found


# ── Provider ──────────────────────────────────────────────────────────────────

class ApifyJobsSource(LeadSource):
    source_type = "apify_jobs"
    display_name = "LinkedIn Job Postings"
    description = (
        "Scrape LinkedIn job postings via Apify, filter by industry, then "
        "find decision-makers at matching companies using Google/SERPER."
    )

    @property
    def is_available(self) -> bool:
        return bool(settings.apify_api_key and settings.serper_api_key)

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["keywords", "location"],
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Job Keywords",
                    "description": "e.g. ['software engineer', 'react developer']",
                },
                "location": {
                    "type": "string",
                    "title": "Location",
                    "description": "e.g. San Francisco, CA",
                },
                "roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Decision-Maker Roles",
                    "description": "Roles to search for at each company",
                    "default": DEFAULT_ROLES,
                },
                "allowed_industries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Allowed Industries",
                    "default": DEFAULT_INDUSTRIES,
                },
                "max_companies": {
                    "type": "integer",
                    "title": "Max Companies",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 200,
                },
                "max_leads_per_company": {
                    "type": "integer",
                    "title": "Max Leads per Company",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 20,
                },
                "apify_actor_id": {
                    "type": "string",
                    "title": "Apify Actor ID",
                    "default": "hMvNSpz3JnHgl5jkh",
                    "description": "Apify LinkedIn Jobs scraper actor ID",
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        actor_id = config.get("apify_actor_id", "hMvNSpz3JnHgl5jkh")
        keywords = config.get("keywords", [])
        location = config.get("location", "")
        allowed_industries = config.get("allowed_industries", DEFAULT_INDUSTRIES)
        max_companies = config.get("max_companies", 20)
        roles = config.get("roles", DEFAULT_ROLES)
        max_leads_per_company = config.get("max_leads_per_company", 3)

        # 1. Apify scrape
        jobs_raw = await _run_apify_actor(
            actor_id,
            {"queries": keywords, "location": location, "maxResults": max_companies * 5},
        )
        log.info(f"[apify_jobs] scraped {len(jobs_raw)} job postings")

        # 2. Industry filter + cap
        companies = _filter_by_industry(jobs_raw, allowed_industries)[:max_companies]
        log.info(f"[apify_jobs] {len(companies)} companies after filter")

        # 3. SERPER decision-maker search (concurrent)
        sem = asyncio.Semaphore(SERPER_CONCURRENCY)
        all_leads: list[RawLead] = []

        async def process_company(company: dict) -> None:
            async with sem:
                company_name = company.get("companyName") or company.get("company", "")
                profiles = await _search_decision_makers(company_name, roles, max_leads_per_company)
                for p in profiles:
                    p.company_linkedin_url = company.get("companyLinkedInUrl") or company.get("companyUrl")
                    p.job_url = company.get("jobUrl") or company.get("url")
                all_leads.extend(profiles)

        await asyncio.gather(*[process_company(c) for c in companies])
        log.info(f"[apify_jobs] {len(all_leads)} leads found")
        return all_leads
