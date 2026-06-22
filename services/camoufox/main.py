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

import asyncio
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
# Serializes browser (re)creation. Without it, when 16 campaigns fire at once
# and find the browser dead, every concurrent /scrape races to relaunch — each
# overwrites the global mid-launch, leaving a clobbered half-initialised browser
# that 502s forever (the wedge we saw 2026-06-22). The lock makes recycle a
# single-flight: the first request relaunches, the rest await and reuse it.
_browser_lock = asyncio.Lock()


def _browser_alive(b) -> bool:
    """True only if the browser's Playwright transport is still connected.

    A Camoufox/Playwright browser whose underlying transport has died
    (``WriteUnixTransport closed`` / "handler is closed") still looks like an
    object but every ``new_page()`` raises. ``is_connected()`` is the honest
    liveness signal; treat any error reading it as dead."""
    if b is None:
        return False
    try:
        return bool(b.is_connected())
    except Exception:  # noqa: BLE001
        return False


async def get_browser():
    """Return a live persistent browser, recreating it if the transport died.

    Self-heals between requests: a dead browser is torn down and relaunched on
    demand (no manual container restart). Relaunch is single-flight under
    ``_browser_lock`` — concurrent callers that arrive while the browser is dead
    don't each spawn a competing instance (which clobbered the global and wedged
    the service); they queue and reuse the one the winner creates."""
    global _camoufox
    if _browser_alive(_camoufox):
        return _camoufox
    async with _browser_lock:
        # Re-check inside the lock: a prior holder may have already relaunched
        # while we waited (double-checked locking).
        if _browser_alive(_camoufox):
            return _camoufox
        if _camoufox is not None:
            log.warning("Camoufox browser transport is dead — recycling")
            try:
                await _camoufox.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001
                log.warning("error tearing down dead browser (ignored): %s", exc)
            _camoufox = None
        log.info("Starting persistent Camoufox browser")
        _camoufox = await AsyncCamoufox(headless=True).__aenter__()
    return _camoufox


def _is_dead_transport_error(exc: Exception) -> bool:
    """Whether an exception is the Camoufox/Playwright transport-death signature
    (browser handle closed mid-operation) vs. a genuine scrape error. Only the
    former is worth a one-shot retry on a fresh browser."""
    msg = str(exc).lower()
    return any(
        sig in msg
        for sig in ("handler is closed", "transport closed", "is closed", "browser closed",
                    "connection closed", "target closed", "browser has been closed")
    )


async def with_browser_retry(op, what: str):
    """Run ``op(browser)``; if the browser transport dies mid-operation, force a
    recycle and retry ONCE on a fresh browser. A transient mid-scrape death then
    self-heals inside the same request instead of surfacing as a failed scrape —
    'nothing should ever crash': the caller never sees the flake."""
    global _camoufox
    browser = await get_browser()
    try:
        return await op(browser)
    except Exception as exc:  # noqa: BLE001
        if not _is_dead_transport_error(exc):
            raise
        log.warning("%s: browser transport died mid-op — recycling and retrying once (%s)", what, exc)
        async with _browser_lock:
            # Drop the dead handle so get_browser() definitely relaunches.
            if _camoufox is not None and not _browser_alive(_camoufox):
                try:
                    await _camoufox.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
                _camoufox = None
        browser = await get_browser()
        return await op(browser)


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


class DirectoryRequest(BaseModel):
    url: str  # a directory category page, e.g. https://clutch.co/agencies/lead-generation
    max_results: int = 25


class DirectoryEntry(BaseModel):
    name: str
    url: str = ""
    description: str = ""


class DirectoryResponse(BaseModel):
    status: str
    data: list[DirectoryEntry]
    count: int


# ── Endpoints ───────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    # Passive liveness: report the real browser state without forcing a heal, so
    # a cheap 30s healthcheck doesn't launch browsers. The old unconditional 200
    # hid a dead transport (scrapes 502'd while health stayed green); the
    # ``browser`` field now tells the truth.
    alive = _browser_alive(_camoufox)
    return {"status": "ok", "service": "camoufox", "browser": "alive" if alive else "recycling"}


@app.get("/health/deep")
async def health_deep():
    """Active backstop healthcheck: ensure a LIVE browser, self-healing if dead.

    This is what Docker probes. A transient dead transport self-heals here (the
    same get_browser() recycle a scrape would do) and returns 200 — so a normal
    flake never trips a container restart. Only a browser that CANNOT be
    relaunched (the genuinely-wedged case) raises, fails the probe, and lets the
    orchestrator restart as the last resort. Belt (in-process heal) and braces
    (orchestrator restart) — the service cannot stay silently dead either way."""
    try:
        browser = await get_browser()
        if not _browser_alive(browser):
            raise RuntimeError("browser not alive after get_browser()")
        return {"status": "ok", "service": "camoufox", "browser": "alive"}
    except Exception as exc:  # noqa: BLE001
        log.error("deep health check failed — browser unrecoverable: %s", exc)
        raise HTTPException(status_code=503, detail=f"browser unrecoverable: {exc}") from exc


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest, x_internal_secret: str | None = Header(None)):
    _require_secret(x_internal_secret)
    try:
        raw_jobs = await with_browser_retry(
            lambda b: fetch_jobs(
                keywords=req.keywords, location=req.location, max_pages=req.max_pages, browser=b
            ),
            what="scrape",
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

    async def _run(browser):
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
        finally:
            try:
                await page.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("page.close() after search failed: %s", exc)

    try:
        return await with_browser_retry(_run, what="search")
    except Exception as exc:  # noqa: BLE001
        log.exception("Search failed for '%s'", req.query)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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

    async def _run(browser):
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
                except Exception as exc:  # noqa: BLE001
                    # A dead transport must bubble to with_browser_retry, not be
                    # swallowed as "this page failed" — re-raise that one case.
                    if _is_dead_transport_error(exc):
                        raise
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
            try:
                await page.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("page.close() after team crawl failed: %s", exc)

    return await with_browser_retry(_run, what="crawl-team")


@app.post("/scrape_directory", response_model=DirectoryResponse)
async def scrape_directory(req: DirectoryRequest, x_internal_secret: str | None = Header(None)):
    """Render a B2B agency directory category page (e.g. Clutch) and extract the
    listed companies' names + outbound website URLs.

    Clutch (and similar directories) render provider cards client-side, so a
    plain HTTP fetch sees an empty shell — Camoufox renders the full DOM. We
    target Clutch's provider-row markup first, then fall back to a tolerant
    heading + outbound-link heuristic so a CSS change doesn't zero the scrape."""
    _require_secret(x_internal_secret)

    async def _run(browser):
        page = await browser.new_page()
        try:
            log.info("Scraping directory: %s", req.url)
            await page.goto(req.url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)
            # Trigger lazy-loaded cards by scrolling the page a few times.
            for _ in range(4):
                await page.mouse.wheel(0, 4000)
                await page.wait_for_timeout(800)
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            entries: dict[str, DirectoryEntry] = {}

            # 1. Clutch provider rows (primary path).
            for li in soup.select("li.provider-row, li.provider, div.provider-info"):
                title_link = li.select_one(".provider__title-link, a.company_title, h3 a, h3")
                if not title_link:
                    continue
                name = title_link.get_text(strip=True)
                website = ""
                site = li.select_one('a.website-link__item, a[data-link-type="profile-visit-website"], a[rel*="nofollow"]')
                if site and site.get("href"):
                    website = str(site.get("href")).split("?")[0]
                if name and len(name) <= 120:
                    entries.setdefault(name.lower(), DirectoryEntry(name=name, url=website))

            # 2. Fallback heuristic — outbound links whose anchor text reads like a
            #    company name, when the provider-row markup didn't match.
            if not entries:
                for a in soup.select("a[href]"):
                    href = str(a.get("href", ""))
                    text = a.get_text(strip=True)
                    if (
                        href.startswith("http")
                        and "clutch.co" not in href
                        and 2 <= len(text) <= 60
                        and " " not in href.split("://", 1)[-1].split("/", 1)[0]
                    ):
                        entries.setdefault(text.lower(), DirectoryEntry(name=text, url=href.split("?")[0]))

            data = list(entries.values())[: req.max_results]
            log.info("Directory scrape: %d agencies from %s", len(data), req.url)
            return DirectoryResponse(status="success", data=data, count=len(data))
        finally:
            try:
                await page.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("page.close() after directory scrape failed: %s", exc)

    try:
        return await with_browser_retry(_run, what="scrape_directory")
    except Exception as exc:  # noqa: BLE001
        log.exception("Directory scrape failed for %s", req.url)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _nearby_text(node) -> str:
    """Best-effort name from an anchor's parent text when the link itself is an icon."""
    parent = node.find_parent()
    if parent:
        t = parent.get_text(" ", strip=True)
        return t[:80]
    return ""
