"""
Lead gen pipeline:
  1. Apify LinkedIn jobs scraper → raw job postings
  2. Industry filter (configurable, default IT Services + Software Dev)
  3. Company size filter (optional min_employees / max_employees from config)
  4. Serper-first decision-maker search; Unipile people search as fallback
  5. Upsert via lead_gen.upsert_lead (blacklist + daily cap + dedupe gates apply)
"""
import asyncio
import logging
import re

import httpx

from app.config import settings
from app.db import execute, fetch_one
from app.services.lead_sources.base import RawLead
from app.services.lead_sources.utils import clean_role, is_linkedin_profile

log = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
SERPER_CONCURRENCY = 3
MAX_RETRIES = 3
MAX_PEOPLE_PER_COMPANY = 5
UNIPILE_SEARCH_PATH = "/api/v1/linkedin/search"


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


# ── Company size filter ───────────────────────────────────────────────────────

def _parse_employee_range(raw: str) -> tuple[int | None, int | None]:
    """Parse LinkedIn employee-count strings into (min, max).
    Examples: '11-50', '51-200 employees', '10,001+', '5K-10K'."""
    if not raw or raw.strip().lower() in ("", "none", "n/a"):
        return None, None
    raw = raw.replace(",", "").replace(" employees", "").strip()

    def _to_int(s: str) -> int:
        s = s.strip().upper()
        if "K" in s:
            return int(float(s.replace("K", "")) * 1_000)
        if "M" in s:
            return int(float(s.replace("M", "")) * 1_000_000)
        return int(float(s))

    if "+" in raw:
        m = re.search(r"([\d.]+[KkMm]?)", raw)
        if m:
            return _to_int(m.group(1)), None
        return None, None

    if "-" in raw:
        parts = raw.split("-", 1)
        try:
            return _to_int(parts[0]), _to_int(parts[1])
        except (ValueError, IndexError):
            return None, None

    try:
        n = _to_int(raw)
        return n, n
    except (ValueError, TypeError):
        return None, None


def filter_by_size(
    companies: list[dict],
    min_employees: int | None,
    max_employees: int | None,
) -> list[dict]:
    """Keep only companies whose employee-count range overlaps [min_employees, max_employees].
    Companies with unknown size are included when no bounds are set; excluded when bounds
    are active (fail-closed to prevent large-brand leakage)."""
    if min_employees is None and max_employees is None:
        return companies

    kept = []
    for c in companies:
        raw = (
            c.get("companySize")
            or c.get("company_size")
            or c.get("employeeCount")
            or c.get("employees")
            or ""
        )
        emp_min, emp_max = _parse_employee_range(str(raw))
        if emp_min is None:
            log.info(f"[size_filter] skip '{c.get('companyName','?')}': size unknown with active bounds")
            continue
        effective_max = emp_max if emp_max is not None else emp_min
        if min_employees is not None and effective_max < min_employees:
            continue
        if max_employees is not None and emp_min > max_employees:
            continue
        kept.append(c)

    log.info(f"Size filter: {len(companies)} → {len(kept)} companies")
    return kept


# ── SERPER decision-maker search ──────────────────────────────────────────────

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
                    if is_linkedin_profile(link) and link not in seen_urls:
                        seen_urls.add(link)
                        name = title.split(" - ")[0].strip()
                        parts = name.split()
                        role_clean = clean_role(
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


async def search_unipile_people(
    company_name: str,
    roles: list[str],
    max_per_company: int,
    account_id: str,
) -> list[dict]:
    """Fallback when Serper key is absent: search Unipile LinkedIn people directory."""
    if not settings.unipile_api_key or not settings.unipile_base:
        return []
    keywords = " OR ".join(roles)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.unipile_base}{UNIPILE_SEARCH_PATH}",
                params={"account_id": account_id},
                headers={
                    "X-API-KEY": settings.unipile_api_key,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json={
                    "api": "classic",
                    "category": "people",
                    "keywords": keywords,
                    "current_company": [company_name],
                    "network_distance": [2, 3],
                },
            )
            resp.raise_for_status()
    except Exception as e:
        log.warning(f"[unipile_search] {company_name}: {e}")
        return []

    found = []
    for item in (resp.json().get("items") or [])[:max_per_company]:
        headline = item.get("headline") or ""
        if not any(r.lower() in headline.lower() for r in roles):
            continue
        public_id = item.get("public_identifier") or ""
        if not public_id:
            continue
        name = item.get("name") or ""
        parts = name.split()
        found.append({
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
            "headline": headline,
            "linkedin_url": f"https://www.linkedin.com/in/{public_id}",
        })
    return found


async def find_decision_makers(
    client: httpx.AsyncClient,
    company_name: str,
    roles: list[str],
    max_per_company: int,
    account_id: str | None = None,
) -> list[dict]:
    """Serper-first; falls back to Unipile people search when Serper key is absent."""
    if getattr(settings, "serper_api_key", None):
        return await search_decision_makers(client, company_name, roles, max_per_company)
    if account_id:
        log.warning("[job_search] No SERPER key — falling back to Unipile people search")
        return await search_unipile_people(company_name, roles, max_per_company, account_id)
    return []


# ── DB upsert (routes through lead_gen gates) ─────────────────────────────────

async def upsert_leads(campaign_id: str, company: dict, profiles: list[dict]) -> int:
    """Insert profiles via lead_gen.upsert_lead so blacklist + daily cap + dedupe apply."""
    from app.services.lead_gen import upsert_lead  # avoid circular import at module load

    company_name = company.get("companyName") or company.get("company", "")
    company_li_url = company.get("companyLinkedInUrl") or company.get("companyUrl", "")
    job_url = company.get("jobUrl") or company.get("url", "")

    added = 0
    for p in profiles:
        raw = RawLead(
            first_name=p.get("first_name", ""),
            last_name=p.get("last_name", ""),
            linkedin_url=p.get("linkedin_url"),
            email=p.get("email"),
            headline=p.get("headline", ""),
            company=company_name,
            company_linkedin_url=company_li_url or None,
            job_url=job_url or None,
        )
        inserted = await upsert_lead(campaign_id, raw, "job_search")
        if inserted:
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

        # 3. Company size filter (optional — skipped when min/max are NULL)
        companies = filter_by_size(
            companies,
            config.get("min_employees"),
            config.get("max_employees"),
        )

        companies = companies[: config["max_companies"]]
        await execute(
            "UPDATE job_search_runs SET companies_filtered=$1 WHERE id=$2",
            len(companies), run_id,
        )

        # 4. Decision-maker search (Serper-first; Unipile fallback)
        # Resolve the Unipile account once so every company can use it as fallback
        li_account = await fetch_one(
            """
            SELECT la.unipile_id AS account_id
            FROM campaign_linkedin_accounts cla
            JOIN linkedin_accounts la ON la.id = cla.account_id
            WHERE cla.campaign_id = $1 AND la.is_active = TRUE
            LIMIT 1
            """,
            campaign_id,
        )
        unipile_account_id: str | None = str(li_account["account_id"]) if li_account else None

        sem = asyncio.Semaphore(SERPER_CONCURRENCY)
        leads_found = 0
        leads_added = 0

        async def process_company(company: dict) -> None:
            nonlocal leads_found, leads_added
            async with sem:
                async with httpx.AsyncClient() as client:
                    profiles = await find_decision_makers(
                        client,
                        company.get("companyName") or company.get("company", ""),
                        list(config["serper_roles"]),
                        config["max_leads_per_company"],
                        account_id=unipile_account_id,
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
