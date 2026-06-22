"""Campaign Objective controller — the PURE goal-pursuit decision core.

Given a campaign's measured progress, decide: reached / widen / exhausted. This
module is intentionally I/O-free and fully unit-testable. The async control loop
that MEASURES progress, persists it, and re-seeds the workflow lives in
app.execution.objective_worker (an event-driven consumer of
``campaign.run.completed``) — NOT here, and NOT inline in the transition worker.

Measurement is LINEAGE-SCOPED: a campaign's progress counts only the entities
THIS workflow produced (via its own leads), never the whole workspace — so a
goal of "50 contacts" doesn't read pre-existing contacts or another campaign's
output as progress. See ADR campaign-objective-controller.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

log = logging.getLogger("objective_controller")

# Metrics the engine can HONESTLY measure from a campaign's own lineage. A goal
# the engine can't measure is a lie (it would read 0 and widen until exhausted),
# so the UI offers exactly these — no meetings_booked until a real calendar/deal
# signal is tied to the campaign.
MEASURABLE_METRICS = ("contacts", "qualified_leads", "companies", "replies")

DEFAULT_MAX_ITERATIONS = 5

Decision = Literal["reached", "widen", "exhausted"]


@dataclass(frozen=True)
class ControllerVerdict:
    decision: Decision
    reason: str
    next_status: str  # the objective status to persist: reached | pursuing | exhausted


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def decide(
    *,
    current: int,
    target: int,
    iterations_used: int,
    spend_usd: float,
    bounds: dict[str, Any],
    today: date | None = None,
) -> ControllerVerdict:
    """Pure goal-pursuit decision. No I/O — given the measured state + bounds,
    return whether to stop (reached/exhausted) or widen-and-re-run.

    Order matters: REACHED wins first (hitting the target mid-budget is success,
    not exhaustion). Then the bounds envelope. Only then do we widen."""
    if current >= target:
        return ControllerVerdict("reached", f"{current} >= target {target}", "reached")

    max_iter = int(bounds.get("max_iterations") or DEFAULT_MAX_ITERATIONS)
    if iterations_used >= max_iter:
        return ControllerVerdict(
            "exhausted", f"max_iterations {max_iter} spent ({current}/{target})", "exhausted"
        )

    max_spend = bounds.get("max_spend_usd")
    if max_spend is not None and spend_usd >= float(max_spend):
        return ControllerVerdict(
            "exhausted", f"spend ${spend_usd:.2f} >= cap ${float(max_spend):.2f}", "exhausted"
        )

    deadline = _as_date(bounds.get("deadline"))
    if deadline is not None and (today or datetime.now(UTC).date()) > deadline:
        return ControllerVerdict("exhausted", f"past deadline {deadline.isoformat()}", "exhausted")

    return ControllerVerdict(
        "widen", f"{current}/{target}, iteration {iterations_used + 1}/{max_iter}", "pursuing"
    )


def widen_audience(audience: dict[str, Any], iterations_used: int, entry_node_type: str = "") -> tuple[dict[str, Any], str]:
    """Pick the next sourcing move from the audience spec (v1 ladder), returned
    as config overrides for the entry node + a human summary.

    The override KEY must match the entry node's config field. Search/Apollo
    sources take ``query``; Naukri takes ``keyword``; the directory scrape takes
    ``max_results``. The audience's ``keywords`` list is the ladder: each
    widening advances the index so a re-run sources a DIFFERENT slice rather than
    re-scraping the same page. (Pragmatic v1 — richer ladders, looser geo later.)
    """
    keywords = audience.get("keywords") or []
    # Naukri's source field is `keyword`; every other source field is `query`.
    field = "keyword" if entry_node_type == "source.naukri" else "query"
    if keywords:
        idx = (iterations_used + 1) % len(keywords)
        kw = keywords[idx]
        return {field: kw}, f'widened {field} -> "{kw}"'
    # No keyword ladder: widen the result cap as the fallback (more breadth).
    cap = int(audience.get("max_results") or 25)
    return {"max_results": cap + 25}, f"widened max_results -> {cap + 25}"



# ── lineage-scoped measurement (data access the objective worker calls) ──────
# A campaign's progress counts ONLY what THIS workflow's leads produced, never
# the whole workspace. The anchor is omni_leads.workflow_id; contacts/companies
# are reached THROUGH this workflow's leads, so we never read pre-existing rows
# or another campaign's output as progress.


async def measure(workspace_id: str, metric: str, workflow_id: str) -> int:
    """Measured progress for a metric, scoped to this workflow's lineage."""
    from app.db import fetch_one, system_scope

    async with system_scope():
        if metric == "contacts":
            # A contact this campaign produced = a lead of THIS workflow that
            # reached a contact (contact_id set by crm.create_contact).
            row = await fetch_one(
                "SELECT COUNT(DISTINCT contact_id) AS n FROM omni_leads "
                "WHERE workflow_id=$1 AND workspace_id=$2 AND contact_id IS NOT NULL",
                workflow_id, workspace_id,
            )
        elif metric == "qualified_leads":
            # OBJ-METRIC-001: a QUALIFIED lead must have passed screening, not just
            # become a contact. create_contact has no screen guard and a pipeline
            # may have no ai.screen/verify node, so contact_id alone is NOT
            # qualification — that counted every raw contact as qualified. Require a
            # positive screening/verification signal on the lead's custom_fields:
            #   verification.score >= 0.5  (condition.verify_person), OR
            #   screening_status in (qualified, passed, accepted)  (ai.screen /
            #   crm.resolve_company company_resolution.screening_status).
            row = await fetch_one(
                """
                SELECT COUNT(DISTINCT contact_id) AS n FROM omni_leads
                WHERE workflow_id=$1 AND workspace_id=$2 AND contact_id IS NOT NULL
                  AND (
                    COALESCE((custom_fields->'verification'->>'score')::float, 0) >= 0.5
                    OR lower(COALESCE(custom_fields->'screening'->>'status',
                                      custom_fields->'company_resolution'->>'screening_status', ''))
                       IN ('qualified', 'passed', 'accepted', 'pass')
                  )
                """,
                workflow_id, workspace_id,
            )
        elif metric == "companies":
            # Distinct companies THIS workflow discovered. Two honest sources,
            # whichever is higher (OBJ-METRIC-002):
            #  (a) company.discovered events (entity_type='company') that
            #      crm.resolve_company emits — the authoritative record when the
            #      graph RESOLVES companies; linked to this workflow by the same
            #      correlation→archive→lead join spend() uses.
            #  (b) the for_each company children themselves — each carries a
            #      company under custom_fields.item.company_name. A discovery
            #      pipeline that has NO resolve_company node (source→for_each→
            #      people→contact) emits zero company.discovered events, so (a)
            #      read 0 and the goal widened forever despite real discovery.
            #      Counting distinct item.company_name on this workflow's leads
            #      covers that case.
            row = await fetch_one(
                """
                SELECT GREATEST(
                  (
                    SELECT COUNT(DISTINCT cd.entity_id)
                    FROM omni_events_archive cd
                    WHERE cd.workspace_id = $2
                      AND cd.event_type = 'company.discovered'
                      AND cd.correlation_id IN (
                        SELECT DISTINCT a.correlation_id
                        FROM omni_events_archive a
                        JOIN omni_leads l ON l.id = a.entity_id AND l.workspace_id = $2
                        WHERE a.entity_type = 'lead'
                          AND a.correlation_id IS NOT NULL
                          AND l.workflow_id = $1
                      )
                  ),
                  (
                    SELECT COUNT(DISTINCT lower(custom_fields->'item'->>'company_name'))
                    FROM omni_leads
                    WHERE workflow_id = $1 AND workspace_id = $2
                      AND custom_fields->'item'->>'company_name' IS NOT NULL
                      AND custom_fields->'item'->>'company_name' <> ''
                  )
                ) AS n
                """,
                workflow_id, workspace_id,
            )
        elif metric == "replies":
            # Inbound messages from contacts THIS workflow created.
            row = await fetch_one(
                "SELECT COUNT(*) AS n FROM omni_messages m WHERE m.workspace_id=$2 "
                "AND m.direction='inbound' AND m.contact_id IN "
                "(SELECT DISTINCT contact_id FROM omni_leads "
                " WHERE workflow_id=$1 AND workspace_id=$2 AND contact_id IS NOT NULL)",
                workflow_id, workspace_id,
            )
        else:
            return 0
    return int(row["n"]) if row and row["n"] is not None else 0


# OBJ-SPEND-001: a lead-gen campaign's cost is NOT just AI. The dominant spend is
# paid search-API queries (Serper). Serper bills per query; serper_people fans
# ~2 queries per (role × company). We estimate from the count of serper requests
# in this workflow's lineage. Conservative blended per-request estimate (Serper
# is ~$1/1k queries; a people node makes several). Tune as real billing lands.
_SERPER_COST_PER_REQUEST = 0.003


async def spend(workspace_id: str, workflow_id: str) -> float:
    """Total cost for THIS workflow's runs (not the whole workspace): AI cost
    (omni_ai_jobs) PLUS estimated paid search-API spend (Serper), both scoped to
    correlations whose archived lead-events belong to a lead of this workflow —
    the same lineage join the lead-journey endpoint uses.

    OBJ-SPEND-001: spend() used to be AI-only, so a max_spend_usd bound never
    tripped on the real expense (paid Serper queries). We now add an estimate for
    the workflow's serper requests so the budget guard reflects actual cost."""
    from app.db import fetch_one, system_scope

    async with system_scope():
        # lineage correlations for this workflow (shared by both cost legs)
        ai = await fetch_one(
            """
            SELECT COALESCE(SUM(j.cost_usd), 0) AS c
            FROM omni_ai_jobs j
            WHERE j.workspace_id = $2
              AND j.correlation_id IN (
                SELECT DISTINCT a.correlation_id
                FROM omni_events_archive a
                JOIN omni_leads l ON l.id = a.entity_id AND l.workspace_id = $2
                WHERE a.entity_type = 'lead'
                  AND a.correlation_id IS NOT NULL
                  AND l.workflow_id = $1
              )
            """,
            workflow_id, workspace_id,
        )
        serper = await fetch_one(
            """
            SELECT COUNT(*) AS n
            FROM omni_events_archive e
            WHERE e.workspace_id = $2
              AND e.event_type IN ('source.serper_people.requested', 'source.serper_search.requested')
              AND e.correlation_id IN (
                SELECT DISTINCT a.correlation_id
                FROM omni_events_archive a
                JOIN omni_leads l ON l.id = a.entity_id AND l.workspace_id = $2
                WHERE a.entity_type = 'lead'
                  AND a.correlation_id IS NOT NULL
                  AND l.workflow_id = $1
              )
            """,
            workflow_id, workspace_id,
        )
    ai_cost = float(ai["c"]) if ai and ai["c"] is not None else 0.0
    serper_reqs = int(serper["n"]) if serper and serper["n"] is not None else 0
    return ai_cost + serper_reqs * _SERPER_COST_PER_REQUEST
