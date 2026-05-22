"""Naukri lead source via Apify actor (legit / ToS-aware path).

Naukri's public SERP is fully client-rendered (Next.js) and the mobile JSON
API is reCAPTCHA-walled, so direct HTTP scraping returns zero results.
The legal-clean path is to delegate to a maintained Apify actor — Apify
holds the residential-proxy + captcha-solving infrastructure, and the legal
posture lives in their ToS, not yours.

This source uses Apify's run-sync API to invoke a Naukri actor and waits for
the dataset to populate. Default actor is ``epctex/naukri-scraper`` (public,
~$0.50 / 1000 leads at time of writing); operators can override via
``actor_id`` in the config to use any other Apify actor with a similar
output shape.

For the no-cost-but-legally-grey path, use ``NaukriStealthSource``
(undetected-chromedriver) instead.

Required setting: APIFY_API_KEY (already used by ``apify_jobs``).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

from .base import LeadSource, RawLead

log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
DEFAULT_ACTOR_ID = "epctex~naukri-scraper"


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


class NaukriSource(LeadSource):
    source_type = "naukri"
    display_name = "Naukri.com (Apify)"
    description = (
        "Pull India-focused candidate / job-post data from Naukri via a "
        "maintained Apify actor. ToS-friendly because the scraping risk "
        "lives with Apify. Requires APIFY_API_KEY."
    )

    @property
    def is_available(self) -> bool:
        return bool(getattr(settings, "apify_api_key", "") or "")

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
                },
                "experience_years_min": {
                    "type": "integer",
                    "title": "Minimum experience (years)",
                    "default": 5,
                    "minimum": 0,
                    "maximum": 30,
                },
                "max_results": {
                    "type": "integer",
                    "title": "Max results per run",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                },
                "actor_id": {
                    "type": "string",
                    "title": "Apify Actor ID",
                    "default": DEFAULT_ACTOR_ID,
                    "description": "Apify actor slug. Default scrapes Naukri job tuples.",
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        token: str = getattr(settings, "apify_api_key", "") or ""
        if not token:
            log.warning("[naukri] APIFY_API_KEY not configured")
            return []

        actor_id = (config.get("actor_id") or DEFAULT_ACTOR_ID).strip()
        keywords = (config.get("keywords") or "").strip()
        if not keywords:
            return []
        location = (config.get("location") or "India").strip()
        exp_min = int(config.get("experience_years_min", 5))
        max_results = int(config.get("max_results", 50))

        input_payload: dict[str, Any] = {
            "keyword": keywords,
            "location": location,
            "experience": exp_min,
            "maxItems": max_results,
        }

        url = f"{APIFY_BASE}/acts/{actor_id}/run-sync-get-dataset-items"
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                r = await client.post(
                    url,
                    params={"token": token},
                    json=input_payload,
                )
            if r.status_code >= 400:
                log.error("[naukri] Apify HTTP %s: %s", r.status_code, r.text[:300])
                return []
            items: list[dict] = r.json() or []
        except Exception as e:  # noqa: BLE001
            log.error("[naukri] Apify run failed: %s", e)
            return []

        return self._normalize(items)

    def _normalize(self, items: list[dict]) -> list[RawLead]:
        out: list[RawLead] = []
        for item in items:
            company = (
                item.get("companyName")
                or item.get("company")
                or (item.get("companyDetail") or {}).get("name")
                or ""
            )
            title = item.get("title") or item.get("designation") or ""
            location = item.get("location") or (
                ", ".join(p for p in (item.get("locations") or []) if p) or None
            )
            poster = (
                item.get("postedBy")
                or item.get("recruiterName")
                or item.get("hrName")
                or ""
            )
            first, last = _split_name(poster)
            if not company:
                continue
            out.append(
                RawLead(
                    first_name=first,
                    last_name=last,
                    headline=title,
                    company=company,
                    location=location,
                    job_url=item.get("url") or item.get("jdUrl"),
                    extra={
                        "naukri_job_id": item.get("jobId") or item.get("id"),
                        "naukri_posted_on": item.get("postedOn") or item.get("createdAt"),
                        "needs_person_enrichment": not poster,
                        "source_variant": "apify",
                    },
                )
            )
        log.info("[naukri] %s items → %s usable leads", len(items), len(out))
        return out
