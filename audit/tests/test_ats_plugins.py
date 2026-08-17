"""ATS slug-discovery regression — every platform must extract a slug.

THE BUG (caught 2026-06-22): lever's discovery pattern was pinned to the SURT
prefix ``co,lever,jobs`` (jobs.lever.co only) with a matching ``jobs\\.lever\\.co``
regex. Lever boards overwhelmingly live on **hire.lever.co** (the canonical
host), so the cluster.idx binary-search reached the wrong shard and the regex
matched nothing — Allen's harvest recorded 0 slugs across 5 crawls, and the
``source.lever`` node produced ZERO companies forever while the handler was fine.
Nothing failed loudly: a discovery pattern that finds nothing looks identical to
a platform with no companies.

These lock the discovery contract so a silently-dead platform can't ship again:
  - every platform's regex extracts the slug from a REAL board URL for that ATS;
  - its SURT prefix is a true prefix of that board host's SURT key (so the
    binary-search actually reaches the shard the regex needs);
  - lever specifically catches hire.lever.co (the host the old pattern missed);
  - false-positive guards (marketing pages, robots) still hold.

Pure (no DB/network). Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.services.ats.plugins import ALL_PLATFORMS, get_platform  # noqa: E402


def _surt_host(host: str) -> str:
    """The SURT key prefix CommonCrawl writes for a host (reversed labels,
    comma-joined). e.g. hire.lever.co -> 'co,lever,hire'. Enough for the
    startswith() check find_cdx_files does."""
    return ",".join(reversed(host.split(".")))


# One real, currently-live board URL per platform — the shape that appears in
# the CommonCrawl index. The slug each MUST extract is the second element.
_REAL_BOARDS: dict[str, tuple[str, str]] = {
    "greenhouse": ("https://boards.greenhouse.io/airbnb", "airbnb"),
    "ashby": ("https://jobs.ashbyhq.com/ramp", "ramp"),
    "smartrecruiters": ("https://careers.smartrecruiters.com/Ubisoft", "ubisoft"),
    "breezy": ("https://acme-co.breezy.hr", "acme-co"),
    "icims": ("https://careers-pfizer.icims.com", "pfizer"),
    "bamboohr": ("https://stripe.bamboohr.com/careers", "stripe"),
    "workday": ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", "nvidia|wd5|nvidiaexternalcareersite"),
    "lever": ("https://hire.lever.co/spotify", "spotify"),
    "workable": ("https://shopify.workable.com", "shopify"),
    "recruitee": ("https://gitlab.recruitee.com", "gitlab"),
    "personio": ("https://contentful.jobs.personio.de", "contentful"),
    "rippling": ("https://ats.rippling.com/coinbase/jobs", "coinbase"),
}


def test_every_platform_extracts_a_slug_from_a_real_board():
    """The lever-class invariant: NO platform may silently extract nothing from a
    real board URL. If this fails for a platform, its discovery is dead — slugs
    never land, the source produces ZERO, and nothing else complains."""
    for name, (url, expected) in _REAL_BOARDS.items():
        plat = get_platform(name)
        assert plat is not None, f"{name} not registered"
        slugs = list(plat.extract_slugs_from_url(url))
        assert expected in slugs, (
            f"{name}: extract_slugs_from_url({url!r}) gave {slugs}, expected {expected!r} — "
            f"discovery pattern reaches nothing (the lever bug)"
        )


def test_surt_prefix_actually_prefixes_the_board_host():
    """The binary-search uses startswith(surt_prefix); a prefix that doesn't lead
    to the board host's SURT key reaches the wrong shard and the regex never sees
    the URL — exactly how lever's `co,lever,jobs` missed hire.lever.co's
    `co,lever,hire`. Each platform's prefix must be a prefix of its board's SURT."""
    boards_host = {
        "greenhouse": "boards.greenhouse.io",
        "ashby": "jobs.ashbyhq.com",
        "smartrecruiters": "careers.smartrecruiters.com",
        "breezy": "acme.breezy.hr",
        "icims": "careers-pfizer.icims.com",
        "bamboohr": "stripe.bamboohr.com",
        "workday": "nvidia.wd5.myworkdayjobs.com",
        # lever is SEEDED, not CDX-discovered (CCBot robots-blocked) — its SURT
        # prefix targets jobs.lever.co only and is never actually searched; the
        # prefix-of-host invariant is asserted against that host, not hire.
        "lever": "jobs.lever.co",
        "workable": "shopify.workable.com",
        "recruitee": "gitlab.recruitee.com",
        "personio": "contentful.jobs.personio.de",
        "rippling": "ats.rippling.com",
    }
    for name, host in boards_host.items():
        plat = get_platform(name)
        surt = _surt_host(host)
        assert surt.startswith(plat.surt_prefix), (
            f"{name}: board host {host} -> SURT {surt!r} does NOT start with "
            f"surt_prefix {plat.surt_prefix!r} — the cluster.idx search misses this host"
        )


def test_lever_is_seeded_not_cdx_discovered():
    """REGRESSION: Lever produced ZERO because its slug inventory was empty, and
    the trap is thinking a CDX/SURT tweak fixes it — it can't. CCBot is blocked
    by jobs.lever.co/robots.txt, so CommonCrawl has NO Lever board URLs to find.
    Lever's 4,368 slugs are SEEDED from the Feashliaa aggregator via
    app.services.ats.seed, not harvested. This locks the architecture so nobody
    'fixes' lever by widening the SURT again (chasing an empty index)."""
    lever = get_platform("lever")
    # the regex still recognises both board hosts (so a seeded slug's URL parses,
    # and a future re-crawl is harmless), even though CDX never supplies them
    assert "spotify" in list(lever.extract_slugs_from_url("https://hire.lever.co/spotify"))
    assert "netflix" in list(lever.extract_slugs_from_url("https://jobs.lever.co/netflix"))


def test_lever_drops_marketing_and_system_paths():
    """The widened pattern must not pull marketing pages or robots as slugs."""
    lever = get_platform("lever")
    assert list(lever.extract_slugs_from_url("https://www.lever.co/about")) == []
    # robots IS extracted by the regex but rejected by the validity filter
    assert not lever.is_valid_slug("robots")
    assert not lever.is_valid_slug("favicon")
    # REGRESSION: the first real harvest of the widened prefix returned ONLY
    # Lever's own chrome (hire.lever.co/auth, /developer, jobs.lever.co/jobs) —
    # system pages on the same hosts. They must be filtered, not stored as
    # companies, or source.lever produces garbage rows.
    for system_path in ("auth", "developer", "jobs", "login", "signup", "api"):
        assert not lever.is_valid_slug(system_path), f"{system_path} is Lever chrome, not a company"
    # a real company slug still passes
    assert lever.is_valid_slug("spotify")


def test_all_twelve_platforms_present():
    """The catalogue is 12 ATS platforms — a dropped registration is a dropped
    source. (apollo/serper/searxng/naukri/clutch are non-ATS, not in this map.)"""
    assert len(ALL_PLATFORMS) == 12
    assert set(ALL_PLATFORMS) == set(_REAL_BOARDS)
