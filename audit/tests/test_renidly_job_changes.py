"""RENIDLY-002 — the Renidly job-changes in-process source.

Locks the three things that make this source correct rather than merely
present: (1) it branches on the ENVELOPE's success, never HTTP status
(Renidly answers 200 for failures — the RENIDLY-001 lesson); (2) contact ids
reuse crm.create_contact's namespace + LinkedIn key, so a person discovered
here upserts the same row as the same person discovered anywhere else
(DEDUP-001); (3) the fan-out emits complete ready-made contacts with the
job-change trigger fields preserved.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.nodes import NodeContext, discover, get  # noqa: E402
from app.nodes.crm.create_contact import _contact_id  # noqa: E402
from app.nodes.sources import renidly_job_changes as src  # noqa: E402

discover()

_NODE = "source.renidly_job_changes"

# The live item shape (captured 2026-07-17).
_ITEM = {
    "event_type": "joined",
    "title": "Allround marketeer",
    "previous_title": "",
    "detected_at": "2026-05-01T07:38:34.178031Z",
    "effective_date": "2026-05-01T00:00:00Z",
    "profile_id": "prsn_ud3n8nicnrd9c",
    "organization_id": "org_7ounqj35nfmrq",
    "profile_handle": "scott-aben-25488517b",
    "profile_first_name": "Scott",
    "profile_last_name": "Aben",
    "profile_headline": "Marketeer",
    "profile_url": "https://linkedin.com/in/scott-aben-25488517b",
}


class _FakeResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


def _patch_http(monkeypatch, body: dict, status_code: int = 200):
    class _FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _FakeResponse(body, status_code)

    monkeypatch.setattr(src.httpx, "AsyncClient", _FakeClient)

    async def fake_key(_ws, _name):
        return "rnd-test"

    monkeypatch.setattr(src, "_resolve_api_key", fake_key)


def _ctx() -> NodeContext:
    return NodeContext(workspace_id="ws-1", workflow_id="wf", node_id="n1", lead={"id": "l1"}, config={"connection_name": "renidly"})


def test_node_registered_as_a_locally_resolved_source():
    manifest, _ = get(_NODE)
    assert {h.name for h in manifest.output_handles} == {"default", "empty", "on_error"}
    assert "connection:renidly" in manifest.capabilities
    assert manifest.entry_capable, "a source must be able to root a campaign"


@pytest.mark.asyncio
async def test_fanout_emits_ready_made_contacts_with_the_trigger_fields(monkeypatch):
    _patch_http(monkeypatch, {"success": True, "statusCode": 200, "data": [_ITEM]})
    _, execute = get(_NODE)
    result = await execute(_ctx())

    assert result.handle == "default"
    [event] = result.events
    assert event["event_type"] == "contact.created"
    payload = event["payload"]
    assert payload["first_name"] == "Scott"
    assert payload["linkedin_url"] == "https://linkedin.com/in/scott-aben-25488517b"
    cf = payload["custom_fields"]
    assert cf["job_change_event"] == "joined"
    assert cf["job_change_title"] == "Allround marketeer"
    assert cf["renidly_id"] == "prsn_ud3n8nicnrd9c"
    # The org id chains straight into renidly.company_profile — no re-resolve.
    assert cf["renidly_company_id"] == "org_7ounqj35nfmrq"


@pytest.mark.asyncio
async def test_contact_id_reuses_the_crm_namespace(monkeypatch):
    """DEDUP-001: the SAME person discovered by any source must mint the SAME
    contact id — here, the crm.create_contact LinkedIn natural key."""
    _patch_http(monkeypatch, {"success": True, "data": [_ITEM]})
    _, execute = get(_NODE)
    result = await execute(_ctx())
    expected = _contact_id("ws-1", "https://linkedin.com/in/scott-aben-25488517b", None)
    assert result.events[0]["entity_id"] == expected


@pytest.mark.asyncio
async def test_success_false_at_http_200_is_an_error_not_an_empty_pull(monkeypatch):
    """The RENIDLY-001 lesson, applied here: Renidly delivers failures at HTTP
    200; treating one as 'no events today' would silently kill the trigger."""
    _patch_http(monkeypatch, {"success": False, "statusCode": 200, "error_code": "1074", "data": None})
    _, execute = get(_NODE)
    result = await execute(_ctx())
    assert result.handle == "on_error"
    assert "1074" in (result.error or "")


@pytest.mark.asyncio
async def test_empty_data_routes_the_empty_handle(monkeypatch):
    _patch_http(monkeypatch, {"success": True, "data": []})
    _, execute = get(_NODE)
    result = await execute(_ctx())
    assert result.handle == "empty"
    assert result.events == []


@pytest.mark.asyncio
async def test_items_without_a_handle_or_name_are_skipped(monkeypatch):
    anonymous = {**_ITEM, "profile_handle": "", "profile_url": ""}
    nameless = {**_ITEM, "profile_first_name": "", "profile_last_name": "", "profile_handle": "someone-else"}
    _patch_http(monkeypatch, {"success": True, "data": [anonymous, nameless, _ITEM]})
    _, execute = get(_NODE)
    result = await execute(_ctx())
    # Only the complete item survives; the same person twice dedupes to one.
    assert len(result.events) == 1


@pytest.mark.asyncio
async def test_missing_connection_is_a_loud_error(monkeypatch):
    async def no_key(_ws, _name):
        return None

    monkeypatch.setattr(src, "_resolve_api_key", no_key)
    _, execute = get(_NODE)
    result = await execute(_ctx())
    assert result.handle == "on_error"
    assert "RENIDLY_NOT_CONNECTED" in (result.error or "")
