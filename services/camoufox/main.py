"""Camoufox headless-browser HTTP microservice.

Exposes a small HTTP API the Rust muscle calls over the internal Docker network:

  POST /scrape        — scrape Naukri job listings for one role keyword
  POST /search        — free Google search (Serper alternative)
  POST /lookup-domain — resolve a company's official website via Google
  POST /crawl-team    — render a company site's team/about pages (JS-aware) and
                        extract people names/titles/LinkedIn URLs

Auth: every endpoint except /health requires `X-Internal-Secret` to match
CAMOUFOX_SHARED_SECRET (set in the environment). Keeps the service closed even
though it only listens on the internal network.

Ported + hardened from omniagenticai/omni-outreach feature/dev-automation
(services/camoufox/main.py). Adds auth, env config, and the team-page crawl.
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
from camoufox.async_api import AsyncCamoufox
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from scraper import fetch_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("camoufox")

_SHARED_SECRET = os.getenv("CAMOUFOX_SHARED_SECRET", "")
# Team/about page paths to try when crawling a company domain.
_TEAM_PATHS = ("/team", "/about", "/about-us", "/leadership", "/our-team", "/people", "/company")

_camoufox = None


async def get_browser():
    global _camoufox
    if _camoufox is None:
        log.info("Starting persistent Camoufox browser")
        _camoufox = await AsyncCamoufox(headless=True).__aenter__()
    return _camoufox


async def stop_browser():
    global _camoufox
    if _camoufox is not None:
        log.info("Shutting down persistent Camoufox browser")
        await _camoufox.__aexit__(None, None, None)
        _camoufox = None


@asynccontextmanager
async def lifespan(app):
    await get_browser()
    yield
    await stop_browser()


app = FastAPI(title="Camoufox Browser Service", version="1.0.0", lifespan=lifespan)


def _require_secret(provided: str | None) -> None:
    """Constant-time shared-secret check. If no secret is configured the guard
    is open (dev), but production must set CAMOUFOX_SHARED_SECRET."""
    if not _SHARED_SECRET:
        return
    if not provided or not secrets.compare_digest(provided, _SHARED_SECRET):
        raise HTTPException(status_code=401, detail="invalid internal secret")


# ── Models ────────────────────────────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    keywords: str = "SDR"
    location: str | None = None
    max_pages: int = 1


class JobItem(BaseModel):
    company_name: str
    title: str
    url: str
    description: str
    location: str
    experience: str


class ScrapeResponse(BaseModel):
    status: str
    data: list[JobItem]
    count: int


class SearchRequest(BaseModel):
    query: str


class SearchResult(BaseModel):
    url: str
    title: str


class SearchResponse(BaseModel):
    results: list[SearchResult]


class DomainLookupRequest(BaseModel):
    company_name: str


class DomainLookupResponse(BaseModel):
    domain: str | None


class CrawlTeamRequest(BaseModel):
    domain: str  # bare host or full URL


class TeamPerson(BaseModel):
    name: str
    title: str | None = None
    linkedin_url: str | None = None


class CrawlTeamResponse(BaseModel):
    people: list[TeamPerson]
    pages_crawled: list[str]


# ── Endpoints ───────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "camoufox"}


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest, x_internal_secret: str | None = Header(None)):
    _require_secret(x_internal_secret)
    try:
        browser = await get_browser()
        raw_jobs = await fetch_jobs(
            keywords=req.keywords, location=req.location, max_pages=req.max_pages, browser=browser
        )
        jobs = [JobItem(**j) for j in raw_jobs if j.get("company_name") and j.get("title")]
        log.info("Scrape complete: %d jobs for '%s'", len(jobs), req.keywords)
        return ScrapeResponse(status="success", data=jobs, count=len(jobs))
    except Exception as exc:  # noqa: BLE001
        log.exception("Scrape failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/search", response_model=SearchResponse)
async def search_google(req: SearchRequest, x_internal_secret: str | None = Header(None)):
    """Free Google search via the persistent Camoufox browser (Serper alternative)."""
    _require_secret(x_internal_secret)
    browser = await get_browser()
    page = await browser.new_page()
    try:
        url = f"https://www.google.com/search?q={quote(req.query)}&hl=en"
        log.info("Searching: %s", req.query)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        try:
            btn = await page.query_selector('button:has-text("Accept all")')
            if btn:
                await btn.click()
                await page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001
            pass

        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []
        for g in soup.select("div.g")[:10]:
            link = g.select_one("a")
            h3 = g.select_one("h3")
            if link and h3:
                href = link.get("href", "")
                if href.startswith("/url?q="):
                    href = href.split("/url?q=")[1].split("&")[0]
                results.append(SearchResult(url=href, title=h3.get_text(strip=True)))
        log.info("Found %d results for '%s'", len(results), req.query)
        return SearchResponse(results=results)
    except Exception as exc:  # noqa: BLE001
        log.exception("Search failed for '%s'", req.query)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await page.close()


@app.post("/lookup-domain", response_model=DomainLookupResponse)
async def lookup_domain(req: DomainLookupRequest, x_internal_secret: str | None = Header(None)):
    """Resolve a company's official website via Google search."""
    _require_secret(x_internal_secret)
    results = await search_google(
        SearchRequest(query=f'"{req.company_name}" official website'), x_internal_secret
    )
    for r in results.results:
        domain = r.url.strip()
        if domain.startswith("http"):
            parsed = urlparse(domain)
            host = (parsed.netloc or parsed.path).removeprefix("www.").lower()
            if host and "." in host:
                log.info("Domain for '%s': %s", req.company_name, host)
                return DomainLookupResponse(domain=host)
    log.warning("No domain found for '%s'", req.company_name)
    return DomainLookupResponse(domain=None)


@app.post("/crawl-team", response_model=CrawlTeamResponse)
async def crawl_team(req: CrawlTeamRequest, x_internal_secret: str | None = Header(None)):
    """Render a company's team/about pages (JS-aware) and extract people.

    Many Indian SMB sites are React/Vue — reqwest sees empty HTML. Camoufox
    renders the full DOM. We look for LinkedIn /in/ links and nearby name/title
    text. People without a LinkedIn URL are still returned (used downstream as
    search hints)."""
    _require_secret(x_internal_secret)
    raw = req.domain.strip()
    base = raw if raw.startswith("http") else f"https://{raw.removeprefix('www.')}"
    browser = await get_browser()
    people: dict[str, TeamPerson] = {}
    crawled: list[str] = []
    page = await browser.new_page()
    try:
        for path in _TEAM_PATHS:
            target = urljoin(base, path)
            try:
                resp = await page.goto(target, wait_until="domcontentloaded", timeout=20000)
                if resp is None or resp.status >= 400:
                    continue
                await page.wait_for_timeout(1500)
                html = await page.content()
            except Exception:  # noqa: BLE001
                continue
            crawled.append(target)
            soup = BeautifulSoup(html, "lxml")

            # 1. LinkedIn profile links → strongest signal.
            for a in soup.select('a[href*="linkedin.com/in/"]'):
                href = a.get("href", "").split("?")[0]
                name = a.get_text(strip=True) or _nearby_text(a)
                if name and len(name) <= 80:
                    people[href] = TeamPerson(name=name, title=None, linkedin_url=href)

            # 2. Heuristic name — title pairs (e.g. "Rahul Menon — Head of Growth").
            for el in soup.find_all(["h3", "h4", "p", "div", "span"]):
                txt = el.get_text(" ", strip=True)
                for sep in (" — ", " – ", " - ", ", "):
                    if sep in txt and 6 <= len(txt) <= 80:
                        name, title = (s.strip() for s in txt.split(sep, 1))
                        if name and title and " " in name and name.lower() not in (p.name.lower() for p in people.values()):
                            people[f"name::{name}"] = TeamPerson(name=name, title=title, linkedin_url=None)
                        break
        log.info("Team crawl of %s: %d people across %d pages", base, len(people), len(crawled))
        return CrawlTeamResponse(people=list(people.values()), pages_crawled=crawled)
    finally:
        await page.close()


def _nearby_text(node) -> str:
    """Best-effort name from an anchor's parent text when the link itself is an icon."""
    parent = node.find_parent()
    if parent:
        t = parent.get_text(" ", strip=True)
        return t[:80]
    return ""
