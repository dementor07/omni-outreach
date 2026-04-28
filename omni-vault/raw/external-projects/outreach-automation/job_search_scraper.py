"""
job_search_scraper.py — LinkedIn job-based lead sourcing pipeline.
Adapted from the linkedin-leadgen-pipeline method:
  Apify → industry filter → size filter → Unipile people search → screen → Sheets

Flow:
  1. Load job_search_configs for each enabled campaign
  2. Run Apify LinkedIn Jobs scraper → get companies with sector + size fields
  3. Filter companies by industry/sector   (allowed_sectors in DB config — NULL = no filter)
  4. Filter companies by employee count    (min_employees / max_employees in DB config — NULL = no filter)
     Size is read from Apify data if available; falls back to a Unipile company lookup.
  5. For each remaining company: Unipile people search → find decision-makers
  6. Screen headline + profile with Claude Haiku via lead_screener
  7. Write accepted leads to campaign's Google Sheet → ingest_leads() picks them up

Run manually:
  python job_search_scraper.py [campaign_id]   # single campaign
  python job_search_scraper.py                 # all enabled campaigns

New DB columns (add once via migration):
  ALTER TABLE job_search_configs
    ADD COLUMN IF NOT EXISTS allowed_sectors TEXT[],
    ADD COLUMN IF NOT EXISTS min_employees   INT,
    ADD COLUMN IF NOT EXISTS max_employees   INT;
"""
from __future__ import annotations

import logging
import re
import sys
import time
import os
import threading
from pathlib import Path

import requests

import config as cfg_module
from db import execute, fetch_all, fetch_one, lead_exists
from google_sheets_service import get_worksheet


# ─── Run logging ──────────────────────────────────────────────────────────────

def _start_run(campaign_id: str) -> int:
    row = fetch_one(
        "INSERT INTO job_search_runs (campaign_id, status) VALUES (%s, 'running') RETURNING id",
        (campaign_id,),
    )
    return row["id"]


def _finish_run(run_id: int, stats: dict, error: str | None = None) -> None:
    status = "failed" if error else "success"
    execute(
        """
        UPDATE job_search_runs SET
            status = %s,
            companies_found = %s,
            candidates_found = %s,
            accepted = %s,
            rejected = %s,
            skipped = %s,
            error_msg = %s,
            finished_at = NOW()
        WHERE id = %s
        """,
        (
            status,
            stats.get("companies", 0),
            stats.get("candidates", 0),
            stats.get("accepted", 0),
            stats.get("rejected", 0),
            stats.get("skipped", 0),
            error,
            run_id,
        ),
    )

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


# ─── Constants ────────────────────────────────────────────────────────────────

APIFY_BASE = "https://api.apify.com/v2"
UNIPILE_SEARCH_PATH = "/api/v1/linkedin/search"
UNIPILE_SEARCH_DELAY = 3.0  # 1 search per 3 s — conservative Unipile rate
MAX_PEOPLE_PER_COMPANY = 5
SERPER_SEARCH_DELAY = 1.0
SERPER_MAX_RETRIES = 3


# ─── LinkedIn company-size fetch (reference-style) ──────────────────────────

_SIZE_CACHE: dict[str, str] = {}
_SIZE_CACHE_LOCK = threading.Lock()


def _extract_size_from_text(text: str) -> str:
    """Extract a LinkedIn-like employee range string from page text."""
    if not text:
        return ""
    m = re.search(r"(\d[\d,]*(?:\.\d+)?\s*[KkMm]?\s*\+?)\s*(?:-|to)?\s*(\d[\d,]*(?:\.\d+)?\s*[KkMm]?)?\s*employees", text, re.IGNORECASE)
    if not m:
        return ""
    left = (m.group(1) or "").strip()
    right = (m.group(2) or "").strip()
    return f"{left}-{right}" if right else left


def _fetch_size_from_linkedin(company: dict) -> str:
    """
    Reference-style company-size fetch using LinkedIn page with li_at cookie.
    Returns empty string when not available; caller can fall back to other sources.
    """
    company_name = (company.get("company_name") or "").strip()
    company_url = (company.get("company_url") or "").strip()
    if not company_name or not company_url or not company_url.startswith("http"):
        return ""

    with _SIZE_CACHE_LOCK:
        cached = _SIZE_CACHE.get(company_name)
    if cached is not None:
        return cached

    li_at = (cfg_module.cfg("LINKEDIN_SESSION_COOKIE") or os.getenv("LINKEDIN_SESSION_COOKIE") or "").strip()
    if not li_at:
        return ""

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    })
    session.cookies.set("li_at", li_at, domain=".linkedin.com", path="/")

    try:
        resp = session.get(company_url, timeout=30)
        if resp.status_code >= 400:
            return ""
        size = _extract_size_from_text(resp.text)
        with _SIZE_CACHE_LOCK:
            _SIZE_CACHE[company_name] = size
        return size
    except Exception as e:
        log.debug(f"[size_fetch] LinkedIn size fetch failed for '{company_name}': {e}")
        return ""


# ─── Config loading ───────────────────────────────────────────────────────────

def _load_configs(campaign_id: str | None = None) -> list[dict]:
    if campaign_id:
        rows = fetch_all(
            """
            SELECT jc.*, cs.leads_sheet_id, cs.leads_tab,
                   cc.global_dedup
            FROM job_search_configs jc
            JOIN campaign_sheets cs ON cs.campaign_id = jc.campaign_id
            LEFT JOIN campaign_constants cc ON cc.campaign_id = jc.campaign_id
            WHERE jc.enabled = TRUE AND jc.campaign_id = %s
            """,
            (campaign_id,),
        )
    else:
        rows = fetch_all(
            """
            SELECT jc.*, cs.leads_sheet_id, cs.leads_tab,
                   cc.global_dedup
            FROM job_search_configs jc
            JOIN campaign_sheets cs ON cs.campaign_id = jc.campaign_id
            LEFT JOIN campaign_constants cc ON cc.campaign_id = jc.campaign_id
            WHERE jc.enabled = TRUE
            ORDER BY jc.campaign_id
            """,
        )
    return [dict(r) for r in rows]


def _get_unipile_account(campaign_id: str) -> str:
    """Return first account_id configured for this campaign."""
    row = fetch_one(
        "SELECT account_id FROM campaign_linkedin_accounts WHERE campaign_id = %s LIMIT 1",
        (campaign_id,),
    )
    if not row:
        raise RuntimeError(f"No Unipile accounts configured for campaign {campaign_id}")
    return row["account_id"]


# ─── Apify ────────────────────────────────────────────────────────────────────

def _normalize_actor_id(actor_id: str) -> str:
    """Accept common UI input forms and convert them to Apify API path format."""
    normalized = (actor_id or "").strip()
    if "/" in normalized and "~" not in normalized:
        owner, slug = normalized.split("/", 1)
        normalized = f"{owner}~{slug}"
    return normalized

def _run_apify(actor_id: str, keywords: list[str], location: str | None, max_results: int) -> list[dict]:
    """Run Apify actor and return job listing results."""
    api_key = cfg_module.cfg("APIFY_API_KEY")
    if not api_key:
        raise RuntimeError("APIFY_API_KEY not configured in .env")

    actor_id = _normalize_actor_id(actor_id)
    if not actor_id or "~" not in actor_id:
        raise RuntimeError(f"Invalid Apify actor ID: {actor_id!r}. Expected format owner~actor-name")

    payload: dict = {
        "keywords": " OR ".join(keywords),
        "limit": max_results,
    }
    if location:
        payload["location"] = location

    log.info(f"[apify] Starting run: actor={actor_id} keywords={keywords} location={location}")

    # Start run
    resp = requests.post(
        f"{APIFY_BASE}/acts/{actor_id}/runs",
        params={"token": api_key},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    run = resp.json()["data"]
    run_id = run["id"]
    dataset_id = run["defaultDatasetId"]
    log.info(f"[apify] Run started: {run_id}")

    # Poll until done
    for _ in range(60):  # max 5 min
        time.sleep(5)
        status_resp = requests.get(
            f"{APIFY_BASE}/acts/{actor_id}/runs/{run_id}",
            params={"token": api_key},
            timeout=15,
        )
        status_resp.raise_for_status()
        status = status_resp.json()["data"]["status"]
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"[apify] Run {run_id} ended with status: {status}")
        log.info(f"[apify] Run status: {status} — waiting...")

    # Fetch results
    items_resp = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": api_key, "limit": max_results},
        timeout=30,
    )
    items_resp.raise_for_status()
    items = items_resp.json()
    log.info(f"[apify] Got {len(items)} job listings")
    return items


def _extract_companies(job_listings: list[dict]) -> list[dict]:
    """Deduplicate companies from job listings, capturing sector and size for downstream filters."""
    seen: set[str] = set()
    companies = []
    for job in job_listings:
        # Support both camelCase (linkedin-jobs-scraper) and snake_case (rapid-linkedin-scraper) field names
        name = (job.get("companyName") or job.get("company_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)

        # Sector: prefer 'sector', fall back to 'industry'/'industries'
        sector = (
            job.get("sector")
            or job.get("industry")
            or job.get("industries")
            or ""
        )

        # Company size: different actors use different field names
        raw_size = (
            job.get("companySize")
            or job.get("company_size")
            or job.get("employeeCount")
            or job.get("employees")
            or ""
        )

        companies.append({
            "company_name": name,
            "company_url": job.get("companyUrl") or job.get("company_url") or "",
            "sector": str(sector),
            "raw_size": str(raw_size),
            "industry": str(sector),  # kept for Sheets output / screening context
        })
    return companies


# ─── Industry / sector filter ─────────────────────────────────────────────────

def _filter_by_industry(companies: list[dict], allowed_sectors: list[str]) -> list[dict]:
    """Keep only companies whose sector contains one of the allowed strings (case-insensitive)."""
    normalized = [s.lower().strip() for s in allowed_sectors if s]
    kept = []
    for c in companies:
        c_sector = c.get("sector", "").lower()
        if any(allowed in c_sector for allowed in normalized):
            kept.append(c)
        else:
            log.debug(f"[industry_filter] skip '{c['company_name']}' sector='{c['sector']}'")
    log.info(f"[industry_filter] {len(kept)}/{len(companies)} companies kept after sector filter")
    return kept


# ─── Company size filter ──────────────────────────────────────────────────────

def _parse_employee_range(raw: str) -> tuple[int | None, int | None]:
    """
    Parse LinkedIn employee-count strings into (min, max).
    Examples: '11-50', '51-200 employees', '10,001+', '5K-10K' → (min, max).
    Returns (None, None) if unparseable.
    """
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


def _fetch_size_via_unipile(company: dict, account_id: str) -> str:
    """
    Fallback: search Unipile LinkedIn company directory to retrieve employee count range.
    Returns empty string if not found.
    """
    base = cfg_module.cfg("UNIPILE_BASE")
    key = cfg_module.cfg("UNIPILE_API_KEY")
    company_name = company["company_name"]
    try:
        resp = requests.post(
            f"{base}{UNIPILE_SEARCH_PATH}",
            params={"account_id": account_id},
            headers={
                "X-API-KEY": key,
                "accept": "application/json",
                "content-type": "application/json",
            },
            json={"api": "classic", "category": "companies", "keywords": company_name},
            timeout=30,
        )
        resp.raise_for_status()
        for item in resp.json().get("items") or []:
            item_name = (item.get("name") or item.get("company_name") or "").strip()
            if item_name.lower() == company_name.lower():
                size = (
                    item.get("staffCountRange")
                    or item.get("employeeCountRange")
                    or item.get("company_size")
                    or item.get("size")
                    or ""
                )
                return str(size)
    except Exception as e:
        log.debug(f"[size_fetch] Unipile company lookup failed for '{company_name}': {e}")
    return ""


def _filter_by_size(
    companies: list[dict],
    min_employees: int | None,
    max_employees: int | None,
    account_id: str,
) -> list[dict]:
    """Filter companies by employee count range. Fails open when size is unknown."""
    kept = []
    for c in companies:
        raw = c.get("raw_size", "")
        # If Apify didn't return size, try LinkedIn page fetch first (reference flow)
        if not raw or raw == "None":
            raw = _fetch_size_from_linkedin(c)
            if raw:
                c["raw_size"] = raw

        # If still missing, fallback to Unipile company lookup
        if not raw or raw == "None":
            raw = _fetch_size_via_unipile(c, account_id)
            if raw:
                c["raw_size"] = raw

        emp_min, emp_max = _parse_employee_range(raw)
        if emp_min is None:
            # If bounds are configured, fail closed to avoid large-brand leakage.
            if min_employees is not None or max_employees is not None:
                log.info(f"[size_filter] skip '{c['company_name']}': size unknown with active bounds")
                continue
            log.debug(f"[size_filter] '{c['company_name']}': size unknown, including")
            kept.append(c)
            continue

        # Check that the company's size range overlaps with [min_employees, max_employees]
        effective_max = emp_max if emp_max is not None else emp_min
        if min_employees is not None and effective_max < min_employees:
            log.debug(f"[size_filter] skip '{c['company_name']}': max={effective_max} < {min_employees}")
            continue
        if max_employees is not None and emp_min > max_employees:
            log.debug(f"[size_filter] skip '{c['company_name']}': min={emp_min} > {max_employees}")
            continue

        kept.append(c)

    log.info(f"[size_filter] {len(kept)}/{len(companies)} companies kept after size filter")
    return kept


# ─── Contact search (Serper-first) ───────────────────────────────────────────

def _clean_role_from_title(title: str, company_name: str, fallback_role: str) -> str:
    if not title:
        return fallback_role
    cleaned = re.sub(re.escape(company_name), "", title, flags=re.IGNORECASE).strip(" -|,\u2022")
    return cleaned or fallback_role


def _search_serper_profiles(company_name: str, role: str, serper_key: str) -> list[dict]:
    """Search Serper for LinkedIn profiles matching company + role."""
    headers = {"X-API-KEY": serper_key, "Content-Type": "application/json"}
    patterns = [
        f"{role} at {company_name} site:linkedin.com/in",
        f"{company_name} {role} site:linkedin.com/in",
        f"{role} {company_name} LinkedIn",
    ]

    found: list[dict] = []
    seen_urls: set[str] = set()

    for pattern in patterns:
        for attempt in range(SERPER_MAX_RETRIES):
            try:
                resp = requests.post(
                    "https://google.serper.dev/search",
                    headers=headers,
                    json={"q": pattern, "num": 10},
                    timeout=30,
                )
                if resp.status_code == 429:
                    wait_s = 2 ** attempt
                    log.warning(f"[serper] 429 for '{pattern}', retrying in {wait_s}s")
                    time.sleep(wait_s)
                    continue
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("organic") or []:
                    url = (item.get("link") or "").strip()
                    if "linkedin.com/in/" not in url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    raw_title = (item.get("title") or "").strip()
                    name = raw_title.split(" - ")[0].strip() if raw_title else ""
                    title_tail = " - ".join(raw_title.split(" - ")[1:]).strip() if raw_title else ""
                    clean_role = _clean_role_from_title(title_tail, company_name, role)

                    found.append({
                        "first_name": name.split()[0] if name else "",
                        "last_name": " ".join(name.split()[1:]) if name else "",
                        "headline": clean_role,
                        "location": "",
                        "linkedin_url": url,
                        "company_name": company_name,
                        "industry": "",
                        "provider_id": "",
                    })
                    if len(found) >= MAX_PEOPLE_PER_COMPANY:
                        return found
                break
            except Exception as e:
                log.warning(f"[serper] Search failed for '{pattern}': {e}")
                break
            finally:
                time.sleep(SERPER_SEARCH_DELAY)
    return found


def _search_unipile_profiles(company: dict, titles: list[str], account_id: str) -> list[dict]:
    """Fallback: search Unipile for decision-makers at a company."""
    base = cfg_module.cfg("UNIPILE_BASE")
    key = cfg_module.cfg("UNIPILE_API_KEY")
    company_name = company["company_name"]
    keywords = " OR ".join(titles)

    try:
        resp = requests.post(
            f"{base}{UNIPILE_SEARCH_PATH}",
            params={"account_id": account_id},
            headers={
                "X-API-KEY": key,
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
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning(f"[unipile] Search failed for {company_name}: {e}")
        return []

    items = data.get("items") or []
    results = []
    for item in items[:MAX_PEOPLE_PER_COMPANY]:
        headline = item.get("headline") or ""
        if not any(t.lower() in headline.lower() for t in titles):
            continue
        public_id = item.get("public_identifier") or ""
        if not public_id:
            continue
        results.append({
            "first_name": (item.get("name") or "").split()[0] if item.get("name") else "",
            "last_name": " ".join((item.get("name") or "").split()[1:]),
            "headline": headline,
            "location": item.get("location") or "",
            "linkedin_url": f"https://www.linkedin.com/in/{public_id}",
            "company_name": company_name,
            "industry": company.get("sector") or company.get("industry") or "",
            "provider_id": item.get("id") or "",
        })
    return results


def _search_decision_makers(company: dict, titles: list[str], account_id: str) -> list[dict]:
    """Primary: Serper. Fallback: Unipile if SERPER_KEY missing."""
    company_name = company["company_name"]
    serper_key = (cfg_module.cfg("SERPER_KEY") or "").strip()

    if serper_key:
        all_found: list[dict] = []
        seen: set[str] = set()
        for role in titles:
            for lead in _search_serper_profiles(company_name, role, serper_key):
                url = lead["linkedin_url"]
                if url in seen:
                    continue
                seen.add(url)
                lead["industry"] = company.get("sector") or company.get("industry") or ""
                all_found.append(lead)
                if len(all_found) >= MAX_PEOPLE_PER_COMPANY:
                    break
            if len(all_found) >= MAX_PEOPLE_PER_COMPANY:
                break
        log.info(f"[serper] {company_name}: {len(all_found)} profiles")
        return all_found

    log.warning("[serper] SERPER_KEY not set; falling back to Unipile people search")
    return _search_unipile_profiles(company, titles, account_id)


# ─── Company-level screening ──────────────────────────────────────────────────

def _screen_company(company: dict, screening_prompt: str, screen_lead_fn) -> tuple[str, str]:
    """Run the screening prompt against company name + sector before fetching decision-makers."""
    name = company.get("company_name", "")
    sector = company.get("sector", "unknown")
    company_profile = {
        "first_name": name,
        "headline": f"{name} — sector: {sector}",
        "company_name": name,
        "location": company.get("location", ""),
    }
    augmented = (
        f"{screening_prompt}\n\n"
        f"NOTE: You are screening a COMPANY (not a person). The company name is '{name}' in sector '{sector}'. "
        f"REJECT if the company name or sector suggests it is a large enterprise, outsourcing firm, "
        f"or otherwise outside the target ICP."
    )
    return screen_lead_fn(company_profile, augmented)


# ─── Screening ────────────────────────────────────────────────────────────────

def _load_screener() -> object | None:
    try:
        dashboard_path = Path(__file__).parent.parent / "outreach-dashboard"
        if str(dashboard_path) not in sys.path:
            sys.path.insert(0, str(dashboard_path))
        from lead_screener import screen_lead
        return screen_lead
    except ImportError:
        log.warning("[screener] lead_screener not found — screening disabled")
        return None


# ─── Google Sheets output ─────────────────────────────────────────────────────

_SHEET_HEADERS = [
    "LinkedIn_URL", "first_name", "last_name",
    "headline", "company_name", "industry", "location",
    "source", "screening_status", "screening_reason",
]


def _push_to_sheet(ws, lead: dict, reason: str) -> None:
    """Append an accepted lead row to the campaign's leads sheet."""
    row = [
        lead.get("linkedin_url", ""),
        lead.get("first_name", ""),
        lead.get("last_name", ""),
        lead.get("headline", ""),
        lead.get("company_name", ""),
        lead.get("industry", ""),
        lead.get("location", ""),
        "job_search",
        "ACCEPT",
        reason,
    ]
    ws.append_rows([row], value_input_option="USER_ENTERED")


def _ensure_sheet_headers(ws) -> None:
    existing = ws.row_values(1)
    if not existing:
        ws.append_rows([_SHEET_HEADERS], value_input_option="USER_ENTERED")


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run_for_campaign(config: dict, screen_lead) -> dict:
    campaign_id = config["campaign_id"]
    log.info(f"\n{'='*60}")
    log.info(f"[job_search] Campaign: {campaign_id}")

    stats = {"companies": 0, "candidates": 0, "accepted": 0, "rejected": 0, "skipped": 0}
    run_id = _start_run(campaign_id)

    # Validate sheet config
    sheet_id = config.get("leads_sheet_id")
    sheet_tab = config.get("leads_tab")
    if not sheet_id or not sheet_tab:
        msg = f"No sheet configured for {campaign_id}"
        log.error(f"[job_search] {msg} — skipping")
        _finish_run(run_id, stats, error=msg)
        return stats

    account_id = _get_unipile_account(campaign_id)
    global_dedup = bool(config.get("global_dedup"))
    titles = list(config.get("decision_maker_titles") or ["CEO", "Founder", "Co-Founder", "CMO"])
    screening_prompt = config.get("screening_prompt") or ""

    # Filtering config — new columns; NULL in DB means that filter is skipped
    allowed_sectors: list[str] | None = config.get("allowed_sectors") or None
    min_employees: int | None = config.get("min_employees")
    max_employees: int | None = config.get("max_employees")

    # Step 1: Apify job search
    job_listings = _run_apify(
        actor_id=config["apify_actor_id"],
        keywords=list(config.get("job_keywords") or []),
        location=config.get("job_location"),
        max_results=config.get("max_results_per_run") or 100,
    )
    companies = _extract_companies(job_listings)
    log.info(f"[job_search] {len(companies)} unique companies from {len(job_listings)} job listings")

    # Step 2: Industry / sector filter
    if allowed_sectors:
        companies = _filter_by_industry(companies, allowed_sectors)

    # Step 3: Company size filter
    if min_employees is not None or max_employees is not None:
        companies = _filter_by_size(companies, min_employees, max_employees, account_id)

    # Step 3b: Company-level LLM screening
    if screening_prompt and screen_lead:
        before = len(companies)
        kept = []
        for c in companies:
            verdict, reason = _screen_company(c, screening_prompt, screen_lead)
            if verdict == "ACCEPT":
                kept.append(c)
                log.info(f"[company_screen] ✓ '{c['company_name']}' — {reason}")
            else:
                log.info(f"[company_screen] ✗ '{c['company_name']}' — {reason}")
        companies = kept
        log.info(f"[company_screen] {len(companies)}/{before} companies kept after LLM screen")

    stats["companies"] = len(companies)
    log.info(f"[job_search] {len(companies)} companies after filtering")

    # Open sheet once
    ws = get_worksheet(sheet_id, sheet_tab)
    _ensure_sheet_headers(ws)

    # Step 4: For each company, find decision-makers and screen
    for company in companies:
        time.sleep(UNIPILE_SEARCH_DELAY)
        candidates = _search_decision_makers(company, titles, account_id)
        stats["candidates"] += len(candidates)

        for lead in candidates:
            linkedin_url = lead["linkedin_url"]

            # Dedup check
            if lead_exists(linkedin_url, campaign_id, global_dedup=global_dedup):
                log.info(f"[job_search] dup: {linkedin_url}")
                stats["skipped"] += 1
                continue

            # Screening — inject target company so Claude can verify match
            if screening_prompt and screen_lead:
                augmented_prompt = (
                    f"{screening_prompt}\n\n"
                    f"IMPORTANT: This person was found via a job listing at '{lead['company_name']}'. "
                    f"REJECT if their headline/profile does not clearly indicate they currently work at '{lead['company_name']}'."
                )
                verdict, reason = screen_lead(lead, augmented_prompt)
            else:
                verdict, reason = "ACCEPT", "No screening configured"

            if verdict == "REJECT":
                log.info(f"[job_search] ✗ {linkedin_url} — {reason}")
                stats["rejected"] += 1
                continue

            # Push to sheet
            try:
                _push_to_sheet(ws, lead, reason)
                log.info(f"[job_search] ✓ {linkedin_url} ({lead.get('headline', '')})")
                stats["accepted"] += 1
            except Exception as e:
                log.warning(f"[job_search] Sheet write failed for {linkedin_url}: {e}")

    _finish_run(run_id, stats)
    log.info(
        f"[job_search] {campaign_id} done | "
        f"companies={stats['companies']} candidates={stats['candidates']} "
        f"accepted={stats['accepted']} rejected={stats['rejected']} skipped={stats['skipped']}"
    )
    return stats


def main(campaign_id: str | None = None) -> None:
    configs = _load_configs(campaign_id)
    if not configs:
        log.info("[job_search] No enabled job_search_configs found.")
        return

    screen_lead = _load_screener()

    total_accepted = 0
    for config in configs:
        try:
            stats = run_for_campaign(config, screen_lead)
            total_accepted += stats["accepted"]
        except Exception as e:
            log.error(f"[job_search] Campaign {config['campaign_id']} failed: {e}", exc_info=True)
            # Mark any still-running row as failed
            execute(
                "UPDATE job_search_runs SET status='failed', error_msg=%s, finished_at=NOW() WHERE campaign_id=%s AND status='running'",
                (str(e)[:500], config["campaign_id"]),
            )

    log.info(f"\n[job_search] All done. Total accepted: {total_accepted}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    main(target)
