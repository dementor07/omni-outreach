"""Congruity invariants — encode the cross-boundary contracts whose drift caused
the 2026-06-08 audit findings, so the same class of bug can't silently return.

Each test is a runtime-faithful proxy for a contract that spans two parts of the
system (dispatcher↔node config, Pydantic↔DB CHECK, Python enum↔Rust enum). They
open no DB connection — pure static/registry checks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.core.events import ChannelType  # noqa: E402
from app.execution import dispatcher  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


# ── C1: channel.linkedin mode must route to the matching muscle channel ────────
def test_linkedin_mode_routes_to_distinct_channels():
    """REGRESSION C1: the dispatcher must map channel.linkedin + payload.mode to
    the mode-specific ChannelType. The bug was a static NODE_CHANNEL value that
    sent every mode as a DM."""
    expected = {
        "invite": ChannelType.LINKEDIN_INVITE,
        "dm": ChannelType.LINKEDIN_DM,
        "inmail": ChannelType.LINKEDIN_INMAIL,
        "profile_view": ChannelType.LINKEDIN_PROFILE_VIEW,
    }
    for mode, chan in expected.items():
        got = dispatcher._channel_for("channel.linkedin", {"mode": mode})
        assert got == chan, f"channel.linkedin mode={mode!r} routed to {got}, expected {chan}"
    # Absent/unknown mode falls back to the safe default (DM), not None.
    assert dispatcher._channel_for("channel.linkedin", {}) == ChannelType.LINKEDIN_DM
    assert dispatcher._channel_for("channel.linkedin", {"mode": "bogus"}) == ChannelType.LINKEDIN_DM


def test_linkedin_node_config_modes_match_router_map():
    """Every mode the channel.linkedin node config offers must be routable by the
    dispatcher — config and router can't drift apart."""
    src = (REPO / "backend/app/nodes/channels/linkedin.py").read_text(encoding="utf-8")
    m = re.search(r'mode:\s*Literal\[([^\]]+)\]', src)
    assert m, "could not find the LinkedIn mode Literal in the node config"
    config_modes = set(re.findall(r'"(\w+)"', m.group(1)))
    routed = set(dispatcher._LINKEDIN_MODE_CHANNEL)
    assert config_modes == routed, (
        f"LinkedIn node modes {config_modes} != dispatcher-routed modes {routed}"
    )


# ── H2: omni_ai_jobs.kind values must agree across DB CHECK, projector, Pydantic ─
def _migration_kind_values() -> set[str]:
    """The kinds the latest omni_ai_jobs.kind CHECK constraint allows."""
    versions = REPO / "backend/alembic/versions"
    allowed: set[str] = set()
    # The widest CHECK wins (migrations only add). Scan all that mention the check.
    for f in versions.glob("*.py"):
        txt = f.read_text(encoding="utf-8")
        for m in re.finditer(r"kind IN \(([^)]+)\)", txt):
            allowed |= set(re.findall(r"'(\w+)'", m.group(1)))
    return allowed


def test_ai_job_kind_congruent_across_db_projector_pydantic():
    """REGRESSION H2: a kind the projector can WRITE (e.g. 'screen') but the
    AiJobOut Pydantic model can't represent makes GET /ai/jobs 500 on that row.
    The DB CHECK, the projector's accepted set, and the response model must agree."""
    db_kinds = _migration_kind_values()
    assert db_kinds, "no omni_ai_jobs.kind CHECK found in migrations"

    proj = (REPO / "backend/app/projector/main.py").read_text(encoding="utf-8")
    pm = re.search(r'kind not in \(([^)]+)\)', proj)
    assert pm, "could not find the projector's accepted-kind tuple"
    proj_kinds = set(re.findall(r'"(\w+)"', pm.group(1)))

    ai_router = (REPO / "backend/app/routers/ai_studio.py").read_text(encoding="utf-8")
    out = re.search(r'class AiJobOut\(BaseModel\):.*?kind:\s*Literal\[([^\]]+)\]', ai_router, re.S)
    assert out, "could not find AiJobOut.kind Literal"
    pydantic_kinds = set(re.findall(r'"(\w+)"', out.group(1)))

    # Anything the projector writes must be representable by the response model
    # and allowed by the DB.
    assert proj_kinds <= pydantic_kinds, (
        f"projector writes kinds {proj_kinds - pydantic_kinds} that AiJobOut can't "
        f"represent -> GET /ai/jobs 500s on those rows"
    )
    assert proj_kinds <= db_kinds, (
        f"projector writes kinds {proj_kinds - db_kinds} the DB CHECK rejects"
    )


# ── CMP9/CMP10: flow.delay / flow.wait_until must actually delay ───────────────
import asyncio  # noqa: E402

from app.execution import transition_worker  # noqa: E402


def test_flow_delay_computes_nonzero_seconds():
    """REGRESSION CMP9: a flow.delay node must yield a positive delay so the
    orchestrator timer holds the lead — not advance immediately."""
    node = {"node_type": "flow.delay", "config": {"amount": 3, "unit": "days"}, "workflow_id": None}
    secs = asyncio.run(transition_worker._compute_flow_delay_seconds("ws", node))
    assert secs == 3 * 86400, f"flow.delay 3 days computed {secs}, expected 259200"

    node2 = {"node_type": "flow.delay", "config": {"amount": 30, "unit": "minutes"}, "workflow_id": None}
    assert asyncio.run(transition_worker._compute_flow_delay_seconds("ws", node2)) == 1800


def test_flow_nodes_held_by_worker_not_advanced_immediately():
    """REGRESSION CMP9/CMP10: the worker must special-case flow.delay/wait_until
    so they ride the delay path, not the immediate projection_only path."""
    src = (REPO / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
    assert 'node_type in ("flow.delay", "flow.wait_until")' in src, (
        "flow.delay/wait_until are not special-cased in _fire_node — they would "
        "advance immediately via the projection_only path"
    )


# ── DEDUP: clean_company_name must strip taglines without mangling real names ──
from app.services.company_kg import clean_company_name  # noqa: E402


def test_clean_company_name_strips_taglines_only():
    """REGRESSION (dedup hardening): scraped names arrive with taglines glued on
    via | / - / : separators. We must strip the tagline to dedup, but must NOT
    mangle a legitimately hyphenated name (no surrounding spaces on the hyphen)."""
    assert clean_company_name("SourceMash Technologies | Leading Software Co") == "SourceMash Technologies"
    assert clean_company_name("Acme - We Build X") == "Acme"
    assert clean_company_name("Foo : RevOps Platform") == "Foo"
    assert clean_company_name("Globex  Corp   [Remote]") == "Globex Corp"
    assert clean_company_name("Acme (India)") == "Acme"
    # Must NOT be mangled: hyphenated word, dotted name, plain name, empty.
    assert clean_company_name("Co-Working Spaces Ltd") == "Co-Working Spaces Ltd"
    assert clean_company_name("Scooter.ai") == "Scooter.ai"
    assert clean_company_name("Telnyx") == "Telnyx"
    assert clean_company_name("") == ""
    assert clean_company_name(None) == ""


# ── PEOPLE-CHAIN: crm.create_contact must build identity from the discovered person ─
def test_create_contact_reads_discovered_person_not_just_config():
    """REGRESSION (people stage): node config is passed verbatim — it is NOT
    interpolated with the lead's custom_fields. So crm.create_contact MUST read
    the screened person from custom_fields[person_field], or the Naukri/LinkedIn
    company -> Serper people -> screen -> contact chain creates nothing. Config
    fields override the person row; with neither identity it fails closed."""
    import asyncio as _asyncio

    from app.nodes import NodeContext
    from app.nodes.crm.create_contact import execute as _create_contact

    # Discovered person, empty config -> contact built from the person row.
    ctx = NodeContext(
        workspace_id="ws", workflow_id=None, node_id=None, config={},
        lead={"id": "l1", "custom_fields": {"item": {
            "name": "Rahul Menon", "headline": "Head of Growth",
            "linkedin_url": "https://linkedin.com/in/rahul", "company_name": "SourceMash Technologies"}}},
        correlation_id=None,
    )
    r = _asyncio.run(_create_contact(ctx))
    assert r.error is None
    payload = next(e for e in r.events if e["event_type"] == "contact.created")["payload"]
    assert payload["first_name"] == "Rahul" and payload["last_name"] == "Menon"
    assert payload["linkedin_url"] == "https://linkedin.com/in/rahul"
    assert payload["company"] == "SourceMash Technologies"
    # The lead must be bound to the new contact (person-stage lead).
    assert any(e["event_type"] == "lead.contact_attached" for e in r.events)

    # No person AND no config -> fail closed (no ghost contact).
    empty = NodeContext(workspace_id="ws", workflow_id=None, node_id=None, config={},
                        lead={"id": "l2", "custom_fields": {}}, correlation_id=None)
    re = _asyncio.run(_create_contact(empty))
    assert re.error == "CONTACT_REQUIRES_EMAIL_OR_LINKEDIN" and not re.events


# ── INDEED PORT: source.indeed channel must agree across node / map / Rust enum ─
def test_source_indeed_channel_congruent_python_and_rust():
    """REGRESSION (Indeed port): source.indeed must route to ChannelType.INDEED
    in the Python NODE_CHANNEL map, the Python enum value must be 'indeed', and
    the Rust ChannelType must carry a matching #[serde(rename = "indeed")]
    variant + as_str arm + a dispatch arm — or the intent reaches the muscle and
    falls into Unknown."""
    from app.core.events import ChannelType as PyChannel

    assert dispatcher.commands.NODE_CHANNEL.get("source.indeed") == PyChannel.INDEED
    assert PyChannel.INDEED.value == "indeed"

    models_rs = (REPO / "backend-rust/src/models.rs").read_text(encoding="utf-8")
    assert 'rename = "indeed"' in models_rs and "Indeed," in models_rs
    assert 'ChannelType::Indeed => "indeed"' in models_rs
    mod_rs = (REPO / "backend-rust/src/handlers/mod.rs").read_text(encoding="utf-8")
    assert "ChannelType::Indeed => indeed::handle_indeed(command).await" in mod_rs
    assert "pub mod indeed;" in mod_rs


# ── PEOPLE precision: is_company_mismatch must match the fork's latest logic ───
def test_is_company_mismatch_matches_fork_logic():
    """REGRESSION: the pre-Claude misattribution fast-path (verify_person calls
    this) must reject only when the title names a DIFFERENT company via '@'/'at',
    and must NOT fire on '|'/'·' separators (the fork's 2026-06-08 ae023fd8 fix —
    those usually separate roles, not companies). Drift here either re-admits
    misattributed people or wastes Claude calls."""
    from app.services.people_scoring import is_company_mismatch as m

    assert m("CEO @ OtherCorp", "SourceMash") is True
    assert m("Director at Globex", "Acme") is True
    assert m("CEO at SourceMash", "SourceMash") is False
    assert m("Head of Growth at SourceMash Technologies", "SourceMash Technologies") is False
    assert m("VP Sales @ Acme, ex-Google", "Acme") is False
    # The fix: pipe / middot must NOT be treated as company indicators.
    assert m("Founder | 3x startup advisor", "Acme") is False
    assert m("CTO · building things", "Acme") is False
    assert m("CEO at LinkedIn", "Acme") is False  # excluded sentinel
    assert m("Sales Lead", "Acme") is False  # no separator


# ── E2E-001: fan-out dedup + join distinct-child counting + screen verdict writeback ─
def test_fan_out_dedups_identical_items():
    """REGRESSION E2E-001a: a source that returns the same company/person twice
    must not spawn N identical children (wastes paid screens, inflates the join
    barrier). _dedup_items collapses value-identical elements, preserving order."""
    from app.execution.transition_worker import _dedup_items

    c = {"company_name": "Axis Max Life Insurance", "title": "X"}
    assert _dedup_items([c, c, c, c]) == [c]
    a, b = {"company_name": "A"}, {"company_name": "B"}
    assert _dedup_items([a, b, a, b, a]) == [a, b]
    # key order must not defeat dedup
    assert _dedup_items([{"a": 1, "b": 2}, {"b": 2, "a": 1}]) == [{"a": 1, "b": 2}]
    assert _dedup_items([]) == []


def test_join_arrive_counts_distinct_children_idempotently():
    """REGRESSION E2E-001b: _join_arrive must bump the parent's fanout_done at
    most ONCE per child. Kafka redelivery re-runs the arrival; without an atomic
    claim the counter over-counts (observed fanout_done=64 vs total=1) and the
    barrier releases early, tearing the parent down to flow.end before children
    finish. The guard is an atomic UPDATE...WHERE status<>'completed' RETURNING."""
    src = (REPO / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
    assert "status<>'completed' RETURNING id" in src, (
        "join-arrival child completion must be an atomic claim; without the "
        "RETURNING gate, redelivery double-counts fanout_done"
    )
    assert "if not claimed:" in src, "the join must no-op when the child was already counted"


def test_ai_screen_writes_verdict_to_custom_fields():
    """REGRESSION E2E-001c: the ai_screen muscle handler must persist the verdict
    into lead_mutations.custom_fields.screen so the decision survives past routing
    (Leads 'Screen' column, lead scoring). The handle routes; this makes it durable."""
    ai_screen_rs = (REPO / "backend-rust/src/handlers/ai_screen.rs").read_text(encoding="utf-8")
    assert '"screen"' in ai_screen_rs and '"decision"' in ai_screen_rs, (
        "ai_screen must write custom_fields.screen.{decision,verdict,reason}"
    )
