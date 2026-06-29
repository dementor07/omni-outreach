"""Audience authoring surface (OUTBOUND-FIRST-001, Layer 3-4).

The routes that make outbound-first authorable from the dashboard:
  - POST /projections/contacts — manually add a recipient (the long-missing
    "add a contact"); deterministic id so a manual add converges with a later
    source discovery (DEDUP-001);
  - GET/POST/DELETE /canvas/workflows/{id}/audience — attach/list/remove the
    contacts a campaign reaches.

Static/source-faithful checks (house style). No DB, no Kafka.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[1].parent
PROJECTIONS = (REPO / "backend/app/routers/projections.py").read_text(encoding="utf-8")
CANVAS = (REPO / "backend/app/routers/canvas.py").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^async def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


def test_create_contact_uses_deterministic_id_and_emits_event():
    body = _func_body(PROJECTIONS, "create_contact")
    # reuse the canonical deterministic id so manual + discovered contacts merge.
    assert "from app.nodes.crm.create_contact import _contact_id" in body
    assert "_contact_id(" in body
    # event-sourced: the projector owns the durable write (contact.created).
    assert 'event_type="contact.created"' in body
    # needs an email or linkedin to be reachable.
    assert "a contact needs an email or a linkedin_url" in body
    # returns the row immediately via an idempotent upsert.
    assert "ON CONFLICT (id) DO UPDATE SET" in body


def test_create_contact_is_workspace_scoped():
    body = _func_body(PROJECTIONS, "create_contact")
    assert "ctx.workspace_id" in body
    # the immediate upsert runs under system_scope (RLS) but stamps the caller's ws.
    assert "system_scope()" in body


def test_audience_routes_exist_and_are_workspace_scoped():
    assert '"/workflows/{workflow_id}/audience"' in CANVAS
    for fn in ("list_audience", "add_audience", "remove_audience"):
        body = _func_body(CANVAS, fn)
        assert "ctx.workspace_id" in body, f"{fn} must scope to the caller's workspace"


def test_add_audience_only_attaches_own_workspace_contacts():
    body = _func_body(CANVAS, "add_audience")
    # INSERT…SELECT from omni_contacts WHERE workspace_id makes a foreign id a
    # no-op instead of an FK error / cross-tenant attach.
    assert "INSERT INTO omni_campaign_audience" in body
    assert "FROM omni_contacts c" in body and "c.workspace_id=$1" in body
    assert "ON CONFLICT (workflow_id, contact_id) DO NOTHING" in body


def test_validation_reads_audience_for_run_gate():
    # the run gate (validate_saved_graph) must consult whether an audience exists
    # so an outbound-rooted campaign is runnable only once contacts are attached.
    body = _func_body(CANVAS, "validate_saved_graph")
    assert "_workflow_has_audience(" in body
    has_body = _func_body(CANVAS, "_workflow_has_audience")
    assert "omni_campaign_audience" in has_body
