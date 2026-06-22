"""ATS platform definitions — the SLUG-DISCOVERY side, faithfully ported.

Each platform declares the three things CDX discovery needs:
  - surt_prefix      : SURT key to binary-search in cluster.idx
  - slug_regex       : regex (one capture group) to pull a company slug from a URL
  - is_valid_slug    : filter out system-path false positives
  - extract_slugs_from_url : override for composite slugs (workday: company|wdN|site)

Ported verbatim (regexes/validators) from Allen's pipeline/plugins/*.py. The
per-company job-fetch logic lives in the Rust muscle (handlers/ats.rs) — this
module is discovery only. See [[project_ats_cdx_port]].
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ATSPlatform:
    name: str
    surt_prefix: str
    slug_regex: str
    # System-path slugs to drop (greenhouse-style platforms have many).
    invalid_slugs: frozenset[str] = field(default_factory=frozenset)
    min_slug_len: int = 1
    # Workday packs three parts into one slug; flagged so extract() differs.
    composite: bool = False

    def is_valid_slug(self, slug: str) -> bool:
        if self.composite:
            return _workday_valid(slug)
        return slug not in self.invalid_slugs and len(slug) >= self.min_slug_len

    def extract_slugs_from_url(self, url: str) -> Iterator[str]:
        if self.composite:
            yield from _workday_extract(url)
            return
        for m in re.finditer(self.slug_regex, url):
            yield m.group(1).lower()


# ── Workday composite slug (company|wdN|site_id) ─────────────────────────────
_WORKDAY_URL_RE = re.compile(
    r"https?://([a-z0-9][a-z0-9-]*)\.(wd\d+)\.myworkdayjobs\.com/([a-z0-9_-]+)",
    re.IGNORECASE,
)
_WORKDAY_INVALID_SITE = frozenset(
    {"robots", "search", "login", "sitemap", "logout", "feed", "rss", "api"}
)
_WORKDAY_LOCALE_RE = re.compile(
    r"^(ar|bg|ca|cs|da|de|el|en|es|et|fi|fr|he|hr|hu|id|is|it|ja|ko|lt|lv|ms|nb|nl|no|pl|pt|ro|ru|sk|sl|sr|sv|th|tr|uk|vi|zh)"
    r"(-[a-z]{2})?$"
)


def _workday_extract(url: str) -> Iterator[str]:
    for m in _WORKDAY_URL_RE.finditer(url):
        company = m.group(1).lower()
        wd = m.group(2).lower()
        site_id = m.group(3).lower()
        yield f"{company}|{wd}|{site_id}"


def _workday_valid(slug: str) -> bool:
    parts = slug.split("|")
    if len(parts) != 3:
        return False
    site_id = parts[2]
    if site_id in _WORKDAY_INVALID_SITE:
        return False
    return not _WORKDAY_LOCALE_RE.match(site_id)


_SMARTRECRUITERS_SYSTEM = frozenset({
    "about-us", "blog", "role", "help", "partner", "partners", "pricing", "product",
    "customers", "resources", "login", "signup", "contact", "team", "news", "press",
    "legal", "privacy", "terms", "leadership", "platform", "solutions", "integrations",
    "developer", "api", "support", "security", "events", "webinars", "podcast",
    "case-studies", "testimonials", "faq", "sitemap", "search", "careers", "jobs",
    "hiring-success", "hiring-tools", "recruiting-software", "industries", "use-case",
    "topics", "success", "de", "fr", "en", "es", "it", "pt", "nl", "ja", "ko", "zh",
    "ar", "robots.txt",
})

# All 12 platforms, keyed by name. Order mirrors Allen's registry.
PLATFORMS: dict[str, ATSPlatform] = {
    "greenhouse": ATSPlatform(
        name="greenhouse",
        surt_prefix="io,greenhouse",
        slug_regex=r"(?:boards|job-boards)\.greenhouse\.io/([a-z0-9][a-z0-9-]*[a-z0-9])",
    ),
    "ashby": ATSPlatform(
        name="ashby",
        surt_prefix="com,ashbyhq,jobs",
        slug_regex=r"jobs\.ashbyhq\.com/([a-z0-9][a-z0-9-]*[a-z0-9])",
    ),
    "smartrecruiters": ATSPlatform(
        name="smartrecruiters",
        surt_prefix="com,smartrecruiters",
        slug_regex=r"(?:www\.|careers\.|jobs\.)?smartrecruiters\.com/([a-zA-Z][a-zA-Z0-9-]*[a-zA-Z0-9])",
        invalid_slugs=_SMARTRECRUITERS_SYSTEM,
        min_slug_len=2,
    ),
    "breezy": ATSPlatform(
        name="breezy",
        surt_prefix="hr,breezy",
        slug_regex=r"([a-z0-9][a-z0-9-]*[a-z0-9])\.breezy\.hr",
    ),
    "icims": ATSPlatform(
        name="icims",
        surt_prefix="com,icims,",
        slug_regex=r"(?:careers|app-career)-([a-z0-9][a-z0-9-]*[a-z0-9])\.icims\.com",
    ),
    "bamboohr": ATSPlatform(
        name="bamboohr",
        surt_prefix="com,bamboohr,",
        slug_regex=r"([a-z0-9][a-z0-9-]*[a-z0-9])\.bamboohr\.com",
    ),
    "workday": ATSPlatform(
        name="workday",
        surt_prefix="com,myworkdayjobs,",
        slug_regex=r"([a-z0-9][a-z0-9-]*)\.(wd\d+)\.myworkdayjobs\.com/([a-z0-9_-]+)",
        composite=True,
    ),
    "lever": ATSPlatform(
        # Allen's harvest pinned the SURT to `co,lever,jobs` (jobs.lever.co only)
        # and found 0 slugs across 5 crawls — Lever boards overwhelmingly live on
        # hire.lever.co (the canonical host), which that prefix never reached.
        # Widen to the `co,lever` prefix so the cluster.idx binary-search spans
        # every *.lever.co board host, and match the slug off both hire. and jobs.
        name="lever",
        surt_prefix="co,lever",
        slug_regex=r"(?:hire|jobs)\.lever\.co/([a-z0-9][a-z0-9-]*[a-z0-9])",
        invalid_slugs=frozenset({"robots", "favicon"}),
    ),
    "workable": ATSPlatform(
        name="workable",
        surt_prefix="com,workable",
        slug_regex=r"([a-z0-9][a-z0-9-]*[a-z0-9])\.workable\.com",
        invalid_slugs=frozenset({
            "www", "apply", "blog", "support", "help", "api", "app", "status", "jobs",
            "events", "get", "partnerhelp", "partners", "resources", "tools",
            "site-editor", "subdomain", "jobseekers", "demo-workable-academy-2",
            "demo-request", "pricing", "about",
        }),
        min_slug_len=3,
    ),
    "recruitee": ATSPlatform(
        name="recruitee",
        surt_prefix="com,recruitee",
        slug_regex=r"([a-z0-9][a-z0-9-]*[a-z0-9])\.recruitee\.com",
        invalid_slugs=frozenset({"www", "blog", "support", "help", "api", "app", "status", "docs", "developer"}),
        min_slug_len=3,
    ),
    "personio": ATSPlatform(
        name="personio",
        surt_prefix="de,personio,jobs",
        slug_regex=r"([a-z0-9][a-z0-9-]*[a-z0-9])\.jobs\.personio\.(?:de|com)",
        invalid_slugs=frozenset({"www", "blog", "support", "help", "api", "app", "status"}),
        min_slug_len=3,
    ),
    "rippling": ATSPlatform(
        name="rippling",
        surt_prefix="com,rippling,ats",
        slug_regex=r"ats\.rippling\.com/([a-z0-9][a-z0-9-]*[a-z0-9])",
        invalid_slugs=frozenset({"www", "blog", "support", "help", "api", "app", "status", "robots"}),
        min_slug_len=3,
    ),
}

ALL_PLATFORMS: tuple[str, ...] = tuple(PLATFORMS.keys())


def get_platform(name: str) -> ATSPlatform | None:
    return PLATFORMS.get(name)
