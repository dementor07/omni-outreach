"""MSG-CAMPAIGN-001 — a recorded message carries the campaign it belongs to.

``omni_messages`` held only ``contact_id``, and contacts are shared across
campaigns, so "replies for campaign N" could not be asked. Answering it by
joining through ``omni_leads`` on ``contact_id`` counts every other campaign
that ever touched the same person -- the exact error that reported Campaign 3
as having a reply when it had none.

These lock the three things that make the column trustworthy: the DSL can
express a campaign-scoped reply query, the attribution rule prefers the
campaign that actually last spoke to the contact, and BOTH writers persist the
column (a writer that forgets it makes every new row silently unattributable).
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import inbound_reply as ir
from app.services.view_query import QuerySpec, build_query, entity_catalog

WS = "11111111-1111-1111-1111-111111111111"
CONTACT = "22222222-2222-2222-2222-222222222222"
CAMPAIGN_A = "33333333-3333-3333-3333-333333333333"
CAMPAIGN_B = "44444444-4444-4444-4444-444444444444"


@contextlib.asynccontextmanager
async def _fake_scope():
    yield


# ── The DSL can express the question at all ─────────────────────────────────


def test_messages_entity_exposes_the_campaign():
    """Without this column in the whitelist a campaign-scoped reply widget is
    unbuildable -- the view falls back to a workspace-wide number that reads as
    if it belonged to the campaign."""
    assert "workflow_id" in entity_catalog()["entities"]["messages"]["fields"]


def test_campaign_scoped_reply_query_compiles():
    built = build_query(QuerySpec(
        entity="messages",
        filters=[{"field": "direction", "op": "eq", "value": "inbound"},
                 {"field": "workflow_id", "op": "eq", "value": CAMPAIGN_A}],
        metrics=[{"fn": "count_distinct", "field": "contact_id", "alias": "people"}],
    ))
    assert "workflow_id" in built.sql
    # The campaign id travels as a bind parameter, never spliced into the SQL.
    assert CAMPAIGN_A not in built.sql
    assert any(str(p) == CAMPAIGN_A for p in built.params)


# ── Attribution: a reply belongs to whoever last spoke to them ──────────────


@pytest.mark.asyncio
async def test_reply_is_attributed_to_the_last_campaign_that_sent(monkeypatch):
    async def fake_fetch_one(query, *args):
        assert "omni_send_outcomes" in query
        return {"workflow_id": CAMPAIGN_A}

    monkeypatch.setattr(ir, "system_scope", _fake_scope)
    monkeypatch.setattr(ir, "fetch_one", fake_fetch_one)
    assert await ir._resolve_campaign(WS, CONTACT) == CAMPAIGN_A


@pytest.mark.asyncio
async def test_falls_back_to_the_contacts_sole_campaign(monkeypatch):
    """No send history -- but if the contact lives in exactly one campaign there
    is only one answer it could be."""
    calls = []

    async def fake_fetch_one(query, *args):
        calls.append(query)
        if "omni_send_outcomes" in query:
            return None
        return {"workflow_id": CAMPAIGN_B}

    monkeypatch.setattr(ir, "system_scope", _fake_scope)
    monkeypatch.setattr(ir, "fetch_one", fake_fetch_one)
    assert await ir._resolve_campaign(WS, CONTACT) == CAMPAIGN_B
    assert any("omni_leads" in q for q in calls)


@pytest.mark.asyncio
async def test_ambiguous_contact_stays_unattributed(monkeypatch):
    """The HAVING COUNT(DISTINCT)=1 guard returns no row when the contact sits
    in several campaigns. None is the correct answer -- picking one would
    inflate whichever campaign happened to sort first."""
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(ir, "system_scope", _fake_scope)
    monkeypatch.setattr(ir, "fetch_one", fake_fetch_one)
    assert await ir._resolve_campaign(WS, CONTACT) is None


@pytest.mark.asyncio
async def test_inbound_event_payload_carries_the_campaign(monkeypatch):
    """The event payload is the ONLY channel the projector has -- if the
    campaign is missing here the column is NULL no matter what the DB allows."""
    published = []

    async def fake_publish(events):
        published.extend(events)

    async def fake_fetch_one(query, *args):
        return {"workflow_id": CAMPAIGN_A}

    async def fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(ir, "system_scope", _fake_scope)
    monkeypatch.setattr(ir, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(ir, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(ir.bus, "publish_events", fake_publish)

    await ir.process_reply(WS, CONTACT, "sure, happy to chat")

    assert len(published) == 1
    assert published[0]["payload"]["workflow_id"] == CAMPAIGN_A


# ── Both writers must persist it ────────────────────────────────────────────


@pytest.mark.parametrize("path", [
    "backend/app/execution/transition_worker.py",
    "backend/app/projector/main.py",
])
def test_every_message_writer_persists_the_campaign(path):
    """Source-level lock. There are exactly two INSERTs into omni_messages; a
    third writer, or either of these losing the column, makes new rows
    unattributable while every existing test still passes."""
    src = (ROOT / path).read_text(encoding="utf-8")
    idx = src.find("INSERT INTO omni_messages")
    assert idx != -1, f"{path} no longer writes omni_messages -- update this lock"
    stmt = src[idx:idx + 400]
    assert "workflow_id" in stmt, f"{path} INSERT dropped workflow_id"
