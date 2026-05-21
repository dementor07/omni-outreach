"""Naukri.com lead source.

Scrapes the Naukri Recruiter "Resdex" public search results page for profiles
matching an operator-supplied query. Naukri exposes a paginated HTML SERP at
https://www.naukri.com/<slug>-jobs that includes the candidate's display name,
designation, current company, location and (for many profiles) a profile URL
that resolves to a public Naukri profile.

This source only emits leads when at least one identifier is recoverable
(linkedin_url, email, or phone). For most Naukri results the public page does
not include email/phone — those leads will leave the source with just name +
company + headline and get enriched downstream by Apollo / Hunter / ProxyCurl.

No API key required. We honour Naukri's robots.txt — search SERP is allowed,
profile detail pages aren't, so we never follow individual profile links.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

import httpx

from .base import LeadSource, RawLead

log = logging.getLogger(__name__)

NAUKRI_BASE = "https://www.naukri.com"
# A realistic UA prevents Naukri's bot wall from returning empty markup.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


class NaukriSource(LeadSource):
    source_type = "naukri"
    display_name = "Naukri.com"
    description = (
        "Scrape Naukri.com search results for India-based professionals. "
        "Returns name, designation, company, location. Pair with Hunter/Apollo "
        "downstream to recover email + phone."
    )

    @property
    def is_available(self) -> bool:
        # No API key — always available. Operators can still throttle via
        # max_pages in the config.
        return True

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["keywords"],
            "properties": {
                "keywords": {
                    "type": "string",
                    "title": "Job Title / Keywords",
                    "description": "e.g. 'Marketing Director', 'Head of Growth Agency'",
                },
                "location": {
                    "type": "string",
                    "title": "Location",
                    "default": "India",
                    "description": "City or country. Naukri is India-centric; leave default for nationwide.",
                },
                "experience_years_min": {
                    "type": "integer",
                    "title": "Minimum experience (years)",
                    "default": 5,
                    "minimum": 0,
                    "maximum": 30,
                },
                "max_pages": {
                    "type": "integer",
                    "title": "Max Pages",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        keywords: str = (config.get("keywords") or "").strip()
        if not keywords:
            return []
        location: str = (config.get("location") or "India").strip()
        exp_min = int(config.get("experience_years_min", 5))
        max_pages = int(config.get("max_pages", 3))

        slug = _slug(keywords)
        all_leads: list[RawLead] = []
        seen_keys: set[str] = set()

        async with httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
        ) as client:
            for page in range(1, max_pages + 1):
                # Naukri's public job-search URL pattern. We deliberately use
                # the job-search SERP (which lists employer-side designations
                # plus the hiring company) rather than the candidate Resdex
                # which requires a paid recruiter login.
                url = (
                    f"{NAUKRI_BASE}/{slug}-jobs"
                    f"?k={quote_plus(keywords)}"
                    f"&l={quote_plus(location)}"
                    f"&experience={exp_min}"
                    f"&pageNo={page}"
                )
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        log.warning("[naukri] page %s HTTP %s", page, r.status_code)
                        break
                    leads_on_page = self._parse_serp(r.text)
                except Exception as e:  # noqa: BLE001
                    log.error("[naukri] page %s failed: %s", page, e)
                    break

                fresh = 0
                for lead in leads_on_page:
                    key = (lead.company or "").lower() + "|" + (lead.first_name + lead.last_name).lower()
                    if not key.strip("|") or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    all_leads.append(lead)
                    fresh += 1

                log.info("[naukri] page %s → %s parsed (%s fresh)", page, len(leads_on_page), fresh)
                if not leads_on_page:
                    break

        log.info("[naukri] total: %s leads", len(all_leads))
        return all_leads

    # ── HTML parsing ─────────────────────────────────────────────────────────

    def _parse_serp(self, html: str) -> list[RawLead]:
        """Parse a Naukri SERP HTML page.

        Naukri's job tuples carry the hiring contact's title + the company.
        The structure changes occasionally; we read the public JSON-LD blob
        first (most stable) and fall back to the article-tuple parser.
        """
        out: list[RawLead] = []
        try:
            from bs4 import BeautifulSoup  # local import — keeps module loadable without bs4
            soup = BeautifulSoup(html, "html.parser")
        except ImportError:
            log.error("[naukri] beautifulsoup4 not installed; install with `pip install beautifulsoup4`")
            return out
        except Exception as e:  # noqa: BLE001
            log.error("[naukri] soup failed: %s", e)
            return out

        # Fast path: JobPosting JSON-LD nodes
        import json as _json

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = _json.loads(script.string or "{}")
            except (_json.JSONDecodeError, TypeError):
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                    continue
                org = item.get("hiringOrganization") or {}
                company = org.get("name") or ""
                title = item.get("title") or ""
                location = self._extract_location(item.get("jobLocation"))
                # JSON-LD rarely carries a named contact — emit a company-only
                # placeholder lead so the enrichment leg can fill in a real
                # human via Apollo's org → people lookup downstream.
                if not company:
                    continue
                out.append(
                    RawLead(
                        first_name="",
                        last_name="",
                        headline=title,
                        company=company,
                        location=location,
                        extra={
                            "naukri_role_url": item.get("url"),
                            "naukri_posted_at": item.get("datePosted"),
                            "needs_person_enrichment": True,
                        },
                    )
                )

        # Slow path: tuple-level scrape for "Posted by <Name>" attributions.
        for tuple_node in soup.select("article.jobTuple, div.srp-jobtuple-wrapper, div.jobTuple"):
            company = self._first_text(tuple_node.select_one("a.subTitle, span.companyName, a.comp-name"))
            title = self._first_text(tuple_node.select_one("a.title, a.title-link"))
            location = self._first_text(tuple_node.select_one("li.location, span.locWdth"))
            poster_name = self._first_text(tuple_node.select_one("span.posted-by, span.recruiter-name"))
            if not company:
                continue
            first, last = _split_name(poster_name)
            out.append(
                RawLead(
                    first_name=first,
                    last_name=last,
                    headline=title,
                    company=company,
                    location=location or None,
                    extra={
                        "naukri_role_url": self._href(tuple_node.select_one("a.title")),
                        "needs_person_enrichment": not poster_name,
                    },
                )
            )
        return out

    @staticmethod
    def _first_text(node) -> str:
        return node.get_text(" ", strip=True) if node else ""

    @staticmethod
    def _href(node) -> str | None:
        return node.get("href") if node else None

    @staticmethod
    def _extract_location(loc) -> str | None:
        if isinstance(loc, list):
            loc = loc[0] if loc else None
        if not isinstance(loc, dict):
            return None
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
            return ", ".join(p for p in parts if p) or None
        return None
