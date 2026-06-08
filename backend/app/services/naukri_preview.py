"""Synchronous Naukri scrape preview.

The production path (``source.naukri`` node) is async: it emits an intent onto
the bus, the Rust muscle scrapes via Camoufox, and the company list lands on a
lead's ``custom_fields`` for ``flow.for_each``. That's right for a running
workflow but useless for an operator who just wants to *see what a keyword
returns* before wiring a workflow.

This module is that missing surface: it calls the Camoufox ``/scrape`` endpoint
directly and returns the deduped company list synchronously — no bus, no lead,
no persistence. The dedup + row shape mirror the Rust ``extract_companies``
(backend-rust/src/handlers/naukri.rs) so a preview matches what a real run
would produce, and it reuses ``clean_company_name`` so dedup is consistent with
the knowledge-graph resolver.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.company_kg import clean_company_name

log = logging.getLogger(__name__)

# Naukri renders multiple pages in a headless browser — far slower than a REST
# call. Match the Rust client's generous timeout (naukri.rs: 180s).
_TIMEOUT = httpx.Timeout(180.0, connect=10.0)


@dataclass
class PreviewCompany:
    company_name: str
    title: str
    role_count: int
    location: str
    experience: str
    source_url: str


@dataclass
class PreviewResult:
    keyword: str
    jobs_returned: int
    companies: list[PreviewCompany]


class PreviewError(RuntimeError):
    """Camoufox was unreachable or returned an error. Carries an HTTP-ish code
    so the router can map it to a sensible status."""

    def __init__(self, message: str, *, status: int = 502):
        super().__init__(message)
        self.status = status


async def preview_naukri(
    keyword: str, *, location: str | None = None, max_pages: int = 1
) -> PreviewResult:
    """Scrape Naukri for one keyword and return the deduped companies.

    Synchronous w.r.t. the caller (awaits the Camoufox round-trip). Raises
    ``PreviewError`` on transport / upstream failure so the route never leaks a
    raw httpx exception."""
    keyword = (keyword or "").strip()
    if not keyword:
        raise PreviewError("keyword is required", status=400)
    max_pages = max(1, min(int(max_pages), 50))

    url = f"{settings.camoufox_base_url.rstrip('/')}/scrape"
    headers = {}
    if settings.camoufox_shared_secret:
        headers["X-Internal-Secret"] = settings.camoufox_shared_secret
    body = {"keywords": keyword, "location": location, "max_pages": max_pages}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("camoufox preview request failed: %s", exc)
        raise PreviewError(f"camoufox unreachable: {exc}", status=502) from exc

    if resp.status_code >= 400:
        raise PreviewError(
            f"camoufox returned HTTP {resp.status_code}", status=502 if resp.status_code >= 500 else 400
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise PreviewError("camoufox returned non-JSON", status=502) from exc

    jobs = data.get("data") or []
    companies = _extract_companies(jobs)
    return PreviewResult(keyword=keyword, jobs_returned=len(jobs), companies=companies)


def _extract_companies(jobs: list[dict]) -> list[PreviewCompany]:
    """Dedupe jobs by (cleaned) company name, carrying role_count. Mirrors the
    Rust ``extract_companies`` but runs the name through ``clean_company_name``
    first so the preview dedups exactly as the KG resolver later will."""
    # role_count keyed by the cleaned, lowercased name (multiple_roles signal).
    counts: Counter[str] = Counter()
    for job in jobs:
        name = clean_company_name(job.get("company_name") or "")
        if name and (job.get("title") or "").strip():
            counts[name.lower()] += 1

    seen: set[str] = set()
    out: list[PreviewCompany] = []
    for job in jobs:
        name = clean_company_name(job.get("company_name") or "")
        title = (job.get("title") or "").strip()
        key = name.lower()
        if not name or not title or key in seen:
            continue
        seen.add(key)
        out.append(
            PreviewCompany(
                company_name=name,
                title=title,
                role_count=counts.get(key, 1),
                location=job.get("location") or "",
                experience=job.get("experience") or "",
                source_url=job.get("url") or job.get("source_url") or "",
            )
        )
    return out
