"""CONTACT-CAP-002: the campaign contact goal-cap must be enforced ONCE, before
contact.created is emitted, and end a capped lead through the worker's
barrier-accounting terminal path — not as a projector second-writer.

History: the cap lived in TWO places — crm.create_contact (pre-flight, emitting a
side-channel lead.sequence_ended) AND the projector _project_lead (read+null the
contact_id). The projector copy (a) terminalized outside _terminalize_lead so a
capped fan-out child never decremented its parent's barrier (stranded parent),
and (b) ran after contact.created already minted an orphan contact. The
create_contact copy had no advisory lock (parallel branches overshot).

These tests pin the consolidated fix (static/source + functional, no DB):
  1. create_contact takes the advisory lock around the cap count;
  2. on cap, create_contact emits NO contact.created (no orphan) and signals
     goal_capped via a dedicated handle/telemetry;
  3. the projector no longer enforces the cap (no objective read in _project_lead);
  4. the worker terminalizes a goal_capped create_contact via _terminalize_lead.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

CC_SRC = (ROOT / "backend/app/nodes/crm/create_contact.py").read_text(encoding="utf-8")
PROJ_SRC = (ROOT / "backend/app/projector/main.py").read_text(encoding="utf-8")
TW_SRC = (ROOT / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^async def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


def test_cap_count_is_advisory_locked_in_create_contact():
    """The cap read must hold pg_advisory_xact_lock so parallel fan-out branches
    serialize on the count instead of all reading under-target and overshooting."""
    body = _func_body(CC_SRC, "_is_contact_cap_reached")
    assert "pg_advisory_xact_lock" in body, (
        "_is_contact_cap_reached lost its advisory lock — parallel branches race the cap"
    )
    assert "lead-contact-cap:" in body, "advisory lock key changed/removed"
    assert "count(DISTINCT contact_id)" in body


def test_capped_create_contact_emits_no_contact_and_signals_goal_capped(monkeypatch):
    """On cap, the node must NOT emit contact.created (orphan) and must signal the
    worker to terminalize via goal_capped (handle + telemetry), not a bare
    lead.sequence_ended event (which would strand a fan-out parent)."""
    import app.nodes.crm.create_contact as cc
    from app.nodes import NodeContext

    async def _capped(_ws, _wf):
        return True

    monkeypatch.setattr(cc, "_is_contact_cap_reached", _capped)
    ctx = NodeContext(
        workspace_id="ws", workflow_id="wf", node_id="n1", config={},
        lead={"id": "lead-1", "custom_fields": {"item": {
            "name": "Ada Lovelace", "linkedin_url": "https://linkedin.com/in/ada",
        }}},
        correlation_id="corr",
    )
    result = asyncio.run(cc.execute(ctx))
    # No event at all on the capped path — zero orphan contacts.
    assert not result.events, "capped create_contact still emits events (orphan contact risk)"
    assert result.handle == "goal_capped"
    assert (result.telemetry or {}).get("goal_capped") is True


def test_projector_no_longer_enforces_contact_cap():
    """_project_lead must be a pure terminal-sticky upsert — no objective read, no
    cap. A second writer enforcing the cap here was the barrier-strand bug."""
    body = _func_body(PROJ_SRC, "_project_lead")
    assert "omni_campaign_objectives" not in body, (
        "projector _project_lead still reads the objective — the duplicate cap writer is back"
    )
    assert "goal_cap" not in body, "projector still stamps goal_cap (duplicate enforcement)"
    # but it must keep the terminal-sticky guard
    assert "ANY($8::text[])" in body, "terminal-sticky guard lost in the simplification"


def test_worker_terminalizes_goal_capped_via_terminalize_lead():
    """The worker must end a goal_capped create_contact through _terminalize_lead
    (barrier accounting), not a bare status write."""
    body = _func_body(TW_SRC, "_fire_node")
    cap_at = body.find('"crm.create_contact" and (result.telemetry or {}).get("goal_capped")')
    assert cap_at != -1, "worker has no goal_capped handling for crm.create_contact"
    seg = body[cap_at:cap_at + 900]
    assert "_terminalize_lead(" in seg, (
        "goal_capped lead is not terminalized via _terminalize_lead (barrier strand risk)"
    )
    assert "goal_cap" in seg, "goal_cap marker not stamped for Leads/Analytics"


def test_create_contact_still_creates_when_under_cap(monkeypatch):
    """Functional: with no objective (cap not reached), the node still emits
    contact.created from a discovered person — the cap must not break the happy path."""
    from app.nodes import NodeContext
    from app.nodes.crm import create_contact as create_contact_node

    async def _no_active_duplicate(*_args, **_kwargs):
        return None

    monkeypatch.setattr(create_contact_node, "fetch_one", _no_active_duplicate)
    create_contact = create_contact_node.execute

    # workflow_id=None skips the cap check entirely (manual/single-contact flow).
    ctx = NodeContext(
        workspace_id="ws", workflow_id=None, node_id="n1", config={},
        lead={"id": "lead-1", "custom_fields": {"item": {
            "name": "Ada Lovelace", "linkedin_url": "https://linkedin.com/in/ada",
            "company_name": "Analytical", "title": "Founder",
        }}},
        correlation_id="corr",
    )
    result = asyncio.run(create_contact(ctx))
    assert result.error is None
    assert any(e["event_type"] == "contact.created" for e in result.events)
    assert result.handle == "default"
