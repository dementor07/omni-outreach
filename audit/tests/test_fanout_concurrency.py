"""Deterministic concurrency harness for the for_each fan-out (E2E-001/002).

The live bug could not be reproduced reliably by re-running paid scrapes: under
Kafka at-least-once delivery the source result arrived ~5× and the symptoms
flipped between "20 duplicate children" (E2E-001) and "0 children despite a full
collection" (E2E-002). This harness reproduces BOTH deterministically with an
in-memory leads store that honours the same atomic-claim semantics as Postgres
(``UPDATE ... WHERE fanout_total IS NULL RETURNING`` is row-locked), then drives
N concurrent ``_fan_out`` calls via ``asyncio.gather`` and asserts:

  * exactly ONE wave wins the claim (no duplicate children), and
  * the winner reads the collection AFTER the mutation landed (read-after-write),
    so it spawns the right number of children even when the snapshot it was
    handed was stale.

No Postgres, no network — pure asyncio. It tests the worker's claim + fresh-read
logic, which is exactly where the two bugs lived.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.execution import transition_worker as tw  # noqa: E402


class FakeLeads:
    """In-memory omni_leads with row-atomic claim semantics + child inserts."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.children: list[dict] = []
        self._lock = asyncio.Lock()  # serialises the read-modify-write claim

    def seed_parent(self, lead_id: str, custom_fields: dict):
        self.rows[lead_id] = {
            "id": lead_id,
            "workspace_id": "ws",
            "current_node_id": None,
            "status": "active",
            "fanout_total": None,
            "fanout_done": 0,
            "custom_fields": custom_fields,
            "contact_id": None,
            "workflow_id": "wf",
            "parent_lead_id": None,
            "origin_node_id": None,
        }


@contextlib.asynccontextmanager
async def _fake_scope():
    yield


def install(monkeypatch, store: FakeLeads):
    """Wire the worker's module-level DB calls to the in-memory store. Only the
    SQL shapes _fan_out actually issues are handled; anything else raises so the
    test fails loud instead of silently passing on an unmocked path."""

    async def fake_fetch_one(sql: str, *args):
        s = " ".join(sql.split())
        # The atomic claim: UPDATE ... fanout_total=-1 ... WHERE fanout_total IS NULL RETURNING id
        if "fanout_total=-1" in s and "fanout_total IS NULL RETURNING id" in s:
            for_each_id, lead_id, ws = args
            async with store._lock:
                row = store.rows.get(lead_id)
                if not row or row["fanout_total"] is not None:
                    return None  # already claimed — lose the race
                row["fanout_total"] = -1
                row["current_node_id"] = for_each_id
                row["status"] = "waiting"
                return {"id": lead_id}
        # Read-after-write fresh custom_fields read.
        if s.startswith("SELECT custom_fields FROM omni_leads WHERE id="):
            lead_id, ws = args
            row = store.rows.get(lead_id)
            return {"custom_fields": row["custom_fields"]} if row else None
        raise AssertionError(f"unexpected fetch_one: {s}")

    async def fake_execute(sql: str, *args):
        s = " ".join(sql.split())
        # Parking UPDATE: sets the real fanout_total.
        if "SET current_node_id=$1, status='waiting', fanout_total=$2" in s:
            for_each_id, total, lead_id, ws = args
            store.rows[lead_id]["fanout_total"] = total
            return
        # E2E-002 claim RELEASE: collection empty, await the mutation. Resets
        # fanout_total to NULL + bumps the retry counter so a later delivery
        # re-claims and fans out for real.
        if "SET fanout_total=NULL, status='active'" in s:
            patch_json, lead_id, ws = args
            row = store.rows[lead_id]
            row["fanout_total"] = None
            row["status"] = "active"
            row["custom_fields"] = {**row["custom_fields"], **json.loads(patch_json)}
            return
        # Child INSERT.
        if "INSERT INTO omni_leads" in s:
            store.children.append({"id": args[0], "custom_fields": args[5]})
            return
        raise AssertionError(f"unexpected execute: {s}")

    async def fake_outgoing_edge(ws, node_id, handle):
        if handle == "each":
            return {"target_node_id": "screen-node"}
        return None  # no done/empty edge needed for the success path

    async def fake_node_row(ws, node_id):
        return {"id": node_id, "node_type": "ai.screen_company", "config": {}, "workflow_id": "wf"}

    async def fake_lead_with_contact(ws, lead_id):
        # children are fired via _fire_node, which we stub to a no-op
        return {"id": lead_id, "custom_fields": {}}, None

    async def fake_ancestor(ws, parent, fid):
        return (False, str(parent["id"]))

    async def fake_descendant_count(ws, root_id):
        return 0

    async def fake_fire_node(*a, **k):
        return None

    monkeypatch.setattr(tw, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(tw, "execute", fake_execute)
    monkeypatch.setattr(tw, "system_scope", _fake_scope)
    monkeypatch.setattr(tw, "_outgoing_edge", fake_outgoing_edge)
    monkeypatch.setattr(tw, "_node_row", fake_node_row)
    monkeypatch.setattr(tw, "_lead_with_contact", fake_lead_with_contact)
    monkeypatch.setattr(tw, "_ancestor_visited_for_each", fake_ancestor)
    monkeypatch.setattr(tw, "_descendant_count_for_root", fake_descendant_count)
    monkeypatch.setattr(tw, "_fire_node", fake_fire_node)


@pytest.mark.asyncio
async def test_concurrent_fan_out_spawns_one_wave(monkeypatch):
    """E2E-001: N concurrent/redelivered fan-outs of the same parent must spawn
    exactly ONE wave (max_items children), not N waves."""
    store = FakeLeads()
    companies = [{"company_name": f"Co{i}"} for i in range(5)]
    store.seed_parent("p1", {"companies": companies})
    install(monkeypatch, store)

    for_each = {"id": "fe1", "config": {"items_key": "companies", "item_field": "item", "max_items": 5}}
    # Five redelivered transitions race into _fan_out simultaneously.
    parent_snapshot = {**store.rows["p1"]}
    await asyncio.gather(*[
        tw._fan_out("ws", parent_snapshot, for_each, "corr") for _ in range(5)
    ])

    assert store.rows["p1"]["fanout_total"] == 5, store.rows["p1"]["fanout_total"]
    assert len(store.children) == 5, f"expected 5 children, got {len(store.children)}"


@pytest.mark.asyncio
async def test_fan_out_reads_collection_after_write(monkeypatch):
    """E2E-002: the winning delivery may carry a STALE snapshot (taken before the
    company-list mutation landed). _fan_out must re-read custom_fields fresh from
    the store, so it spawns children from the committed collection, not the empty
    snapshot it was handed."""
    store = FakeLeads()
    # DB has the full collection (mutation already committed)...
    store.seed_parent("p2", {"companies": [{"company_name": f"Co{i}"} for i in range(3)]})
    install(monkeypatch, store)

    for_each = {"id": "fe2", "config": {"items_key": "companies", "item_field": "item", "max_items": 10}}
    # ...but the transition handed _fan_out a snapshot with NO companies yet.
    stale_snapshot = {**store.rows["p2"], "custom_fields": {}}
    await tw._fan_out("ws", stale_snapshot, for_each, "corr")

    # Read-after-write: it must have used the DB's 3 companies, not the empty arg.
    assert store.rows["p2"]["fanout_total"] == 3, store.rows["p2"]["fanout_total"]
    assert len(store.children) == 3, f"expected 3 children from fresh read, got {len(store.children)}"


@pytest.mark.asyncio
async def test_fan_out_releases_claim_when_collection_not_yet_arrived(monkeypatch):
    """E2E-002 (delivery ordering): the for_each-routing transition can arrive
    BEFORE the source's collection mutation (separate at-least-once envelopes).
    Delivery #1 wins the claim but the DB collection is still empty -> it must
    RELEASE the claim (fanout_total back to NULL) rather than route to done with
    zero leads. Delivery #2, arriving after the mutation landed, then re-claims
    and fans out the real count. Without the release, a full scrape strands at
    zero children (the exact live E2E-002 symptom)."""
    store = FakeLeads()
    store.seed_parent("p3", {})  # collection NOT present yet
    install(monkeypatch, store)
    for_each = {"id": "fe3", "config": {"items_key": "companies", "item_field": "item", "max_items": 10}}

    # Delivery #1: routing transition arrives first, collection empty.
    await tw._fan_out("ws", {**store.rows["p3"]}, for_each, "corr")
    assert store.rows["p3"]["fanout_total"] is None, "claim must be released, not consumed"
    assert len(store.children) == 0
    assert store.rows["p3"]["custom_fields"].get("_fanout_retry") == 1

    # The collection mutation now lands (a later result envelope).
    store.rows["p3"]["custom_fields"]["companies"] = [{"company_name": "A"}, {"company_name": "B"}]

    # Delivery #2: re-claims (fanout_total is NULL again) and fans out for real.
    await tw._fan_out("ws", {**store.rows["p3"]}, for_each, "corr")
    assert store.rows["p3"]["fanout_total"] == 2, store.rows["p3"]["fanout_total"]
    assert len(store.children) == 2, f"expected 2 children after mutation landed, got {len(store.children)}"
