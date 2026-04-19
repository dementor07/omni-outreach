"""
Apollo.io People Search + Organization Search.
Optional integration — requires APOLLO_API_KEY in settings.

Apollo API docs: https://apolloio.github.io/apollo-api-docs/
Rate limits: 10 req/s, credits per call (varies by tier).
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from .base import LeadSource, RawLead

log = logging.getLogger(__name__)

APOLLO_BASE = "https://api.apollo.io/api/v1"


class ApolloSource(LeadSource):
    source_type = "apollo"
    display_name = "Apollo.io"
    description = (
        "Search Apollo's database of 250M+ contacts. "
        "Filter by job title, company size, industry, location, and more."
    )

    @property
    def is_available(self) -> bool:
        return bool(getattr(settings, "apollo_api_key", None))

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["person_titles"],
            "properties": {
                "person_titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Job Titles",
                    "description": "e.g. ['CEO', 'Head of Marketing', 'CTO']",
                },
                "organization_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Target Domains",
                    "description": "Restrict to specific company domains (optional)",
                },
                "organization_industries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Industries",
                    "description": "e.g. ['Information Technology and Services', 'Software']",
                },
                "organization_num_employees_ranges": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Employee Count",
                    "description": "e.g. ['1,10', '11,50', '51,200']",
                },
                "person_locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Locations",
                    "description": "e.g. ['United States', 'United Kingdom']",
                },
                "per_page": {
                    "type": "integer",
                    "title": "Results per page",
                    "default": 25,
                    "minimum": 1,
                    "maximum": 100,
                },
                "max_pages": {
                    "type": "integer",
                    "title": "Max Pages",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        api_key = settings.apollo_api_key  # type: ignore[attr-defined]
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": api_key,
        }
        per_page = config.get("per_page", 25)
        max_pages = config.get("max_pages", 1)
        all_leads: list[RawLead] = []

        payload = {
            "per_page": per_page,
            "person_titles": config.get("person_titles", []),
        }
        if config.get("organization_domains"):
            payload["q_organization_domains"] = "\n".join(config["organization_domains"])
        if config.get("organization_industries"):
            payload["organization_industry_tag_ids"] = config["organization_industries"]
        if config.get("organization_num_employees_ranges"):
            payload["organization_num_employees_ranges"] = config["organization_num_employees_ranges"]
        if config.get("person_locations"):
            payload["person_locations"] = config["person_locations"]

        async with httpx.AsyncClient(timeout=30) as client:
            for page in range(1, max_pages + 1):
                try:
                    r = await client.post(
                        f"{APOLLO_BASE}/mixed_people/search",
                        headers=headers,
                        json={**payload, "page": page},
                    )
                    r.raise_for_status()
                    data = r.json()
                    people = data.get("people", [])
                    if not people:
                        break

                    for person in people:
                        org = person.get("organization") or {}
                        linkedin_url = person.get("linkedin_url") or ""
                        # Normalise LinkedIn URL
                        if linkedin_url and not linkedin_url.startswith("http"):
                            linkedin_url = f"https://www.linkedin.com/in/{linkedin_url}"

                        all_leads.append(RawLead(
                            first_name=person.get("first_name", ""),
                            last_name=person.get("last_name", ""),
                            linkedin_url=linkedin_url or None,
                            email=person.get("email"),
                            headline=person.get("title", ""),
                            company=org.get("name", "") or person.get("organization_name", ""),
                            company_linkedin_url=org.get("linkedin_url"),
                            extra={
                                "apollo_id": person.get("id"),
                                "city": person.get("city"),
                                "country": person.get("country"),
                                "seniority": person.get("seniority"),
                                "departments": person.get("departments", []),
                                "org_website": org.get("website_url"),
                                "org_employees": org.get("num_employees"),
                                "org_industry": org.get("industry"),
                            },
                        ))

                    log.info(f"[apollo] page {page} → {len(people)} results")
                    if len(people) < per_page:
                        break
                except Exception as e:
                    log.error(f"[apollo] search error page {page}: {e}")
                    break

        log.info(f"[apollo] total: {len(all_leads)} leads")
        return all_leads
