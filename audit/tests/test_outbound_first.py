"""Outbound-first / any-start campaigns (OUTBOUND-FIRST-001).

The product promise is: lead-gen OR outbound OR any mix, fully customizable. The
engine had drifted to assume every campaign BEGINS by discovering leads from a
source — the validator forbade any non-source root (ENTRY_NOT_SOURCE) and
seed_and_run seeded one empty root lead ("the source discovers entities"). So
"reach out to a known list of people" was impossible to run.

This restores any-start across the layers and pins each so it can't regress:
  - NodeManifest.entry_capable declares which nodes may root a campaign
    (sources always; the 7 person-addressable channels too);
  - the validator allows an entry-capable root, and requires an attached
    audience for an outbound (non-source) root (OUTBOUND_NEEDS_AUDIENCE);
  - seed_and_run enrolls one lead PER audience contact (with contact_id +
    recipient identity) when the entry node is outbound;
  - migration 048 adds the omni_campaign_audience binding (RLS system-aware,
    since the runner reads it under system_scope()).

Static + functional checks (house style). No DB, no Kafka.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import app.nodes as noderegistry  # noqa: E402
from app.services.graph_validation import validate_graph  # noqa: E402

noderegistry.discover()

REPO = Path(__file__).resolve().parents[1].parent
RUN_SRC = (REPO / "backend/app/execution/run.py").read_text(encoding="utf-8")
MIGRATION = (REPO / "backend/alembic/versions/048_campaign_audience.py").read_text(encoding="utf-8")


def _n(node_type: str, config: dict | None = None) -> dict:
    return {"id": str(uuid.uuid4()), "node_type": node_type, "config": config or {}}


def _e(src: dict, tgt: dict, handle: str = "default") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "source_node_id": src["id"],
        "target_node_id": tgt["id"],
        "source_handle": handle,
    }


# ── entry-capability model ────────────────────────────────────────────────────


def test_sources_and_person_channels_are_entry_capable():
    from app.nodes import get

    for t in ("source.searxng", "source.serper_people"):
        assert get(t)[0].entry_capable, f"{t} (a source) must be entry-capable"
    for t in (
        "channel.linkedin", "channel.email", "channel.sms",
        "channel.whatsapp", "channel.instagram", "channel.telegram", "channel.voice",
    ):
        assert get(t)[0].entry_capable, f"{t} must be entry-capable (can start an outbound campaign)"


def test_non_addressable_nodes_are_not_entry_capable():
    from app.nodes import get

    # conditions/flow/crm/events and the non-person channels can't ROOT a campaign.
    for t in (
        "condition.replied", "flow.delay", "crm.create_contact",
        "event.invite_accepted", "channel.slack", "channel.webhook_out",
    ):
        assert not get(t)[0].entry_capable, f"{t} must NOT be entry-capable"


# ── validator: any-start, audience-gated for outbound ─────────────────────────


def test_outbound_root_without_audience_is_blocked():
    inv = _n("channel.linkedin", {"mode": "invite", "message_template": "hi"})
    end = _n("flow.end")
    result = validate_graph([inv, end], [_e(inv, end, "sent")], has_audience=False)
    codes = {i["code"] for i in result["issues"]}
    assert "OUTBOUND_NEEDS_AUDIENCE" in codes
    assert result["valid_for_run"] is False
    # but it's SAVEABLE (config-scope error, not structural) — you can build it,
    # you just can't run it until you attach an audience.
    assert result["valid_for_save"] is True


def test_outbound_root_with_audience_is_runnable():
    inv = _n("channel.linkedin", {"mode": "invite", "message_template": "hi"})
    end = _n("flow.end")
    result = validate_graph([inv, end], [_e(inv, end, "sent")], has_audience=True)
    assert result["valid_for_run"] is True, [i["code"] for i in result["issues"]]


def test_source_root_still_runnable_without_audience():
    # lead-gen is unchanged: a source root needs no audience.
    src = _n("source.searxng", {"query": "fintech founders"})
    end = _n("flow.end")
    # source.searxng emits default/empty/on_error; wire default to end.
    result = validate_graph([src, end], [_e(src, end, "default")], has_audience=False)
    codes = {i["code"] for i in result["issues"]}
    assert "OUTBOUND_NEEDS_AUDIENCE" not in codes
    assert "ENTRY_NOT_CAPABLE" not in codes


def test_non_entry_root_is_a_wiring_error():
    # a condition with no incoming edge can't start a campaign.
    cond = _n("condition.replied", {"window_days": 30})
    end = _n("flow.end")
    result = validate_graph([cond, end], [_e(cond, end, "true")], has_audience=True)
    codes = {i["code"] for i in result["issues"]}
    assert "ENTRY_NOT_CAPABLE" in codes
    assert result["valid_for_run"] is False
    # the old blanket code is gone.
    assert "ENTRY_NOT_SOURCE" not in codes


def test_mixed_start_source_plus_outbound_with_audience():
    # a campaign may run a source AND an outbound root together (any mix).
    src = _n("source.searxng", {"query": "x"})
    inv = _n("channel.linkedin", {"mode": "invite", "message_template": "hi"})
    end = _n("flow.end")
    end2 = _n("flow.end")
    edges = [_e(src, end, "default"), _e(inv, end2, "sent")]
    result = validate_graph([src, inv, end, end2], edges, has_audience=True)
    assert result["valid_for_run"] is True, [i["code"] for i in result["issues"]]


# ── seeding wiring: outbound root enrolls the audience ────────────────────────


def test_seed_enrolls_one_lead_per_audience_contact():
    # seed_and_run_audience seeds a lead per contact WITH contact_id + identity.
    body = _func_body(RUN_SRC, "seed_and_run_audience")
    assert "for contact in contacts" in body
    assert "contact_id" in body and "_contact_to_lead_fields(contact)" in body
    # the lead is bound to its contact (not contact_id=NULL like the source path).
    assert "INSERT INTO omni_leads" in body and "$3" in body  # contact_id positional


def test_seed_and_run_many_routes_outbound_roots_to_audience():
    body = _func_body(RUN_SRC, "seed_and_run_many")
    # a non-source root enrolls the attached audience; a source root keeps the
    # empty-root discover path.
    assert "_is_source_node(root[\"node_type\"])" in body
    assert "seed_and_run_audience(" in body
    assert "_audience_contacts(" in body
    # an outbound root with no audience is a clear error, not a silent empty run.
    assert "no attached audience" in body


def test_audience_read_is_system_scope_safe():
    # the runner reads the audience under system_scope(); the helper must use it.
    body = _func_body(RUN_SRC, "_audience_contacts")
    assert "system_scope()" in body
    assert "omni_campaign_audience" in body


# ── migration shape ───────────────────────────────────────────────────────────


def test_migration_audience_is_rls_system_aware():
    assert 'revision = "048"' in MIGRATION and 'down_revision = "047"' in MIGRATION
    assert "CREATE TABLE IF NOT EXISTS omni_campaign_audience" in MIGRATION
    assert "PRIMARY KEY (workflow_id, contact_id)" in MIGRATION
    # read by the runner under system_scope() — MUST permit app_is_system().
    assert "app_current_workspace() OR app_is_system()" in MIGRATION
    assert "ENABLE ROW LEVEL SECURITY" in MIGRATION and "FORCE ROW LEVEL SECURITY" in MIGRATION
    assert "GRANT ALL PRIVILEGES ON omni_campaign_audience TO omni_app_role" in MIGRATION
    # contact delete cleanly drops it from every audience.
    assert "REFERENCES omni_contacts(id) ON DELETE CASCADE" in MIGRATION


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^async def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)
