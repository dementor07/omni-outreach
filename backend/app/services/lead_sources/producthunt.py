"""ProductHunt lead source.

Pulls makers from ProductHunt via the public GraphQL API
(https://api.producthunt.com/v2/api/graphql). Each Post on ProductHunt has
a ``makers`` collection — the founders / engineers / marketers who shipped
the product. We extract those people as leads.

A maker's public profile reliably surfaces:
  - name, username, profile URL (producthunt.com/@username)
  - headline (bio)
  - LinkedIn URL (set in their social links by ~70% of makers)
  - Twitter handle
  - location
  - their associated company (the Post.makerOf)

Email / phone are never returned by ProductHunt — those gaps get filled
downstream by Apollo / Hunter / ProxyCurl enrichment nodes.

Requires PRODUCTHUNT_TOKEN (developer token, free) in settings.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

from .base import LeadSource, RawLead

log = logging.getLogger(__name__)

PH_API = "https://api.producthunt.com/v2/api/graphql"

# GraphQL query — pull recent posts in a topic with their makers expanded.
# Topics are slugs like "marketing", "saas", "advertising", "growth-hacking".
_QUERY = """
query ($topic: String!, $first: Int!, $after: String) {
  posts(topic: $topic, first: $first, after: $after, order: NEWEST) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        slug
        tagline
        url
        votesCount
        makers {
          id
          name
          username
          headline
          twitterUsername
          websiteUrl
          profileImage
          url
        }
      }
    }
  }
}
"""


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _maybe_linkedin(url: str | None) -> str | None:
    if not url:
        return None
    if "linkedin.com/in/" in url:
        return url.split("?")[0].rstrip("/")
    return None


class ProductHuntSource(LeadSource):
    source_type = "producthunt"
    display_name = "ProductHunt"
    description = (
        "Pull makers (founders/marketers/engineers) from ProductHunt posts in "
        "operator-chosen topics. Returns name, headline, LinkedIn URL when "
        "set publicly, and profile URL. Pair with Apollo/Hunter for email."
    )

    @property
    def is_available(self) -> bool:
        return bool(getattr(settings, "producthunt_token", "") or "")

    def config_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["topic"],
            "properties": {
                "topic": {
                    "type": "string",
                    "title": "Topic slug",
                    "default": "marketing",
                    "description": (
                        "ProductHunt topic, e.g. 'marketing', 'saas', "
                        "'advertising', 'growth-hacking', 'sales'."
                    ),
                },
                "per_page": {
                    "type": "integer",
                    "title": "Posts per page",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
                "max_pages": {
                    "type": "integer",
                    "title": "Max pages",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 10,
                },
                "min_votes": {
                    "type": "integer",
                    "title": "Minimum vote count",
                    "default": 50,
                    "description": "Skip posts under this vote threshold (filters out noise).",
                },
            },
        }

    async def search(self, config: dict) -> list[RawLead]:
        token: str = getattr(settings, "producthunt_token", "") or ""
        if not token:
            log.warning("[producthunt] PRODUCTHUNT_TOKEN not configured")
            return []

        topic: str = (config.get("topic") or "marketing").strip()
        per_page: int = int(config.get("per_page", 20))
        max_pages: int = int(config.get("max_pages", 3))
        min_votes: int = int(config.get("min_votes", 50))

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        all_leads: list[RawLead] = []
        seen_makers: set[str] = set()
        cursor: str | None = None

        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            for page in range(1, max_pages + 1):
                variables: dict[str, Any] = {"topic": topic, "first": per_page}
                if cursor:
                    variables["after"] = cursor
                try:
                    r = await client.post(PH_API, json={"query": _QUERY, "variables": variables})
                    if r.status_code != 200:
                        log.warning("[producthunt] HTTP %s on page %s: %s", r.status_code, page, r.text[:200])
                        break
                    payload = r.json()
                except Exception as e:  # noqa: BLE001
                    log.error("[producthunt] page %s failed: %s", page, e)
                    break

                if payload.get("errors"):
                    log.error("[producthunt] GraphQL errors: %s", payload["errors"])
                    break

                posts_root = ((payload.get("data") or {}).get("posts") or {})
                edges = posts_root.get("edges") or []
                if not edges:
                    break

                fresh = 0
                for edge in edges:
                    post = (edge or {}).get("node") or {}
                    if int(post.get("votesCount") or 0) < min_votes:
                        continue
                    company = post.get("name") or ""
                    company_url = post.get("url") or ""
                    for maker in post.get("makers") or []:
                        maker_id = maker.get("id") or maker.get("username") or ""
                        if not maker_id or maker_id in seen_makers:
                            continue
                        seen_makers.add(maker_id)
                        first, last = _split_name(maker.get("name") or "")
                        linkedin_url = _maybe_linkedin(maker.get("websiteUrl"))
                        all_leads.append(
                            RawLead(
                                first_name=first,
                                last_name=last,
                                linkedin_url=linkedin_url,
                                headline=maker.get("headline") or "",
                                company=company,
                                job_url=maker.get("url"),
                                extra={
                                    "producthunt_id": maker.get("id"),
                                    "producthunt_username": maker.get("username"),
                                    "producthunt_post_slug": post.get("slug"),
                                    "producthunt_post_url": company_url,
                                    "twitter_username": maker.get("twitterUsername"),
                                    "website_url": maker.get("websiteUrl"),
                                    "post_votes": post.get("votesCount"),
                                    "needs_person_enrichment": not linkedin_url,
                                },
                            )
                        )
                        fresh += 1

                log.info("[producthunt] page %s topic=%s posts=%s fresh_makers=%s", page, topic, len(edges), fresh)

                page_info = posts_root.get("pageInfo") or {}
                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")
                if not cursor:
                    break

        log.info("[producthunt] total: %s makers", len(all_leads))
        return all_leads
