"""Naukri job scraping via the Camoufox headless browser.

Camoufox is an anti-detect browser (a Playwright fork with fingerprint spoofing)
that gets past the bot protection on naukri.com.

IMPORTANT — robust strategy: Naukri's SRP is a SPA that renders results from an
internal JSON API (``/jobapi/v3/search``). Scraping the DOM is fragile (CSS-module
hashed class names change without notice — the original port's ``jobTuple``
selectors broke). Instead we navigate the page and CAPTURE the JSON response the
page itself fetches (it carries Naukri's required cookies/nkparam, so it returns
200 where a synthetic fetch gets ``406 recaptcha required``). We parse that JSON.

Discovered live 2026-06: jobapi/v3/search returns
``{jobDetails: [{companyName, title, jobDescription, jdURL, placeholders:[{type,label}]}]}``.
"""

from __future__ import annotations

import logging

from camoufox.async_api import AsyncCamoufox

log = logging.getLogger("camoufox.scraper")

_NAV_TIMEOUT_MS = 45000
_SETTLE_MS = 3000


def build_naukri_url(keywords: str, location: str | None = None, page: int = 1) -> str:
    """Build a Naukri SRP URL. One role keyword at a time gives the cleanest
    results (e.g. 'SDR' -> /sdr-jobs)."""
    kw_slug = keywords.strip().lower().replace(" ", "-")
    if location:
        loc_slug = location.strip().lower().replace(" ", "-")
        base = f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}"
    else:
        base = f"https://www.naukri.com/{kw_slug}-jobs"
    return f"{base}-{page}" if page > 1 else base


def _placeholder(job: dict, kind: str) -> str:
    for ph in job.get("placeholders") or []:
        if ph.get("type") == kind:
            return ph.get("label", "") or ""
    return ""


def _map_job(job: dict) -> dict:
    """Map a Naukri jobapi job object to our normalized job dict."""
    jd_url = job.get("jdURL") or ""
    if jd_url and jd_url.startswith("/"):
        jd_url = f"https://www.naukri.com{jd_url}"
    return {
        "company_name": (job.get("companyName") or "").strip(),
        "title": (job.get("title") or "").strip(),
        "url": jd_url,
        "description": (job.get("jobDescription") or "").strip(),
        "location": _placeholder(job, "location"),
        "experience": _placeholder(job, "experience"),
    }


async def fetch_jobs(
    keywords: str,
    location: str | None = None,
    max_pages: int = 1,
    browser=None,
) -> list[dict]:
    """Scrape up to ``max_pages`` of Naukri results for one keyword (~20/page) by
    capturing the page's own jobapi/v3/search JSON response. Reuses a persistent
    browser when passed; else launches its own."""
    all_jobs: list[dict] = []
    log.info("Naukri scrape: keyword='%s' location=%s pages=%d", keywords, location, max_pages)

    async def _scrape(b):
        page = await b.new_page()
        try:
            for page_num in range(1, max_pages + 1):
                url = build_naukri_url(keywords, location, page=page_num)
                log.info("Fetching page %d: %s", page_num, url)
                try:
                    async with page.expect_response(
                        lambda r: "jobapi/v3/search" in r.url and r.status == 200,
                        timeout=_NAV_TIMEOUT_MS,
                    ) as resp_info:
                        await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                    resp = await resp_info.value
                    data = await resp.json()
                except Exception as exc:  # noqa: BLE001
                    log.warning("Page %d: no jobapi response captured (%s) — stopping", page_num, exc)
                    break

                job_details = data.get("jobDetails") or []
                if not job_details:
                    log.warning("Page %d: jobDetails empty — stopping", page_num)
                    break

                mapped = [_map_job(j) for j in job_details]
                mapped = [m for m in mapped if m["company_name"] and m["title"]]
                log.info("Page %d: %d jobs (of %d raw)", page_num, len(mapped), len(job_details))
                all_jobs.extend(mapped)
                await page.wait_for_timeout(_SETTLE_MS)
        finally:
            # Guard the close: when the browser transport has already died
            # (Camoufox/Playwright "handler is closed"), page.close() itself
            # raises and would mask the scrape result / crash the request. The
            # page is gone anyway — swallow it and let the caller recycle the
            # browser. Whatever pages we captured before the death still return.
            try:
                await page.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("page.close() after scrape failed (browser transport dead?): %s", exc)

    if browser is not None:
        await _scrape(browser)
    else:
        async with AsyncCamoufox(headless=True) as b:
            await _scrape(b)

    return all_jobs
