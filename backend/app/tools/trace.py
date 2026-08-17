"""Correlation trace — reconstruct one workflow run's journey from the event log.

A v2 run is distributed across dispatcher / muscle / Flink / transitions /
projector, so a single lead's story is normally scattered across five log
streams. But every event carries a ``correlation_id`` and the projector
archives all of them into ``omni_events_archive`` (indexed on correlation_id).
This tool stitches that back into one top-to-bottom view — recovering the
legibility of a single synchronous log without giving up the distributed
substrate.

Usage (inside any backend container):
    python -m app.tools.trace <correlation_id>
    python -m app.tools.trace <correlation_id> --workspace <ws_uuid>

What it shows, in order:
    1. Event spine    — every archived event for the correlation, by time
    2. Lead lineage   — leads created under the run (parent/child fan-out)
    3. AI jobs        — screen/score/compose audit rows for the run

Known gap: muscle results (verdicts on outreach.results) are not archived —
only intent events are. The spine therefore shows what each node *requested*,
not the muscle's verdict; verdicts surface indirectly via ai_jobs + lead
routing. Archiving results is a separate follow-up.
"""

from __future__ import annotations

import argparse
import asyncio

from app.config import settings
from app.db import close_pool, fetch_all, init_pool, system_scope


def _fmt_ts(ts) -> str:
    if ts is None:
        return "??:??:??"
    return ts.strftime("%H:%M:%S.%f")[:-3]


async def _event_spine(correlation_id: str) -> list[dict]:
    async with system_scope():
        return await fetch_all(
            """
            SELECT occurred_at, event_type, entity_type, entity_id, payload
            FROM omni_events_archive
            WHERE correlation_id = $1
            ORDER BY occurred_at ASC, kafka_offset ASC
            """,
            correlation_id,
        )


async def _lead_lineage(correlation_id: str) -> list[dict]:
    # Leads don't carry correlation_id directly; we tie them via the events
    # whose entity is a lead in this correlation, then pull their lineage.
    async with system_scope():
        return await fetch_all(
            """
            WITH run_leads AS (
                SELECT DISTINCT entity_id::uuid AS lead_id
                FROM omni_events_archive
                WHERE correlation_id = $1 AND entity_type = 'lead'
                  AND entity_id IS NOT NULL
            )
            SELECT l.id, l.status, l.current_node_id, l.parent_lead_id,
                   l.origin_node_id, l.fanout_total, l.fanout_done, l.created_at
            FROM omni_leads l
            WHERE l.id IN (SELECT lead_id FROM run_leads)
               OR l.parent_lead_id IN (SELECT lead_id FROM run_leads)
            ORDER BY l.created_at ASC
            """,
            correlation_id,
        )


async def _ai_jobs(correlation_id: str) -> list[dict]:
    async with system_scope():
        return await fetch_all(
            """
            SELECT kind, status, entity_type, entity_id, model, cost_usd,
                   created_at, completed_at
            FROM omni_ai_jobs
            WHERE correlation_id = $1
            ORDER BY created_at ASC
            """,
            correlation_id,
        )


def _short(v, n: int = 8) -> str:
    return str(v)[:n] if v else "—"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Trace one workflow run by correlation_id")
    parser.add_argument("correlation_id", help="The correlation_id UUID to trace")
    args = parser.parse_args()
    cid = args.correlation_id

    await init_pool(settings.database_url)
    try:
        spine = await _event_spine(cid)
        leads = await _lead_lineage(cid)
        jobs = await _ai_jobs(cid)
    finally:
        await close_pool()

    print(f"\n══════ TRACE {cid} ══════\n")

    print(f"── EVENT SPINE ({len(spine)} events) ──")
    if not spine:
        print("  (no archived events — wrong correlation_id, or events not yet projected)")
    for e in spine:
        node = (e.get("payload") or {}).get("node_id")
        print(
            f"  {_fmt_ts(e['occurred_at'])}  {e['event_type']:<34} "
            f"entity={e['entity_type']}:{_short(e['entity_id'])}  node={_short(node)}"
        )

    print(f"\n── LEAD LINEAGE ({len(leads)} leads) ──")
    if not leads:
        print("  (no leads tied to this run)")
    for ld in leads:
        kind = "ROOT " if ld["parent_lead_id"] is None else "child"
        print(
            f"  {kind} {_short(ld['id'])}  status={ld['status']:<10} "
            f"node={_short(ld['current_node_id'])} parent={_short(ld['parent_lead_id'])} "
            f"origin={_short(ld['origin_node_id'])} fanout={ld['fanout_done']}/{ld['fanout_total']}"
        )

    print(f"\n── AI JOBS ({len(jobs)} jobs) ──")
    if not jobs:
        print("  (no ai_jobs — none ran, or projector kind mismatch)")
    for j in jobs:
        print(
            f"  {j['kind']:<8} {j['status']:<8} entity={j['entity_type']}:{_short(j['entity_id'])} "
            f"model={j.get('model') or '—'} cost=${j.get('cost_usd') or 0}"
        )

    print()


if __name__ == "__main__":
    asyncio.run(main())
