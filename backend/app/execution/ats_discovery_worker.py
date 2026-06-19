"""ATS discovery worker — refresh company slugs from CommonCrawl.

Runs the heavy slug-discovery batch (download cluster.idx + CDXJ shards,
binary-search the SURT prefix, regex-extract slugs) for one or more ATS
platforms against a CommonCrawl crawl, persisting new slugs into the global
omni_ats_slugs table. This is the ONLY place the ~100MB+ downloads happen, kept
off the API + dispatcher hot path.

Idempotent: a (platform, crawl) already in omni_ats_crawls is skipped.

Run on the box (inside the backend container), e.g. a periodic refresh:
    python -m app.execution.ats_discovery_worker                  # all platforms, latest crawl
    python -m app.execution.ats_discovery_worker --crawl CC-MAIN-2026-21
    python -m app.execution.ats_discovery_worker --platform greenhouse ashby

CommonCrawl publishes ~monthly; a sensible cadence is one refresh per new crawl
(wire to the scheduler the platform settles on — same open slot as the credential
sweep). Each platform is ~70-100s; the worker does them sequentially to stay a
polite CDX client.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.config import settings
from app.db import close_pool, init_pool
from app.services.ats import cdx, discover
from app.services.ats.plugins import ALL_PLATFORMS

log = logging.getLogger("ats_discovery_worker")


async def run(platforms: list[str], crawl: str | None) -> None:
    await init_pool(settings.database_url)
    try:
        target_crawl = crawl or cdx.latest_crawl()
        if not target_crawl:
            log.error("[ats] could not resolve a CommonCrawl crawl id")
            return
        log.info("[ats] discovery for crawl %s across %d platform(s)", target_crawl, len(platforms))
        for platform in platforms:
            try:
                result = await discover.discover_platform(platform, target_crawl)
                log.info("[ats] %s -> %s", platform, result)
            except Exception:  # noqa: BLE001 — one platform's failure shouldn't abort the rest
                log.exception("[ats] discovery failed for %s", platform)
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover ATS company slugs from CommonCrawl")
    parser.add_argument("--crawl", default=None, help="Crawl id (default: latest)")
    parser.add_argument(
        "--platform", nargs="*", default=None,
        help="Platforms to discover (default: all)",
    )
    args = parser.parse_args()
    platforms = args.platform or list(ALL_PLATFORMS)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run(platforms, args.crawl))


if __name__ == "__main__":
    main()
