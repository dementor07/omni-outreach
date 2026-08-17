"""Product Hunt lead source node (PH-001).

Pulls recent Product Hunt posts via the PH GraphQL API and emits one
``contact.created`` event per MAKER, with the product as their company — the
in-process source pattern (mirrors ``source.csv`` / ``source.sheets``).

This is what makes the Product Hunt OAuth flow (``routers/oauth_producthunt.py``)
a real capability rather than a dead-end: connecting a PH account stored an
access token, but nothing consumed it. The token is per-operator;
``oauth_producthunt.resolve_user_access_token`` already resolves the
workspace-agnostic "most-recently-connected operator" token AND transparently
refreshes it, so a source node just asks for an access token and queries.

Makers are real people (name + sometimes twitter/website), which flow straight
into the existing CRM/screening pipeline as contacts. A maker with neither a
LinkedIn URL nor an email is still useful (name + company + twitter), so we
synthesise a stable pseudo-identity from the PH maker id to dedup re-pulls
without colliding across people.
"""

from __future__ import annotations

import logging
import uuid

import httpx
from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)
from app.routers.oauth_producthunt import PH_GRAPHQL_URL, resolve_user_access_token

log = logging.getLogger(__name__)

# Deterministic id namespace for PH makers (distinct from the CRM contact
# namespace — PH ids are not LinkedIn/email natural keys, so we never want them
# to collide with a discovered/CRM person; re-pulling the same maker upserts).
_PH_MAKER_NS = uuid.UUID("b1e2c3d4-5f6a-4b7c-8d9e-0a1b2c3d4e5f")

# GraphQL: most recent posts, each with its makers. `featuredAt` ordering gives
# the freshest launches first; the API caps `first` at 20 per page.
_POSTS_QUERY = """
query RecentPosts($first: Int!) {
  posts(first: $first, order: NEWEST) {
    edges {
      node {
        id
        name
        tagline
        website
        url
        makers {
          id
          name
          username
          twitterUsername
          websiteUrl
        }
      }
    }
  }
}
""".strip()


class ProductHuntSourceConfig(BaseModel):
    max_posts: int = Field(
        20, ge=1, le=20, description="How many recent Product Hunt launches to pull (max 20 per the PH API)"
    )
    timeout_seconds: int = Field(30, ge=1, le=120, description="HTTP timeout for the PH GraphQL call")


MANIFEST = NodeManifest(
    type="source.producthunt",
    category=NodeCategory.SOURCE,
    summary="Discover makers from recent Product Hunt launches (one maker = one contact)",
    config_schema=ProductHuntSourceConfig,
    output_handles=(
        NodeHandle("default", "Emitted once per successful pull, with the maker count in telemetry"),
        NodeHandle("empty", "Emitted when no makers were found"),
        NodeHandle("on_error", "Emitted when Product Hunt is not connected or the GraphQL call failed"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="producthunt",
)


def _maker_contact_id(workspace_id: str, maker_id: str) -> str:
    return str(uuid.uuid5(_PH_MAKER_NS, f"{workspace_id}|ph:{maker_id}"))


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ProductHuntSourceConfig(**ctx.config)

    access_token = await resolve_user_access_token()
    if not access_token:
        return NodeResult(
            handle="on_error",
            error="PRODUCTHUNT_NOT_CONNECTED — connect Product Hunt in Settings → Integrations",
        )

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            resp = await client.post(
                PH_GRAPHQL_URL,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={"query": _POSTS_QUERY, "variables": {"first": cfg.max_posts}},
            )
    except Exception as e:  # noqa: BLE001
        log.warning("[producthunt] GraphQL fetch failed: %s", e)
        return NodeResult(handle="on_error", error="PRODUCTHUNT_NETWORK_ERROR")

    if resp.status_code >= 400:
        return NodeResult(handle="on_error", error=f"PRODUCTHUNT_HTTP_{resp.status_code}")

    body = resp.json() or {}
    if body.get("errors"):
        log.warning("[producthunt] GraphQL errors: %s", str(body["errors"])[:200])
        return NodeResult(handle="on_error", error="PRODUCTHUNT_GRAPHQL_ERROR")

    edges = (((body.get("data") or {}).get("posts") or {}).get("edges")) or []
    events: list[dict] = []
    seen: set[str] = set()
    for edge in edges:
        post = edge.get("node") or {}
        product_name = (post.get("name") or "").strip() or None
        product_site = (post.get("website") or "").strip() or None
        for maker in post.get("makers") or []:
            maker_id = str(maker.get("id") or "").strip()
            name = (maker.get("name") or "").strip()
            if not maker_id or not name:
                continue
            contact_id = _maker_contact_id(ctx.workspace_id, maker_id)
            if contact_id in seen:  # a maker on multiple posts → one contact
                continue
            seen.add(contact_id)
            first, _, last = name.partition(" ")
            twitter = (maker.get("twitterUsername") or "").strip() or None
            events.append(
                {
                    "event_type": "contact.created",
                    "entity_type": "contact",
                    "entity_id": contact_id,
                    "payload": {
                        "first_name": first or None,
                        "last_name": last or None,
                        "company": product_name,
                        "headline": f"Maker of {product_name}" if product_name else None,
                        "source": "producthunt",
                        "custom_fields": {
                            "producthunt_username": (maker.get("username") or "").strip() or None,
                            "twitter_username": twitter,
                            "maker_website": (maker.get("websiteUrl") or "").strip() or None,
                            "product_website": product_site,
                            "product_url": (post.get("url") or "").strip() or None,
                        },
                    },
                }
            )

    handle = "default" if events else "empty"
    return NodeResult(handle=handle, events=events, telemetry={"makers_added": len(events)})


register(MANIFEST, execute)
