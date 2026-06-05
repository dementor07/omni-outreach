"""Naukri job scraping via the Camoufox headless browser.

Camoufox is an anti-detect browser (a Playwright fork with fingerprint spoofing)
that gets past Cloudflare / Akamai / DataDome bot protection on job portals.

Ported from omniagenticai/omni-outreach feature/dev-automation
(services/camoufox/scraper.py). The Naukri DOM selectors (jobTuple / comp-name /
title / job-desc / locWdth / expwdth) are calibrated against live Naukri markup —
keep them verbatim unless Naukri changes its layout.
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup
from camoufox.async_api import AsyncCamoufox

log = logging.getLogger("camoufox.scraper")

# How long to let Naukri's client-side render settle before reading the DOM.
_PAGE_SETTLE_MS = 5000


def build_naukri_url(keywords: str, location: str | None = None, page: int = 1) -> str:
    """Build a Naukri search URL. One role keyword at a time gives the cleanest
    results (e.g. 'SDR' -> /sdr-jobs)."""
    kw_slug = keywords.strip().replace(" ", "-")
    if location:
        loc_slug = location.strip().replace(" ", "-")
        base = f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}"
    else:
        base = f"https://www.naukri.com/{kw_slug}-jobs"
    return f"{base}-{page}" if page > 1 else base


def extract_jobs(page_content: str) -> list[dict]:
    """Parse a Naukri SRP page into job dicts."""
    soup = BeautifulSoup(page_content, "lxml")
    job_cards = soup.find_all(
        "div", class_=lambda c: c and ("jobTuple" in c or "srp-jobtuple" in c)
    )

    jobs: list[dict] = []
    for card in job_cards:
        title_elem = card.find("a", class_="title")
        company_elem = card.find("a", class_=lambda c: c and "comp-name" in c)
        desc_elem = card.find("span", class_="job-desc")
        loc_elem = card.find("span", class_=lambda c: c and "locWdth" in c)
        exp_elem = card.find("span", class_=lambda c: c and "expwdth" in c)

        jobs.append(
            {
                "company_name": company_elem.text.strip() if company_elem else "",
                "title": title_elem.text.strip() if title_elem else "",
                "url": title_elem.get("href") if title_elem else "",
                "description": desc_elem.text.strip() if desc_elem else "",
                "location": loc_elem.text.strip() if loc_elem else "",
                "experience": exp_elem.text.strip() if exp_elem else "",
            }
        )
    return jobs


async def fetch_jobs(
    keywords: str,
    location: str | None = None,
    max_pages: int = 1,
    browser=None,
) -> list[dict]:
    """Scrape up to ``max_pages`` of Naukri results for one keyword (~20/page).

    Stops early on a captcha wall or an empty page. Reuses a persistent browser
    when one is passed (the service keeps one warm), else launches its own.
    """
    all_jobs: list[dict] = []
    log.info("Naukri scrape: keyword='%s' location=%s pages=%d", keywords, location, max_pages)

    async def _scrape(b):
        page = await b.new_page()
        try:
            for page_num in range(1, max_pages + 1):
                url = build_naukri_url(keywords, location, page=page_num)
                log.info("Fetching page %d: %s", page_num, url)
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(_PAGE_SETTLE_MS)

                content = await page.content()
                lowered = content.lower()
                if "recaptcha" in lowered or "cloudflare" in lowered:
                    log.error("Blocked by captcha/cloudflare on page %d — stopping", page_num)
                    break

                jobs = extract_jobs(content)
                if not jobs:
                    log.warning("No jobs on page %d — stopping", page_num)
                    break

                log.info("Extracted %d jobs from page %d", len(jobs), page_num)
                all_jobs.extend(jobs)
        finally:
            await page.close()

    if browser is not None:
        await _scrape(browser)
    else:
        async with AsyncCamoufox(headless=True) as b:
            await _scrape(b)

    return all_jobs
