"""
Hunter.io Domain Search.
Optional integration — requires HUNTER_API_KEY in settings.

Hunter API docs: https://hunter.io/api-documentation/v2
Free tier: 50 searches/month. Paid: $34/mo (2K/mo) upward.
Rate limit: 3 req/s (free), higher on paid.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from .base import LeadSource, RawLead

log = logging.getLogger(__name__)

HUNTER_BASE = "https://api.hunter.io/v2"


class HunterSource(LeadSource):
    source_type = "hunter"
    display_name = "Hunter.io"
    description = (
        "Find verified work emails at any company domain. "
        "Best-in-class email accuracy (98%+). Great for account-based prospecting."
    )

    @property
    def is_available(self) -> bool:
        return bool(getattr(settings, "hunter_api_key", None))

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["domains"],
            "properties": {
                "domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Company Domains",
                    "description": "e.g. ['stripe.com', 'vercel.com']",
                },
                "target_roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Role Filter (optional)",
                    "description": "Only include contacts whose seniority or title matches",
                    "default": [],
                },
                "seniority": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["junior", "senior", "executive"],
                    },
                    "title": "Seniority Filter",
                    "default": ["senior", "executive"],
                },
                "department": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "executive", "it", "finance", "management",
                            "sales", "legal", "support", "hr", "marketing",
                            "communication", "education", "design", "health",
                            "operations",
                        ],
                    },
                    "title": "Department Filter",
                    "default": ["executive", "management", "sales", "marketing"],
                },
                "limit": {
                    "type": "integer",
                    "title": "Results per domain",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        api_key = settings.hunter_api_key  # type: ignore[attr-defined]
        domains: list[str] = config.get("domains", [])
        seniority_filter: list[str] = config.get("seniority", [])
        dept_filter: list[str] = config.get("department", [])
        limit: int = config.get("limit", 10)
        role_keywords: list[str] = [r.lower() for r in config.get("target_roles", [])]

        all_leads: list[RawLead] = []

        async with httpx.AsyncClient(timeout=20) as client:
            for domain in domains:
                try:
                    params: dict = {"domain": domain, "api_key": api_key, "limit": limit}
                    if seniority_filter:
                        params["seniority"] = ",".join(seniority_filter)
                    if dept_filter:
                        params["department"] = ",".join(dept_filter)

                    r = await client.get(f"{HUNTER_BASE}/domain-search", params=params)
                    r.raise_for_status()
                    data = r.json().get("data", {})
                    emails = data.get("emails", [])
                    org_name = data.get("organization") or domain

                    for contact in emails:
                        first = contact.get("first_name", "")
                        last = contact.get("last_name", "")
                        email = contact.get("value", "")
                        position = contact.get("position", "")
                        linkedin = contact.get("linkedin", "")
                        twitter = contact.get("twitter", "")

                        # Optional role keyword filter
                        if role_keywords and not any(k in position.lower() for k in role_keywords):
                            continue

                        all_leads.append(RawLead(
                            first_name=first,
                            last_name=last,
                            linkedin_url=linkedin or None,
                            email=email,
                            headline=position,
                            company=org_name,
                            extra={
                                "hunter_confidence": contact.get("confidence"),
                                "hunter_type": contact.get("type"),
                                "hunter_seniority": contact.get("seniority"),
                                "hunter_department": contact.get("department"),
                                "twitter": twitter,
                                "domain": domain,
                            },
                        ))

                    log.info(f"[hunter] {domain} → {len(emails)} contacts")
                except Exception as e:
                    log.error(f"[hunter] {domain}: {e}")

        log.info(f"[hunter] total: {len(all_leads)} leads")
        return all_leads
