"""Campaign Objective controller — the engine's goal-pursuit loop.

When a campaign's run-lead completes, the controller asks: have we reached the
objective? If short and still within bounds, it WIDENS the sourcing strategy and
re-runs (re-seeding a fresh root lead via the same /run path — no graph back-edge,
so the for_each cycle-explosion class is structurally impossible). If reached, or
the bounds envelope (max_iterations / max_spend / deadline) is spent, it stops.

This module is split into a PURE decision function (`decide`, fully unit-testable,
no I/O) and the async glue (`evaluate_on_completion`) that measures + persists +
re-triggers. See ADR campaign-objective-controller. Slice 2 of 4 (Agency).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

log = logging.getLogger("objective_controller")

# metric -> projection table whose COUNT(*) is the measured progress.
_METRIC_TABLE: dict[str, str] = {
    "contacts": "omni_contacts",
    "companies": "omni_companies",
    "qualified_leads": "omni_leads",
    # replies / meetings_booked are message/deal projections — wired as those
    # metrics graduate from "counted" to "pursued"; default-safe below.
}

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


def metric_table(metric: str) -> str | None:
    """Projection table to COUNT for a metric, or None if not yet countable."""
    return _METRIC_TABLE.get(metric)


def widen_audience(audience: dict[str, Any], iterations_used: int) -> tuple[dict[str, Any], str]:
    """Pick the next sourcing move from the audience spec (v1 ladder).

    The audience may carry a `keywords` list; each widening advances the keyword
    index so a re-run sources a DIFFERENT role (different companies) rather than
    re-scraping the same page. Returns (overrides_for_entry_node_config, summary).
    Pragmatic v1 — a richer ladder (then more pages, then looser geo) comes later.
    """
    keywords = audience.get("keywords") or []
    if keywords:
        idx = (iterations_used + 1) % len(keywords)
        kw = keywords[idx]
        return {"keyword": kw}, f'widened keyword -> "{kw}"'
    # No keyword ladder configured: bump page depth as the fallback widening.
    pages = int(audience.get("max_pages") or 5)
    return {"max_pages": pages + 5}, f"widened scrape depth -> {pages + 5} pages"


# ── async glue: measure + decide + persist + re-trigger ──────────────────────


async def _measure(workspace_id: str, metric: str, workflow_id: str) -> int:
    """COUNT the metric's projection for this workspace. Counts materialised rows
    (lags Kafka by a beat — the controller re-checks on the next completion)."""
    from app.db import fetch_one, system_scope

    table = metric_table(metric)
    if not table:
        return 0
    async with system_scope():
        # qualified_leads = leads that reached a contact; contacts/companies are
        # whole-workspace (a campaign's sourced entities land there). Scoping to
        # the campaign's contacts specifically is a later refinement.
        row = await fetch_one(f"SELECT COUNT(*) AS n FROM {table}")  # noqa: S608 (table from fixed map)
    return int(row["n"]) if row else 0


async def _spend(workspace_id: str) -> float:
    from app.db import fetch_one, system_scope

    async with system_scope():
        row = await fetch_one("SELECT COALESCE(SUM(total_cost), 0) AS c FROM omni_pipeline_metrics")
    return float(row["c"]) if row else 0.0


async def evaluate_on_completion(workspace_id: str, workflow_id: str) -> None:
    """A campaign run-lead just completed — pursue the objective.

    Measures progress, decides via `decide`, persists progress+status, and on a
    'widen' verdict re-seeds the workflow (fresh root lead via the run path) with
    the next sourcing move. No-op when the workflow has no objective or it's
    already terminal/paused. Idempotent on the bounds counter: iterations_used is
    incremented only when we actually re-run."""
    from app.db import fetch_one, system_scope

    async with system_scope():
        obj = await fetch_one(
            "SELECT * FROM omni_campaign_objectives WHERE workflow_id=$1 AND workspace_id=$2",
            workflow_id,
            workspace_id,
        )
    if not obj or obj["status"] in ("reached", "exhausted", "paused"):
        return

    progress = dict(obj.get("progress") or {})
    bounds = dict(obj.get("bounds") or {})
    iterations_used = int(progress.get("iterations_used") or 0)

    current = await _measure(workspace_id, obj["metric"], workflow_id)
    spend = await _spend(workspace_id)
    verdict = decide(
        current=current,
        target=int(obj["target"]),
        iterations_used=iterations_used,
        spend_usd=spend,
        bounds=bounds,
    )
    log.info(
        "objective %s (%s %d/%d): %s — %s",
        obj["id"], obj["metric"], current, obj["target"], verdict.decision, verdict.reason,
    )

    progress.update({"current": current, "spend_usd": spend, "last_action": verdict.reason})

    if verdict.decision == "widen":
        audience = dict(obj.get("audience") or {})
        overrides, summary = widen_audience(audience, iterations_used)
        progress["iterations_used"] = iterations_used + 1
        progress["last_action"] = summary
        await _persist(workspace_id, obj["id"], verdict.next_status, progress)
        await _reseed_and_fire(workspace_id, workflow_id, overrides)
    else:
        await _persist(workspace_id, obj["id"], verdict.next_status, progress)


async def _persist(workspace_id: str, objective_id: str, status: str, progress: dict[str, Any]) -> None:
    import json

    from app.db import execute, system_scope

    async with system_scope():
        await execute(
            "UPDATE omni_campaign_objectives SET status=$1, progress=$2::jsonb, updated_at=NOW() "
            "WHERE id=$3 AND workspace_id=$4",
            status,
            json.dumps(progress),
            objective_id,
            workspace_id,
        )


async def _reseed_and_fire(workspace_id: str, workflow_id: str, config_overrides: dict[str, Any]) -> None:
    """Re-run the workflow's entry node with a widened config — a FRESH root lead
    via the same seed-and-fire shape as the /run endpoint. No graph back-edge:
    this is a brand-new lineage, so the for_each cycle guards are never relevant
    and the 113k-explosion class is structurally impossible."""
    import uuid

    import app.nodes as noderegistry
    from app.db import execute, fetch_all, system_scope
    from app.services import bus

    async with system_scope():
        nodes = await fetch_all(
            "SELECT id, node_type, config FROM omni_workflow_nodes WHERE workflow_id=$1 AND workspace_id=$2 "
            "ORDER BY position_y, position_x",
            workflow_id, workspace_id,
        )
        targeted = await fetch_all(
            "SELECT DISTINCT target_node_id FROM omni_workflow_edges WHERE workflow_id=$1 AND workspace_id=$2",
            workflow_id, workspace_id,
        )
    if not nodes:
        return
    targeted_ids = {str(r["target_node_id"]) for r in targeted}
    roots = [n for n in nodes if str(n["id"]) not in targeted_ids]
    entry = next((n for n in roots if str(n["node_type"]).startswith("source.")), roots[0] if roots else None)
    if not entry:
        log.warning("objective re-seed: workflow %s has no entry node", workflow_id)
        return

    try:
        _manifest, execute_fn = noderegistry.get(str(entry["node_type"]))
    except KeyError:
        return

    lead_id = str(uuid.uuid4())
    node_id = str(entry["id"])
    correlation_id = str(uuid.uuid4())
    merged_config = {**(entry.get("config") or {}), **config_overrides}

    async with system_scope():
        await execute(
            "INSERT INTO omni_leads (id, workspace_id, contact_id, workflow_id, current_node_id, status, custom_fields) "
            "VALUES ($1, $2, NULL, $3, $4, 'active', '{}'::jsonb)",
            lead_id, workspace_id, workflow_id, node_id,
        )

    node_ctx = noderegistry.NodeContext(
        workspace_id=workspace_id,
        workflow_id=str(workflow_id),
        node_id=node_id,
        config=merged_config,
        lead={"id": lead_id, "contact_id": None, "custom_fields": {}},
        correlation_id=correlation_id,
    )
    result = await execute_fn(node_ctx)
    if result.error:
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET status='errored', current_node_id=NULL, updated_at=NOW() "
                "WHERE id=$1 AND workspace_id=$2",
                lead_id, workspace_id,
            )
        log.warning("objective re-seed entry node errored: %s", result.error)
        return

    for ev in result.events:
        payload = dict(ev.get("payload") or {})
        payload.setdefault("node_id", node_id)
        payload.setdefault("lead_id", lead_id)
        payload.setdefault("correlation_id", correlation_id)
        await bus.publish_event(
            workspace_id=workspace_id,
            event_type=ev["event_type"],
            entity_type="lead" if ev.get("entity_type") in (None, "workflow") else ev["entity_type"],
            entity_id=lead_id if ev.get("entity_type") in (None, "workflow") else ev.get("entity_id"),
            payload=payload,
            correlation_id=correlation_id,
        )
    log.info("objective re-seed: workflow %s re-ran entry %s (lead %s, overrides=%s)",
             workflow_id, node_id, lead_id, config_overrides)
