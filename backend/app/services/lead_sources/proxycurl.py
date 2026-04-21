"""
ProxyCurl LinkedIn profile + company employee lookup.
Optional integration — requires PROXYCURL_API_KEY in settings.

ProxyCurl API docs: https://nubela.co/proxycurl/docs
Credits: 1 credit per person profile, 3 per company employee list.
Free tier: 10 credits/month. Paid: $49/mo (2.5K credits) upward.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

from .base import LeadSource, RawLead

log = logging.getLogger(__name__)

PROXYCURL_BASE = "https://nubela.co/proxycurl/api"


class ProxyCurlSource(LeadSource):
    source_type = "proxycurl"
    display_name = "ProxyCurl (LinkedIn)"
    description = (
        "Enrich LinkedIn company pages to extract employee profiles. "
        "Best for LinkedIn-sourced contact data with full work history."
    )

    @property
    def is_available(self) -> bool:
        return bool(getattr(settings, "proxycurl_api_key", None))

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["company_linkedin_urls"],
            "properties": {
                "company_linkedin_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Company LinkedIn URLs",
                    "description": "e.g. ['https://www.linkedin.com/company/stripe']",
                },
                "role_search": {
                    "type": "string",
                    "title": "Role Keyword",
                    "description": "Filter employees by role keyword (e.g. 'marketing', 'engineering')",
                    "default": "",
                },
                "max_per_company": {
                    "type": "integer",
                    "title": "Max Employees per Company",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
                "enrich_profiles": {
                    "type": "boolean",
                    "title": "Enrich Individual Profiles",
                    "description": "Fetch full profile for each employee (uses more credits)",
                    "default": False,
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        api_key = settings.proxycurl_api_key  # type: ignore[attr-defined]
        company_urls: list[str] = config.get("company_linkedin_urls", [])
        role_search: str = config.get("role_search", "")
        max_per_company: int = config.get("max_per_company", 10)
        enrich_profiles: bool = config.get("enrich_profiles", False)
        headers = {"Authorization": f"Bearer {api_key}"}
        all_leads: list[RawLead] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for company_url in company_urls:
                try:
                    # Fetch company employees
                    params: dict = {
                        "linkedin_company_profile_url": company_url,
                        "page_size": max_per_company,
                    }
                    if role_search:
                        params["keyword_regex"] = role_search

                    r = await client.get(
                        f"{PROXYCURL_BASE}/linkedin/company/employees",
                        headers=headers,
                        params=params,
                    )
                    r.raise_for_status()
                    data = r.json()
                    employees = data.get("employees", [])
                    log.info(f"[proxycurl] {company_url} → {len(employees)} employees")

                    for emp in employees:
                        profile_url = emp.get("profile_url") or emp.get("linkedin_profile_url", "")
                        name = emp.get("name", "")
                        parts = name.split(" ", 1)
                        first = parts[0] if parts else ""
                        last = parts[1] if len(parts) > 1 else ""

                        if enrich_profiles and profile_url:
                            # Full profile enrichment (costs 1 credit per profile)
                            try:
                                pr = await client.get(
                                    f"{PROXYCURL_BASE}/v2/linkedin",
                                    headers=headers,
                                    params={"url": profile_url, "extra": "include"},
                                )
                                pr.raise_for_status()
                                p = pr.json()
                                first = p.get("first_name", first)
                                last = p.get("last_name", last)
                                headline = p.get("headline", "")
                                email = p.get("personal_emails", [None])[0] or p.get("work_email")
                                all_leads.append(RawLead(
                                    first_name=first,
                                    last_name=last,
                                    linkedin_url=profile_url,
                                    email=email,
                                    headline=headline,
                                    company_linkedin_url=company_url,
                                    extra={
                                        "proxycurl_city": p.get("city"),
                                        "proxycurl_country": p.get("country_full_name"),
                                        "proxycurl_connections": p.get("connections"),
                                    },
                                ))
                                continue
                            except Exception as e:
                                log.warning(f"[proxycurl] profile enrich {profile_url}: {e}")

                        # Fallback: just the employee stub from the company list
                        all_leads.append(RawLead(
                            first_name=first,
                            last_name=last,
                            linkedin_url=profile_url or None,
                            headline=emp.get("title", ""),
                            company_linkedin_url=company_url,
                            extra={"proxycurl_summary": emp.get("summary")},
                        ))

                except Exception as e:
                    log.error(f"[proxycurl] {company_url}: {e}")

        log.info(f"[proxycurl] total: {len(all_leads)} leads")
        return all_leads

    @property
    def supports_enrichment(self) -> bool:
        return True

    async def enrich(self, lead_data: dict) -> RawLead:
        """ProxyCurl profile lookup by linkedin_url."""
        api_key = settings.proxycurl_api_key  # type: ignore[attr-defined]
        profile_url = lead_data.get("linkedin_url")
        if not profile_url:
            raise ValueError("ProxyCurl enrichment requires linkedin_url on lead")
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{PROXYCURL_BASE}/v2/linkedin",
                headers=headers,
                params={"url": profile_url, "extra": "include"},
            )
            r.raise_for_status()
            p = r.json() or {}
        email = (p.get("personal_emails") or [None])[0] or p.get("work_email")
        return RawLead(
            first_name=p.get("first_name") or lead_data.get("first_name", ""),
            last_name=p.get("last_name") or lead_data.get("last_name", ""),
            linkedin_url=profile_url,
            email=email,
            headline=p.get("headline", ""),
            company=(p.get("experiences") or [{}])[0].get("company", "") if p.get("experiences") else "",
            extra={
                "proxycurl_city": p.get("city"),
                "proxycurl_country": p.get("country_full_name"),
            },
        )
