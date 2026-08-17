"""Slug discovery runner — one CDX extraction per (platform, crawl).

Ports Allen's pipeline/run.py: discover slugs for a platform from a CommonCrawl
crawl, filter via the platform's validator, persist new slugs + crawl history to
omni_ats_slugs / omni_ats_crawls (set-union dedup, idempotent crawl skip). The
CDX download is blocking/CPU-ish, so it runs in a thread so it never blocks the
worker's event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.services.ats import cdx, store
from app.services.ats.plugins import ATSPlatform, get_platform

log = logging.getLogger("ats.discover")


def _discover_blocking(platform: ATSPlatform, crawl: str) -> list[str]:
    """Synchronous CDX extraction (download + parse) — run in a thread."""
    raw = cdx.discover_slugs(crawl, platform.surt_prefix, platform.extract_slugs_from_url)
    return [s for s in raw if platform.is_valid_slug(s)]


async def discover_platform(platform_name: str, crawl: str) -> dict:
    """Discover + persist slugs for one platform/crawl. Idempotent per crawl."""
    platform = get_platform(platform_name)
    if not platform:
        raise ValueError(f"unknown ATS platform: {platform_name}")

    if await store.crawl_already_done(platform_name, crawl):
        log.info("[ats] %s @ %s already processed; skipping", platform_name, crawl)
        return {"platform": platform_name, "crawl": crawl, "skipped": True}

    log.info("[ats] discovering %s slugs from %s …", platform_name, crawl)
    start = time.monotonic()
    slugs = await asyncio.to_thread(_discover_blocking, platform, crawl)
    duration = time.monotonic() - start

    new_count = await store.upsert_slugs(platform_name, slugs, crawl=crawl)
    await store.record_crawl(platform_name, crawl, len(slugs), new_count, duration)
    log.info(
        "[ats] %s @ %s: %d slugs (%d new) in %.1fs",
        platform_name, crawl, len(slugs), new_count, duration,
    )
    return {
        "platform": platform_name,
        "crawl": crawl,
        "slugs_found": len(slugs),
        "new_slugs": new_count,
        "duration_seconds": round(duration, 1),
        "skipped": False,
    }
