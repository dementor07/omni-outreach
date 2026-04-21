"""
GitHub organisation member search.
Free source — uses GITHUB_TOKEN for higher rate limits (optional).
Without a token: 60 req/hr. With token: 5,000 req/hr.

Best for targeting developer-first companies (OSS, API companies, dev tools).
Cross-references public email from profiles.

GitHub REST docs: https://docs.github.com/en/rest
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

from .base import LeadSource, RawLead

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubSource(LeadSource):
    source_type = "github"
    display_name = "GitHub"
    description = (
        "Find developers and decision-makers at tech companies via their "
        "GitHub organisation membership. Free source — great for targeting "
        "developer-first companies."
    )

    @property
    def is_available(self) -> bool:
        # Always available — GitHub API works without a token (60 req/hr)
        # Token just raises the limit to 5K req/hr
        return True

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["orgs"],
            "properties": {
                "orgs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "GitHub Organisation Names",
                    "description": "e.g. ['vercel', 'supabase', 'stripe']",
                },
                "role": {
                    "type": "string",
                    "title": "Member Role",
                    "enum": ["all", "member", "admin"],
                    "default": "all",
                    "description": "Filter by org role",
                },
                "max_per_org": {
                    "type": "integer",
                    "title": "Max Members per Org",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 100,
                },
                "require_email": {
                    "type": "boolean",
                    "title": "Only Include Public Email",
                    "description": "Skip members without a public email address",
                    "default": False,
                },
                "require_company": {
                    "type": "boolean",
                    "title": "Only Include Members with Company Set",
                    "default": False,
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        github_token = getattr(settings, "github_token", None)
        orgs: list[str] = config.get("orgs", [])
        role: str = config.get("role", "all")
        max_per_org: int = config.get("max_per_org", 30)
        require_email: bool = config.get("require_email", False)
        require_company: bool = config.get("require_company", False)

        headers: dict = {"Accept": "application/vnd.github+json"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        all_leads: list[RawLead] = []

        async with httpx.AsyncClient(timeout=15) as client:
            for org in orgs:
                try:
                    members: list[dict] = []
                    page = 1
                    while len(members) < max_per_org:
                        per_page = min(100, max_per_org - len(members))
                        r = await client.get(
                            f"{GITHUB_API}/orgs/{org}/members",
                            headers=headers,
                            params={"role": role, "per_page": per_page, "page": page},
                        )
                        if r.status_code == 404:
                            log.warning(f"[github] org {org} not found")
                            break
                        r.raise_for_status()
                        batch = r.json()
                        if not batch:
                            break
                        members.extend(batch)
                        if len(batch) < per_page:
                            break
                        page += 1

                    log.info(f"[github] org {org}: {len(members)} members")

                    for member in members[:max_per_org]:
                        login = member.get("login", "")
                        try:
                            ur = await client.get(
                                f"{GITHUB_API}/users/{login}", headers=headers
                            )
                            ur.raise_for_status()
                            user = ur.json()
                        except Exception:
                            user = member

                        email = user.get("email") or ""
                        company = (user.get("company") or "").lstrip("@").strip()
                        name = user.get("name") or login
                        parts = name.split(" ", 1)

                        if require_email and not email:
                            continue
                        if require_company and not company:
                            continue

                        linkedin_url = None
                        blog = user.get("blog") or ""
                        if "linkedin.com/in/" in blog:
                            linkedin_url = blog

                        all_leads.append(RawLead(
                            first_name=parts[0] if parts else login,
                            last_name=parts[1] if len(parts) > 1 else "",
                            linkedin_url=linkedin_url,
                            email=email or None,
                            headline=user.get("bio", ""),
                            company=company or org,
                            extra={
                                "github_login": login,
                                "github_url": user.get("html_url"),
                                "github_followers": user.get("followers", 0),
                                "github_public_repos": user.get("public_repos", 0),
                                "github_org": org,
                                "location": user.get("location"),
                            },
                        ))

                except Exception as e:
                    log.error(f"[github] org {org}: {e}")

        log.info(f"[github] total: {len(all_leads)} leads")
        return all_leads
