"""Score-based person identity verification + multi-signal lead scoring.

Ported from omni_outreach_v3 discovery.rs (is_company_mismatch fast-path +
compute_person_score) and plan.md Phase 1/5 (score-based verification, weighted
lead scoring). Pure functions — no I/O — so they run inside a condition node with
no DB handle. The point: cheap Rust-equivalent screening BEFORE the paid Claude
call, and a weighted score so even a Claude ACCEPT can be vetoed on weak signals.
"""

from __future__ import annotations

_EXCLUDE = ("linkedin", "linkedin.com", "linkedin profile")


def is_company_mismatch(title: str, target_company: str) -> bool:
    """Fast-path: if the title explicitly names a DIFFERENT company (via '@' or
    ' at '), reject without calling Claude. Only '@'/' at ' are reliable company
    indicators — '|', '//', '·' usually separate roles, not companies."""
    lt = (title or "").lower()
    tgt = (target_company or "").lower()
    if not lt or not tgt:
        return False
    for sep in ("@", " at "):
        idx = lt.find(sep)
        if idx == -1:
            continue
        after = lt[idx + len(sep):].strip()
        mentioned = ""
        for ch in after:
            if ch in ",.;-·|":
                break
            mentioned += ch
        mentioned = mentioned.strip()
        if len(mentioned) > 3 and mentioned != tgt and mentioned not in _EXCLUDE:
            stripped = mentioned.rstrip().rstrip("".join(c for c in mentioned if not c.isalnum()))
            if (
                stripped
                and stripped != tgt
                and tgt not in stripped
                and stripped not in tgt
                and stripped not in _EXCLUDE
            ):
                return True
    return False


def person_title_score(title: str) -> int:
    """0-100 decision-maker seniority score (discovery.rs compute_person_score)."""
    t = (title or "").lower()
    score = 40  # base for a verified decision-maker
    if any(k in t for k in (
        "ceo",
        "chief executive officer",
        "founder",
        "co-founder",
        "cto",
        "chief technology officer",
        "managing director",
    )):
        score += 25
    elif any(k in t for k in ("cmo", "vp", "vice president")):
        score += 20
    elif any(k in t for k in ("director", "head of")):
        score += 15
    if any(k in t for k in ("sales", "growth", "business development")):
        score += 10
    return min(score, 100)


def verification_score(
    *,
    title: str,
    target_company: str,
    snippet: str | None,
    linkedin_url: str | None,
    domain_known: bool,
    kg_known: bool,
) -> tuple[int, list[tuple[str, int]]]:
    """Multi-signal lead score (plan.md Phase 1+5). Returns (total, breakdown).

    Weights mirror the plan: snippet names target +40, wrong company -30, KG
    prior sighting +35, LinkedIn URL present +20, domain verified +10,
    decision-maker title +5 bonus.
    """
    breakdown: list[tuple[str, int]] = []
    tgt = (target_company or "").lower()
    snip = (snippet or "").lower()

    if snip and tgt and tgt in snip:
        breakdown.append(("snippet_match", 40))
    elif snip and is_company_mismatch(title, target_company):
        breakdown.append(("wrong_company", -30))
    if kg_known:
        breakdown.append(("kg_prior_sighting", 35))
    if linkedin_url:
        breakdown.append(("linkedin_url", 20))
    if domain_known:
        breakdown.append(("domain_verified", 10))
    # Seniority bonus, graduated by title (person_title_score): a CEO/founder is
    # worth more than a generic "director". Scaled into a 0-10 band so it stays
    # proportional to the other signals (was a flat +5 for any decision-maker).
    seniority = person_title_score(title)  # 40 base .. 100
    if seniority > 40:
        breakdown.append(("decision_maker_title", round((seniority - 40) / 60 * 10)))

    return sum(s for _, s in breakdown), breakdown
