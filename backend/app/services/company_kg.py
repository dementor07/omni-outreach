"""Company knowledge-graph resolver — dedup, alias resolution, people cache.

Ported from the parallel org-repo implementation (omni_outreach_v3 resolver.rs +
discovery.rs people cache) into our multi-tenant v2 model. Every call is
workspace-scoped; callers run inside a ``system_scope()`` / request scope so RLS
binds the tenant.

Resolution order (cheapest first), mirroring resolver.rs:
  1. exact case-insensitive name match
  2. alias table lookup
  3. fuzzy suffix-strip ("SourceMash Technologies" -> "SourceMash") + auto-alias
  4. create new (pending screening)

The point is cost: a company resolved once is never re-discovered. ``cached_people``
returns previously found decision-makers so people-discovery can be skipped.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.db import execute, fetch_all, fetch_one

log = logging.getLogger(__name__)

# Common company-name suffixes stripped during fuzzy matching (resolver.rs parity).
_COMMON_SUFFIXES: tuple[str, ...] = (
    "technologies", "technology", "tech", "solutions", "solution", "software",
    "systems", "system", "services", "service", "consulting", "consultancy",
    "ventures", "venture", "labs", "lab", "group", "inc", "incorporated", "llc",
    "ltd", "limited", "pvt", "private", "corp", "corporation", "intl",
    "international", "holdings", "holding", "partners", "partner", "global",
    "digital", "creative", "productions", "production", "industries", "industry",
    "management", "capital", "advisors", "advisor", "analytics", "networks",
    "network", "media", "online", "worldwide",
)


@dataclass
class ResolvedCompany:
    id: str
    name: str
    domain: str | None
    industry: str | None
    employee_count: int | None
    screening_status: str
    people_discovered: bool
    created: bool  # True if this call created the company


async def resolve_company(
    workspace_id: str,
    name: str,
    *,
    industry: str | None = None,
    employee_count: int | None = None,
    domain: str | None = None,
) -> ResolvedCompany:
    """Resolve a raw company name to a canonical omni_companies row, deduping
    via exact / alias / fuzzy match and creating it if genuinely new."""
    name = (name or "").strip()
    if not name:
        raise ValueError("company name required")

    # 1. Exact (case-insensitive) match.
    row = await fetch_one(
        "SELECT id, name, domain, industry, employee_count, screening_status, people_discovered "
        "FROM omni_companies WHERE workspace_id=$1 AND LOWER(name)=LOWER($2)",
        workspace_id,
        name,
    )
    if row:
        await execute(
            "UPDATE omni_companies SET last_seen=NOW(), source_count=source_count+1, updated_at=NOW() "
            "WHERE id=$1 AND workspace_id=$2",
            row["id"],
            workspace_id,
        )
        return _to_resolved(row, created=False)

    # 2. Alias lookup.
    row = await fetch_one(
        """
        SELECT c.id, c.name, c.domain, c.industry, c.employee_count, c.screening_status, c.people_discovered
        FROM omni_company_aliases a
        JOIN omni_companies c ON c.id = a.company_id
        WHERE a.workspace_id=$1 AND LOWER(a.alias)=LOWER($2)
        LIMIT 1
        """,
        workspace_id,
        name,
    )
    if row:
        log.debug("company '%s' matched via alias -> '%s'", name, row["name"])
        return _to_resolved(row, created=False)

    # 3. Fuzzy suffix-strip + auto-alias.
    words = name.lower().split()
    if len(words) > 1:
        for suffix in _COMMON_SUFFIXES:
            if words[-1] == suffix:
                base = " ".join(words[:-1])
                row = await fetch_one(
                    "SELECT id, name, domain, industry, employee_count, screening_status, people_discovered "
                    "FROM omni_companies WHERE workspace_id=$1 AND LOWER(name)=LOWER($2) LIMIT 1",
                    workspace_id,
                    base,
                )
                if row:
                    await execute(
                        "INSERT INTO omni_company_aliases (workspace_id, company_id, alias, source) "
                        "VALUES ($1, $2, $3, 'auto_fuzzy') ON CONFLICT (workspace_id, alias) DO NOTHING",
                        workspace_id,
                        row["id"],
                        name,
                    )
                    log.info("fuzzy match '%s' -> '%s' (suffix '%s'); alias auto-created", name, row["name"], suffix)
                    return _to_resolved(row, created=False)
                break  # only the trailing suffix matters

    # 4. Create new (race-safe via the unique lower(name) index).
    cid = str(uuid.uuid4())
    await execute(
        """
        INSERT INTO omni_companies (id, workspace_id, name, domain, industry, employee_count, screening_status)
        VALUES ($1, $2, $3, $4, $5, $6, 'pending')
        ON CONFLICT (workspace_id, LOWER(name)) DO NOTHING
        """,
        cid,
        workspace_id,
        name,
        domain,
        industry,
        employee_count,
    )
    row = await fetch_one(
        "SELECT id, name, domain, industry, employee_count, screening_status, people_discovered "
        "FROM omni_companies WHERE workspace_id=$1 AND LOWER(name)=LOWER($2)",
        workspace_id,
        name,
    )
    if not row:
        raise RuntimeError(f"company resolve race lost and row vanished: {name}")
    created = str(row["id"]) == cid
    return _to_resolved(row, created=created)


async def cached_people(workspace_id: str, company_id: str, limit: int = 10) -> list[dict]:
    """Return previously discovered people for a company (the KG cache hit).
    A non-empty list means people-discovery can be skipped — zero cost."""
    rows = await fetch_all(
        "SELECT id, name, title, linkedin_url, confidence FROM omni_people_cache "
        "WHERE workspace_id=$1 AND company_id=$2 ORDER BY confidence DESC LIMIT $3",
        workspace_id,
        company_id,
        limit,
    )
    return [dict(r) for r in rows]


async def cache_person(
    workspace_id: str,
    company_id: str,
    *,
    name: str,
    title: str | None,
    linkedin_url: str | None,
    source: str,
) -> None:
    """Upsert a discovered person into the KG cache (keyed by linkedin_url)."""
    await execute(
        """
        INSERT INTO omni_people_cache (workspace_id, company_id, linkedin_url, name, title, source, last_verified)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (workspace_id, linkedin_url)
        DO UPDATE SET name=$4, title=$5, source=$6, last_verified=NOW()
        """,
        workspace_id,
        company_id,
        linkedin_url,
        name,
        title,
        source,
    )


async def mark_people_discovered(workspace_id: str, company_id: str) -> None:
    await execute(
        "UPDATE omni_companies SET people_discovered=TRUE, updated_at=NOW() WHERE id=$1 AND workspace_id=$2",
        company_id,
        workspace_id,
    )


async def set_screening_status(workspace_id: str, company_id: str, status: str) -> None:
    await execute(
        "UPDATE omni_companies SET screening_status=$3, updated_at=NOW() WHERE id=$1 AND workspace_id=$2",
        company_id,
        workspace_id,
        status,
    )


# ── Local filters / blocklist (filters.rs parity) ──────────────────────────────
_JD_REJECT_KEYWORDS: tuple[str, ...] = (
    "10,000+ employees", "10000+ employees", "fortune 500", "fortune500",
    "multinational", "listed company", "global leader", "nse:", "bse:", "nyse:",
    "nasdaq:", "conglomerate", "publicly traded", "stock exchange", "enterprise",
)
_ORG_KEYWORDS: tuple[str, ...] = (
    "government", "university", "college", "school", "hospital", "ministry",
    "public sector", "nonprofit", "ngo", "non profit", "foundation", "charity",
    "trust", "department of", "board of", "authority",
)


async def filter_company(
    workspace_id: str,
    name: str,
    *,
    description: str = "",
    industry: str = "",
    employee_count: int | None = None,
    max_employees: int = 500,
) -> tuple[bool, str]:
    """Local pre-Claude filter. Returns (passed, reason). Checks the editable DB
    blocklist + employee cap + enterprise JD keywords + org-type keywords."""
    name_l = (name or "").lower()
    blocked = await fetch_all(
        "SELECT pattern FROM omni_company_blocklist WHERE workspace_id=$1", workspace_id
    )
    for b in blocked:
        if b["pattern"] and b["pattern"].lower() in name_l:
            return False, f"blocklisted:{b['pattern']}"
    if employee_count is not None and employee_count > max_employees:
        return False, f"employee_count {employee_count} > {max_employees}"
    desc_l = (description or "").lower()
    for kw in _JD_REJECT_KEYWORDS:
        if kw in desc_l:
            return False, f"enterprise_keyword:{kw}"
    ind_l = (industry or "").lower()
    for kw in _ORG_KEYWORDS:
        if kw in name_l or kw in ind_l:
            return False, f"org_keyword:{kw}"
    return True, "ok"


# ── Company signal scoring (signal_scorer.rs parity) ───────────────────────────
def score_signals(title: str, description: str, role_count: int) -> tuple[int, list[tuple[str, int]]]:
    """Score a company's hiring signals from its job data. Returns
    (total, [(signal, score)]). Mirrors signal_scorer.rs extract_signals."""
    t = (title or "").lower()
    d = (description or "").lower()
    out: list[tuple[str, int]] = []
    if any(k in t for k in ("sdr", "sales development", "business development")):
        out.append(("hiring_sdr", 20))
    if "account executive" in t or "ae " in t:
        out.append(("hiring_ae", 15))
    if any(k in t for k in ("senior", "head of", "director of", "vp ", "vice president", "chief")):
        out.append(("hiring_senior", 15))
    if role_count >= 3:
        out.append(("multiple_roles", 20))
    if any(k in d for k in ("high-growth", "rapidly growing", "scale", "expansion")):
        out.append(("hiring_growth", 20))
    if any(k in t for k in ("founder", "co-founder", "ceo", "cto", "cmo")):
        out.append(("hiring_founder_adjacent", 10))
    return sum(s for _, s in out), out


async def persist_signals(
    workspace_id: str, company_id: str, signals: list[tuple[str, int]], source: str
) -> None:
    for signal, score in signals:
        await execute(
            "INSERT INTO omni_company_signals (workspace_id, company_id, signal, score, source) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (workspace_id, company_id, signal) DO UPDATE SET score=$4",
            workspace_id,
            company_id,
            signal,
            score,
            source,
        )


def _to_resolved(row: dict, *, created: bool) -> ResolvedCompany:
    return ResolvedCompany(
        id=str(row["id"]),
        name=row["name"],
        domain=row.get("domain"),
        industry=row.get("industry"),
        employee_count=row.get("employee_count"),
        screening_status=row.get("screening_status") or "pending",
        people_discovered=bool(row.get("people_discovered")),
        created=created,
    )
