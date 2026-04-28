"""
company_discovery_service.py — Dashboard-driven company → decision-maker pipeline.

User pastes LinkedIn company URLs; we find decision-makers inside each company
(Serper Google search, Unipile fallback), filter by target titles (keyword first,
Claude LLM fallback for ambiguous headlines), and return a preview table.
push_to_sheet appends ACCEPTed rows to the campaign's leads sheet — downstream
runner ingestion handles DB writes on the next cycle.

Self-contained: does not import from the outreach_automation package. That keeps
the dashboard's own `db.py` from being shadowed by the automation's `db.py`, which
would cause ImportErrors on server.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

from db import fetch_one
from lead_screener import screen_lead

log = logging.getLogger(__name__)
load_dotenv()

# ─── Constants ────────────────────────────────────────────────────────────────
MAX_COMPANIES_PER_RUN = 25
MAX_PEOPLE_PER_COMPANY = 100
SERPER_SEARCH_DELAY = 1.0
SERPER_MAX_RETRIES = 3
UNIPILE_SEARCH_PATH = "/api/v1/linkedin/search"
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

_COMPANY_SLUG_RE = re.compile(r"linkedin\.com/company/([A-Za-z0-9\-_.%]+)", re.IGNORECASE)
_TITLE_ABBREV_EXPANSIONS: dict[str, str] = {
    "ceo": "chief executive officer",
    "cmo": "chief marketing officer",
    "cgo": "chief growth officer",
    "cro": "chief revenue officer",
    "coo": "chief operating officer",
    "cto": "chief technology officer",
    "cfo": "chief financial officer",
    "cpo": "chief product officer",
    "cxo": "chief experience officer",
    "vp": "vice president",
    "svp": "senior vice president",
    "evp": "executive vice president",
    "avp": "associate vice president",
}

_SHEET_HEADERS = [
    "LinkedIn_URL", "first_name", "last_name",
    "headline", "company_name", "industry", "location",
    "source", "screening_status", "screening_reason",
]


# ─── Secrets (env only — no DB config dependency on the automation side) ──────

def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _service_account_file() -> str:
    """Resolve the Google service account JSON path. Dashboard dir first, then automation dir fallback."""
    env_path = _env("GOOGLE_SERVICE_ACCOUNT_JSON")
    if env_path and Path(env_path).is_file():
        return env_path
    here = Path(__file__).resolve().parent
    for candidate in [
        here / "google_service_account.json",
        here.parent / "outreach_automation" / "google_service_account.json",
        Path("/home/omni/marketing-automation/google_service_account.json"),
    ]:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("No google_service_account.json found")


def _gspread_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(_service_account_file(), scopes=_SCOPES)
    return gspread.authorize(creds)


# ─── Input parsing ────────────────────────────────────────────────────────────

def _extract_slug(raw_url: str) -> str | None:
    if not raw_url:
        return None
    match = _COMPANY_SLUG_RE.search(raw_url.strip())
    if not match:
        return None
    slug = match.group(1).rstrip("/").split("/")[0]
    return slug or None


_DOMAIN_FROM_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?([^/\s]+)", re.IGNORECASE)


def _extract_domain(raw_url: str) -> str | None:
    """Pull the bare domain out of any URL-like string. 'https://slack.com/about' -> 'slack.com'."""
    if not raw_url:
        return None
    m = _DOMAIN_FROM_URL_RE.match(raw_url.strip())
    if not m:
        return None
    host = m.group(1).lower().rstrip("/.")
    # Skip things that aren't plausibly a domain.
    if "." not in host or host.endswith(".linkedin.com") or host == "linkedin.com":
        return None
    return host


def _resolve_company_from_website(raw_url: str) -> dict | None:
    """Given a regular website URL (e.g. 'slack.com'), find its LinkedIn company page.

    Returns {"slug": "slack", "linkedin_url": "https://www.linkedin.com/company/slack"} or None.
    Uses Serper (Google) — same API key as the decision-maker search.
    """
    domain = _extract_domain(raw_url)
    if not domain:
        return None
    serper_key = _env("SERPER_KEY")
    if not serper_key:
        log.warning("[resolve] SERPER_KEY missing — cannot resolve website to LinkedIn company")
        return None

    # Note: Serper rejects queries with quoted domains as "Query not allowed".
    query = f"{domain} site:linkedin.com/company"
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
            json={"q": query, "num": 5},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning(f"[resolve] Serper lookup failed for {domain}: {e}")
        return None

    for item in data.get("organic") or []:
        link = (item.get("link") or "").strip()
        slug = _extract_slug(link)
        if slug:
            return {"slug": slug, "linkedin_url": f"https://www.linkedin.com/company/{slug}"}
    return None


def _parse_company_urls(raw: str | list[str]) -> list[dict]:
    """Build company dicts from user input.

    Input lines may be:
      - LinkedIn company URLs (linkedin.com/company/<slug>) — slug extracted directly.
      - Regular website URLs (slack.com, https://slack.com/about) — resolved via Serper.
    Entries that are neither (or can't be resolved) are dropped.
    """
    lines = raw if isinstance(raw, list) else (raw or "").splitlines()
    seen: set[str] = set()
    companies: list[dict] = []
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue

        # 1. LinkedIn company URL — direct slug extract.
        slug = _extract_slug(cleaned)
        linkedin_url = cleaned

        # 2. Website URL — resolve via Serper to find the LinkedIn company page.
        if not slug:
            resolved = _resolve_company_from_website(cleaned)
            if resolved:
                slug = resolved["slug"]
                linkedin_url = resolved["linkedin_url"]

        if not slug or slug in seen:
            continue
        seen.add(slug)
        companies.append({
            "company_name": slug,
            "linkedin_url": linkedin_url,
            "source_url": cleaned,
            "sector": "",
            "employees": "",
        })
        if len(companies) >= MAX_COMPANIES_PER_RUN:
            break
    return companies


def _parse_titles(raw: str | list[str]) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[,\n]", raw or "")
    return [t.strip() for t in items if t and t.strip()]


# ─── Decision-maker search ────────────────────────────────────────────────────

def _clean_role_from_title(title: str, company_name: str, fallback_role: str) -> str:
    if not title:
        return fallback_role
    cleaned = re.sub(re.escape(company_name), "", title, flags=re.IGNORECASE).strip(" -|,•")
    return cleaned or fallback_role


# Fragments left over after Serper's "Name - Company - LinkedIn" titles get stripped.
# If the cleaned headline matches one of these, it carries no role info and we should
# look elsewhere (snippet, fallback role) for the actual job title.
_GENERIC_HEADLINE_FRAGMENTS = {
    "linkedin",
    "| linkedin",
    "- linkedin",
    "linkedin profile",
}


_ROLE_HINT_TOKENS = {
    "ceo", "cmo", "cgo", "cro", "coo", "cto", "cfo", "cpo", "cxo",
    "vp", "svp", "evp", "avp", "head", "lead", "leader", "director",
    "founder", "cofounder", "co-founder", "owner", "partner", "manager",
    "officer", "chief", "president", "engineer", "designer", "marketing",
    "growth", "sales", "product", "engineering",
}


def _headline_is_generic(headline: str) -> bool:
    """A headline is 'generic' if it doesn't contain any role/title keywords.

    Examples that should be considered generic and trigger snippet fallback:
      ''                        — empty
      'LinkedIn'                — leftover scaffolding
      'HeroDevs | LinkedIn'     — only the company name + 'LinkedIn'
      'Tiny Speck, Inc - LinkedIn' — same
    Examples that are NOT generic:
      'CEO at HeroDevs'
      'Senior Software Engineer'
      'Chief Marketing Officer'
    """
    h = re.sub(r"[^a-z0-9\- ]", " ", (headline or "").lower())
    tokens = {t for t in h.split() if t and t != "linkedin"}
    if not tokens:
        return True
    return not (tokens & _ROLE_HINT_TOKENS)


def _extract_role_from_snippet(snippet: str, company_name: str, fallback_role: str) -> str:
    """Pull a role-bearing sentence/clause out of a Serper snippet.

    Snippets typically look like:
      'Aaron Frost (aka Frosty) is the CEO of HeroDevs, a team...'
      'Sally Bunnell is the Founder & CEO of NaviSavi, a TechStars-backed...'
      'Senior SWE @ Jump Trading · Software Engineer with...'

    We return the snippet itself (truncated) when it contains role keywords,
    otherwise a 'Role at Company' fallback. The downstream title filter does
    the actual matching — we just need to make sure SOMETHING role-bearing is
    in the headline string.
    """
    text = (snippet or "").strip()
    if text:
        # Trim to a manageable length but keep enough context for keyword + LLM matching.
        return text[:240]
    return f"{fallback_role} at {company_name}"


def _search_serper_profiles(company_name: str, role: str, serper_key: str) -> list[dict]:
    headers = {"X-API-KEY": serper_key, "Content-Type": "application/json"}
    patterns = [
        f"{role} at {company_name} site:linkedin.com/in",
        f"{company_name} {role} site:linkedin.com/in",
        f"{role} {company_name} LinkedIn",
    ]
    found: list[dict] = []
    seen_urls: set[str] = set()

    for pattern in patterns:
        for attempt in range(SERPER_MAX_RETRIES):
            try:
                resp = requests.post(
                    "https://google.serper.dev/search",
                    headers=headers,
                    json={"q": pattern, "num": 10},
                    timeout=30,
                )
                if resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("organic") or []:
                    url = (item.get("link") or "").strip()
                    if "linkedin.com/in/" not in url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    raw_title = (item.get("title") or "").strip()
                    snippet = (item.get("snippet") or "").strip()
                    name = raw_title.split(" - ")[0].strip() if raw_title else ""
                    title_tail = " - ".join(raw_title.split(" - ")[1:]).strip() if raw_title else ""
                    headline = _clean_role_from_title(title_tail, company_name, role)
                    # If the title yielded only "LinkedIn" / "| LinkedIn" / etc, the role lives
                    # in the snippet — use that so the title filter has something to match on.
                    if _headline_is_generic(headline):
                        headline = _extract_role_from_snippet(snippet, company_name, role)
                    found.append({
                        "first_name": name.split()[0] if name else "",
                        "last_name": " ".join(name.split()[1:]) if name else "",
                        "headline": headline,
                        "location": "",
                        "linkedin_url": url,
                        "company_name": company_name,
                        "industry": "",
                        "provider_id": "",
                    })
                    if len(found) >= MAX_PEOPLE_PER_COMPANY:
                        return found
                break
            except Exception as e:
                log.warning(f"[serper] Search failed for '{pattern}': {e}")
                break
            finally:
                time.sleep(SERPER_SEARCH_DELAY)
    return found


def _resolve_linkedin_company_id(slug: str, account_id: str) -> str | None:
    """Resolve a LinkedIn company slug to its numeric LinkedIn ID via Unipile.

    Unipile's people search filter expects a numeric LinkedIn company ID
    (e.g. '2135371' for Stripe), not the slug. GET /api/v1/linkedin/company/<slug>
    returns the company profile with the numeric id.
    """
    base = _env("UNIPILE_BASE")
    key = _env("UNIPILE_API_KEY")
    if not slug or not base or not key or not account_id:
        return None
    try:
        resp = requests.get(
            f"{base}/api/v1/linkedin/company/{slug}",
            params={"account_id": account_id},
            headers={"X-API-KEY": key, "accept": "application/json"},
            timeout=20,
        )
        if resp.status_code != 200:
            log.warning(f"[unipile] company resolve {slug}: {resp.status_code} {resp.text[:120]}")
            return None
        data = resp.json()
    except Exception as e:
        log.warning(f"[unipile] company resolve {slug} failed: {e}")
        return None
    cid = data.get("id")
    return str(cid) if cid else None


def _unipile_search_page(
    base: str,
    headers: dict,
    body: dict,
    account_id: str,
    cursor: str | None,
) -> tuple[list[dict], str | None]:
    """Single Unipile classic people-search request. Returns (items, next_cursor)."""
    params = {"account_id": account_id}
    if cursor:
        params["cursor"] = cursor
    try:
        resp = requests.post(
            f"{base}{UNIPILE_SEARCH_PATH}",
            params=params,
            headers=headers,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning(f"[unipile] page failed body={body.get('keywords')!r}: {e}")
        return [], None
    return data.get("items") or [], data.get("cursor")


def _search_unipile_profiles(company: dict, titles: list[str], account_id: str) -> list[dict]:
    """Find people who currently work at `company` via Unipile classic people search.

    For leadership coverage we run ONE search per target title (rather than a single
    bundled `"CEO OR CMO OR ..."` query — that biased toward ICs because LinkedIn's
    relevance ranking treats `OR` as a soft preference). Each per-title query's first
    page is leadership-biased for that role; we union the results, dedupe by URL,
    and cap at MAX_PEOPLE_PER_COMPANY.

    network_distance=[2,3] keeps results within reach but excludes 1st-degree noise
    from the searching account itself.
    """
    base = _env("UNIPILE_BASE")
    key = _env("UNIPILE_API_KEY")
    if not base or not key or not account_id:
        log.warning("[unipile] missing UNIPILE_BASE / UNIPILE_API_KEY / account_id — skipping")
        return []

    slug = company["company_name"]
    company_id = _resolve_linkedin_company_id(slug, account_id)
    if not company_id:
        log.warning(f"[unipile] could not resolve LinkedIn company id for slug={slug!r}")
        return []

    headers = {
        "X-API-KEY": key,
        "accept": "application/json",
        "content-type": "application/json",
    }

    results: list[dict] = []
    seen_urls: set[str] = set()

    def _consume(items: list[dict]) -> None:
        for item in items:
            public_id = item.get("public_identifier") or ""
            if not public_id:
                continue
            url = f"https://www.linkedin.com/in/{public_id}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results.append({
                "first_name": (item.get("name") or "").split()[0] if item.get("name") else "",
                "last_name": " ".join((item.get("name") or "").split()[1:]),
                "headline": item.get("headline") or "",
                "location": item.get("location") or "",
                "linkedin_url": url,
                "company_name": slug,
                "industry": company.get("sector") or company.get("industry") or "",
                "provider_id": item.get("id") or "",
            })

    # 1. Per-title queries — leadership-biased for each role.
    for title in titles:
        if len(results) >= MAX_PEOPLE_PER_COMPANY:
            break
        body: dict = {
            "api": "classic",
            "category": "people",
            "keywords": title,
            "company": [company_id],
            "network_distance": [2, 3],
        }
        items, _ = _unipile_search_page(base, headers, body, account_id, cursor=None)
        before = len(results)
        _consume(items)
        log.info(f"[unipile] {slug} keyword={title!r}: +{len(results) - before} new (total {len(results)})")

    # 2. Backfill with a no-keyword company-scoped sweep, paginated, in case the per-title
    #    queries didn't return enough leaders.
    cursor: str | None = None
    pages = 0
    body_sweep = {
        "api": "classic",
        "category": "people",
        "company": [company_id],
        "network_distance": [2, 3],
    }
    while pages < 4 and len(results) < MAX_PEOPLE_PER_COMPANY:
        items, cursor = _unipile_search_page(base, headers, body_sweep, account_id, cursor=cursor)
        if not items:
            break
        before = len(results)
        _consume(items)
        log.info(f"[unipile] {slug} sweep page {pages}: +{len(results) - before} new (total {len(results)})")
        pages += 1
        if not cursor:
            break

    log.info(f"[unipile] {slug} (id={company_id}): {len(results)} unique profiles total")
    return results[:MAX_PEOPLE_PER_COMPANY]


def _normalize_company_token(name: str) -> str:
    """Lowercase + strip non-alnum + drop common corporate suffixes for fuzzy match."""
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    s = re.sub(r"\b(inc|llc|ltd|limited|gmbh|sa|co|corp|corporation|company|technologies|tech)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


_GENERIC_COMPANY_TOKENS = {
    "tiny", "the", "co", "inc", "ltd", "labs", "tech", "group", "global",
    "world", "international", "digital", "studio", "ventures", "partners",
    "solutions", "systems", "data", "ai", "media", "app", "soft", "online",
    "spec", "specs", "software", "services",
}


def _brand_from_domain(url: str) -> str:
    """Pull the brand stem out of a URL's domain. 'https://slack.com/about' -> 'slack'.

    Returns '' if the URL is empty, a LinkedIn URL, or has no usable hostname.
    """
    if not url:
        return ""
    m = _DOMAIN_FROM_URL_RE.match(url.strip())
    if not m:
        return ""
    host = m.group(1).lower().rstrip("/.")
    if "linkedin.com" in host or "." not in host:
        return ""
    # 'app.slack.com' -> ['app', 'slack', 'com'] -> 'slack' (the registrable label, not TLD/sub).
    parts = host.split(".")
    if len(parts) < 2:
        return ""
    # Take the second-to-last part as the brand (works for slack.com, app.slack.com, slack.co.uk-ish too).
    brand = parts[-2]
    return brand if len(brand) >= 3 else ""


def _profile_currently_at_company(lead: dict, company: dict) -> bool:
    """Return True if the lead's headline credibly indicates current employment at the target company.

    Logic: build a set of CURRENT-employment phrases from the company name/slug AND
    from the brand portion of the originally-pasted URL (so 'slack.com' -> 'slack' is a
    valid marker even when the resolved LinkedIn slug is the parent like 'tiny-spec-inc').
    A profile passes only if (a) one of those phrases appears in the headline AND
    (b) the headline's nearest past-tense marker (ex/former/previously) does NOT
    apply to that phrase.
    """
    headline = (lead.get("headline") or "").lower()
    if not headline:
        return False

    # Build candidate company phrases. Multi-word phrases (full normalized name)
    # are far more reliable than single short tokens like 'tiny' or 'spec'.
    raw_slug = (company.get("company_name") or "").lower()
    source_url = (company.get("source_url") or "").lower()
    full_normalized = _normalize_company_token(raw_slug)
    slug_dehyphened = re.sub(r"[-_]+", " ", raw_slug).strip()

    phrases: list[str] = []
    if full_normalized and len(full_normalized) >= 4:
        phrases.append(full_normalized)
    if slug_dehyphened and slug_dehyphened != full_normalized and len(slug_dehyphened) >= 4:
        phrases.append(slug_dehyphened)
    # Multi-word slug as a phrase (without suffix stripping), to catch e.g. 'tiny speck'.
    if " " in slug_dehyphened:
        phrases.append(slug_dehyphened)
    # Single tokens are only allowed if they're long and not in the generic blocklist.
    for token in re.split(r"[-_\s]+", raw_slug):
        if len(token) >= 5 and token not in _GENERIC_COMPANY_TOKENS:
            phrases.append(token)
    # Brand from the input domain (handles slack.com -> 'slack' even when slug is 'tiny-spec-inc').
    brand = _brand_from_domain(source_url)
    if brand and brand not in _GENERIC_COMPANY_TOKENS:
        phrases.append(brand)

    # Dedupe while preserving order.
    seen: set[str] = set()
    phrases = [p for p in phrases if not (p in seen or seen.add(p))]
    if not phrases:
        # Nothing safe to verify against — be permissive rather than dropping everyone.
        return True

    headline_norm = re.sub(r"[^a-z0-9 ]", " ", headline)
    headline_norm = re.sub(r"\s+", " ", headline_norm).strip()

    for phrase in phrases:
        if not re.search(rf"\b{re.escape(phrase)}\b", headline_norm):
            continue
        # Past-tense marker anywhere before the phrase within the same headline is disqualifying.
        if re.search(rf"\b(ex|former|formerly|previously|past|prev)\b[^.]*?\b{re.escape(phrase)}\b", headline_norm):
            continue
        return True
    return False


def _search_decision_makers(company: dict, titles: list[str], account_id: str) -> list[dict]:
    """Find candidate decision-makers and verify they currently work at the target company.

    Runs both Serper (broad coverage) and Unipile (employment-aware) when both keys are present,
    deduplicates by linkedin_url, then filters out profiles whose headline doesn't credibly
    indicate current employment at the target company.
    """
    serper_key = _env("SERPER_KEY")
    company_name = company["company_name"]

    raw: list[dict] = []
    seen_urls: set[str] = set()

    # Unipile first when available — it actually filters by current_company at the API level.
    if account_id and _env("UNIPILE_API_KEY"):
        for lead in _search_unipile_profiles(company, titles, account_id):
            url = lead["linkedin_url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            raw.append(lead)
            if len(raw) >= MAX_PEOPLE_PER_COMPANY:
                break

    # Serper as a broad supplement — its results need verification before we trust them.
    if serper_key and len(raw) < MAX_PEOPLE_PER_COMPANY:
        for role in titles:
            for lead in _search_serper_profiles(company_name, role, serper_key):
                url = lead["linkedin_url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                lead["industry"] = company.get("sector") or company.get("industry") or ""
                raw.append(lead)
                if len(raw) >= MAX_PEOPLE_PER_COMPANY:
                    break
            if len(raw) >= MAX_PEOPLE_PER_COMPANY:
                break

    log.info(f"[search] {company_name}: {len(raw)} raw profiles")
    return raw


# ─── Title filtering ──────────────────────────────────────────────────────────

def _normalize_title(text: str) -> str:
    lowered = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    tokens = [_TITLE_ABBREV_EXPANSIONS.get(tok, tok) for tok in lowered.split()]
    return " ".join(tokens).strip()


def _tokens_in_order(needle_tokens: list[str], haystack_tokens: list[str]) -> bool:
    """True if every needle token appears in haystack in the same order (gaps allowed)."""
    if not needle_tokens:
        return False
    i = 0
    for tok in haystack_tokens:
        if tok == needle_tokens[i]:
            i += 1
            if i == len(needle_tokens):
                return True
    return False


_PAST_ROLE_MARKERS = re.compile(
    r"\b(ex|former|formerly|previously|prev|past|x|nx)\b[^.|·•]{0,40}",
    re.IGNORECASE,
)


def _is_match_in_past_role_context(headline: str, matched_title: str) -> bool:
    """Reject the keyword match if the matched title sits in a clearly-past-role
    fragment of the headline (e.g. '... | 3x startup CTO', '... ex-CTO of Foo').
    """
    if not headline or not matched_title:
        return False
    h_lower = headline.lower()
    m_lower = matched_title.lower()
    # Find each occurrence of the matched title and check if it's preceded by
    # a past-tense marker within the same delimited fragment.
    for match in re.finditer(re.escape(m_lower), h_lower):
        start = match.start()
        # Walk back to the nearest delimiter |, ·, •, or start-of-string.
        fragment_start = max(
            (h_lower.rfind(d, 0, start) for d in ("|", "·", "•", ",", ";")),
            default=-1,
        )
        fragment = h_lower[fragment_start + 1: start]
        # Past-tense marker in the fragment leading up to the match disqualifies it.
        if re.search(r"\b(ex|former|formerly|previously|prev|past)\b", fragment):
            return True
        # Patterns like '2x', '3x' before a role token also indicate count-of-past-roles.
        if re.search(r"\b\d+\s*x\b", fragment):
            return True
    return False


def _keyword_title_filter(headline: str, target_titles: list[str]) -> tuple[str, str | None]:
    norm_headline = _normalize_title(headline)
    if not norm_headline:
        return "none", None
    headline_tokens = norm_headline.split()
    for title in target_titles:
        norm_title = _normalize_title(title)
        if not norm_title:
            continue
        title_tokens = norm_title.split()
        matched = False
        # Whole-phrase substring check first (exact contiguous match).
        if norm_title in norm_headline or norm_headline in norm_title:
            matched = True
        # Looser: every token of the target appears in the headline in order (allowing filler words).
        elif _tokens_in_order(title_tokens, headline_tokens):
            matched = True
        if matched and not _is_match_in_past_role_context(headline, title):
            return "keyword", title
    return "none", None


def _llm_title_screen(lead: dict, target_titles: list[str]) -> tuple[str, str]:
    titles_str = ", ".join(target_titles) if target_titles else "<none>"
    prompt = (
        f"You are screening a LinkedIn profile to decide if this person is a "
        f"decision-maker matching the target roles: {titles_str}.\n\n"
        f"ACCEPT if the headline shows the person currently holds:\n"
        f"  - one of the listed roles, OR\n"
        f"  - a senior-equivalent role at the company (Head of X, Director of X, "
        f"VP of X, Country/Regional Lead, General Manager, Country Director, "
        f"or any 'Head of' / 'Lead' / 'Director' role in the relevant function).\n\n"
        f"REJECT only if the role is clearly individual-contributor, junior, or "
        f"in an unrelated function (engineer, recruiter, analyst, intern, "
        f"associate without management scope, etc).\n\n"
        f"Bias toward ACCEPT for any 'Head of <area>' or 'Director of <area>' "
        f"role at the company. Do not require an exact title match."
    )
    return screen_lead(lead, prompt)


# ─── Campaign sheet lookup ────────────────────────────────────────────────────

def _resolve_campaign_sheet(campaign_id: str) -> tuple[str, str]:
    row = fetch_one(
        "SELECT leads_sheet_id, leads_tab FROM campaign_sheets WHERE campaign_id = %s",
        (campaign_id,),
    )
    if not row or not row.get("leads_sheet_id") or not row.get("leads_tab"):
        raise RuntimeError(f"No leads sheet configured for campaign {campaign_id}")
    return row["leads_sheet_id"], row["leads_tab"]


def _get_unipile_account(campaign_id: str | None) -> str:
    if campaign_id:
        row = fetch_one(
            "SELECT account_id FROM campaign_linkedin_accounts WHERE campaign_id = %s LIMIT 1",
            (campaign_id,),
        )
        if row:
            return row["account_id"]
    row = fetch_one("SELECT account_id FROM campaign_linkedin_accounts LIMIT 1")
    return row["account_id"] if row else ""


def _get_worksheet(sheet_id: str, tab_name: str):
    ss = _gspread_client().open_by_key(sheet_id)
    try:
        return ss.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=tab_name, rows=1000, cols=20)


def _ensure_sheet_headers(ws) -> None:
    existing = ws.row_values(1)
    if not existing:
        ws.append_rows([_SHEET_HEADERS], value_input_option="USER_ENTERED")


# ─── Public API ───────────────────────────────────────────────────────────────

def run_discovery(
    company_urls: str | list[str],
    titles: str | list[str],
    campaign_id: str | None = None,
) -> dict[str, Any]:
    companies = _parse_company_urls(company_urls)
    target_titles = _parse_titles(titles)

    if not companies:
        return {"rows": [], "stats": {"companies": 0, "candidates": 0, "accepted": 0, "rejected": 0}}
    if not target_titles:
        return {
            "rows": [],
            "stats": {"companies": len(companies), "candidates": 0, "accepted": 0, "rejected": 0},
            "error": "no_titles",
        }

    account_id = _get_unipile_account(campaign_id)
    anthropic_key_present = bool(_env("ANTHROPIC_API_KEY"))

    rows: list[dict] = []
    candidates = 0
    accepted = 0
    rejected = 0

    for company in companies:
        raw_leads = _search_decision_makers(company, target_titles, account_id)
        # Drop profiles whose headline doesn't credibly indicate current employment at the target.
        leads = [lead for lead in raw_leads if _profile_currently_at_company(lead, company)]
        log.info(
            f"[discovery] {company['company_name']}: "
            f"{len(leads)}/{len(raw_leads)} profiles after employment verification"
        )
        candidates += len(leads)

        for lead in leads:
            method, matched = _keyword_title_filter(lead.get("headline", ""), target_titles)
            if method == "keyword":
                verdict = "ACCEPT"
                reason = f"matched '{matched}' in headline"
                match_method = "keyword"
            elif anthropic_key_present:
                verdict, reason = _llm_title_screen(lead, target_titles)
                match_method = "llm"
            else:
                verdict = "REVIEW"
                reason = "no keyword match and ANTHROPIC_API_KEY not configured"
                match_method = "skipped"

            if verdict == "ACCEPT":
                accepted += 1
            elif verdict == "REJECT":
                rejected += 1

            rows.append({
                "company_name": company["company_name"],
                "company_url": company["linkedin_url"],
                "linkedin_url": lead.get("linkedin_url", ""),
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "headline": lead.get("headline", ""),
                "location": lead.get("location", ""),
                "industry": lead.get("industry", ""),
                "match_method": match_method,
                "verdict": verdict,
                "reason": reason,
            })

    return {
        "rows": rows,
        "stats": {
            "companies": len(companies),
            "candidates": candidates,
            "accepted": accepted,
            "rejected": rejected,
        },
    }


def push_to_sheet(rows: list[dict], campaign_id: str) -> dict[str, Any]:
    if not campaign_id:
        raise RuntimeError("campaign_id is required to push leads")

    sheet_id, tab_name = _resolve_campaign_sheet(campaign_id)
    ws = _get_worksheet(sheet_id, tab_name)
    _ensure_sheet_headers(ws)

    accepted_rows = [r for r in rows if r.get("verdict") == "ACCEPT" and r.get("linkedin_url")]
    if not accepted_rows:
        return {"pushed": 0, "skipped": len(rows), "sheet_id": sheet_id, "tab": tab_name}

    payload = [
        [
            r.get("linkedin_url", ""),
            r.get("first_name", ""),
            r.get("last_name", ""),
            r.get("headline", ""),
            r.get("company_name", ""),
            r.get("industry", ""),
            r.get("location", ""),
            "company_discovery",
            "ACCEPT",
            r.get("reason", ""),
        ]
        for r in accepted_rows
    ]
    ws.append_rows(payload, value_input_option="USER_ENTERED")

    return {
        "pushed": len(accepted_rows),
        "skipped": len(rows) - len(accepted_rows),
        "sheet_id": sheet_id,
        "tab": tab_name,
    }
