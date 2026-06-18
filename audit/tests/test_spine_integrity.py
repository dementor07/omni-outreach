"""Spine logic-integrity invariants — the A–D contract from the 2026-06-11
trace audit (see omni-vault/wiki/decisions/logic-integrity-ledger.md).

Each test pins one fix from that pass so the bug class can't silently return:
  Decision A — idempotency + terminal-guard at the transition entry
  Decision B — every failure path reaches a terminal state + barrier accounting
  Decision C — run/lead identity minted once at the spine entry
  Decision D — contract honesty across the Python↔Rust wire

Static/functional checks only — no DB, no Kafka (house style: runtime-faithful
proxies over the source and importable pure functions).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
TW_SRC = (REPO / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
CANVAS_SRC = (REPO / "backend/app/routers/canvas.py").read_text(encoding="utf-8")
DISPATCH_SRC = (REPO / "backend/app/execution/dispatcher.py").read_text(encoding="utf-8")
# Seed-and-fire was extracted from run_workflow into the shared run module; the
# SM-3 invariant (error-before-publish) now lives in seed_and_run.
RUN_SRC = (REPO / "backend/app/execution/run.py").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    """Source of one top-level async def, up to the next top-level def."""
    m = re.search(rf"^async def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


# ── Decision A: terminal guard + atomic claims ─────────────────────────────────

def test_terminal_statuses_contract_declared():
    """The terminal-state set is a single named contract, not scattered strings."""
    assert re.search(
        r'TERMINAL_STATUSES\s*=\s*\(\s*"completed",\s*"errored",\s*"cancelled",\s*"converted",\s*"ended"', TW_SRC
    ), "TERMINAL_STATUSES contract constant missing or reordered"


def test_handle_transition_guards_terminal_leads():
    """REGRESSION SM-1/SM-6: a terminal lead must never be advanced/re-fired.
    The entry fetch must read status (and lineage for the barrier carve-out)
    and branch on TERMINAL_STATUSES before any routing."""
    body = _func_body(TW_SRC, "handle_transition")
    assert "SELECT workspace_id, status, parent_lead_id, origin_node_id FROM omni_leads" in body
    guard_at = body.find("in TERMINAL_STATUSES")
    assert guard_at != -1, "terminal-state guard missing from handle_transition"
    retry_at = body.find('handle == "__retry__"')
    assert retry_at != -1 and guard_at < retry_at, (
        "terminal guard must run BEFORE the __retry__ branch (SM-1: retry resurrected errored leads)"
    )


def test_race_fan_out_uses_atomic_claim_not_memory_guard():
    """REGRESSION RACE-1: _race_fan_out idempotency must be the fanout_total
    0→-1 atomic claim (RETURNING-gated), not a read-back in-memory guard a
    redelivery trample can bypass."""
    body = _func_body(TW_SRC, "_race_fan_out")
    assert re.search(r"fanout_total=-1.*?fanout_total=0\s+RETURNING", body, re.S), (
        "_race_fan_out atomic claim (fanout_total 0→-1 … RETURNING) missing"
    )
    assert 'parent.get("status")' not in body, (
        "old in-memory status guard still present in _race_fan_out (TOCTOU)"
    )


def test_no_pre_advance_before_fanout_targets():
    """REGRESSION RACE-1 (the trample): handle_transition must not _advance_lead
    before dispatching to for_each/race — the unconditional pre-advance flipped
    parked parents back to 'active' on redelivery, breaking the race win claim
    (which requires status='waiting') and bypassing idempotency."""
    body = _func_body(TW_SRC, "handle_transition")
    fanout_at = body.find('"flow.for_each"')
    race_at = body.find('"flow.race"')
    assert fanout_at != -1 and race_at != -1
    pre = body[:fanout_at]
    assert "_advance_lead(" not in pre.split('handle == "timeout"')[-1], (
        "an _advance_lead call re-appeared between the timeout branch and the fan-out dispatch"
    )
    # The normal advance must be a positional claim, after both fan-out branches.
    claim_at = body.find("IS NOT DISTINCT FROM")
    assert claim_at > race_at, "positional advance claim must come after the for_each/race branches"


def test_normal_advance_is_positional_claim():
    """REGRESSION RACE-7 (consumer-side defusal): the normal advance must be
    claim-gated on the lead still sitting at the transition's source node, so
    redelivered / Flink-re-emitted transitions can't double-advance or
    double-fire (duplicate muscle send)."""
    body = _func_body(TW_SRC, "handle_transition")
    assert re.search(
        r"UPDATE omni_leads SET current_node_id=\$1, status='active'.*?"
        r"current_node_id IS NOT DISTINCT FROM \$4.*?RETURNING",
        body,
        re.S,
    ), "positional advance claim missing"


def test_retry_redrive_is_deduplicated():
    """REGRESSION RETRY-DUP: the __retry__ transition is at-least-once; the
    (command_id, attempt) marker claim must gate the re-fire so one retry can't
    dispatch the same muscle command twice."""
    body = _func_body(TW_SRC, "handle_transition")
    assert "_retry_marker" in body and "IS DISTINCT FROM" in body.split('handle == "__retry__"')[1].split("handle == ")[0]


# ── Decision B: failure paths reach a terminal state + barrier accounting ──────

def test_terminalize_lead_claims_and_notifies_barrier():
    """SM-5 core: _terminalize_lead must be an atomic claim (status NOT IN
    terminal set) that notifies the parent barrier on the claiming call and
    re-attempts ONLY the release (count=False) on redelivery."""
    body = _func_body(TW_SRC, "_terminalize_lead")
    assert "status NOT IN" in body and "RETURNING parent_lead_id, origin_node_id" in body
    assert "count=True" in body and "count=False" in body


def test_all_terminal_paths_route_through_terminalize():
    """REGRESSION SM-5 + siblings: every place a lead ends — leaf, goal/end,
    unknown node type, dead-on-arrival, node error — must terminalize (which
    accounts fan-out children at the parent barrier) rather than writing a bare
    terminal status that strands the parent in 'waiting' forever."""
    fire = _func_body(TW_SRC, "_fire_node")
    handle = _func_body(TW_SRC, "handle_transition")
    assert fire.count("_terminalize_lead(") >= 4, (
        "_fire_node must terminalize on: unknown type, result.error, goal/end, dead_on_arrival"
    )
    leaf = handle.split("reached leaf")[0]
    assert "_terminalize_lead(" in leaf.rsplit("if not target:", 1)[-1] if "if not target:" in leaf else True
    assert '_advance_lead(workspace_id, lead_id, None, status="completed")' not in handle, (
        "leaf path still writes a bare completed status (bypasses barrier accounting)"
    )
    assert 'status="errored")' not in fire, (
        "_fire_node still writes a bare errored status (bypasses barrier accounting)"
    )


def test_fire_node_inspects_result_error():
    """REGRESSION SM-2: a node's result.error must be inspected — route the
    on_error edge or terminalize; never advance a lead past its own failure."""
    body = _func_body(TW_SRC, "_fire_node")
    err_at = body.find("if result.error:")
    assert err_at != -1, "_fire_node never inspects result.error"
    publish_at = body.find("if result.events:")
    assert err_at < publish_at, "error must be checked BEFORE publishing the node's events"
    err_block = body[err_at:publish_at]
    assert '"on_error"' in err_block and "_terminalize_lead(" in err_block


def test_barrier_release_resets_fanout_counters():
    """REGRESSION SEQ-FANOUT: every barrier release/win claim must reset
    fanout_total/fanout_done to 0 (the claim sentinel), or a lead that finished
    one fan-out can never claim a later one — sequential for_each nodes
    silently never fanned out."""
    barrier = _func_body(TW_SRC, "_barrier_arrive")
    resets = re.findall(r"fanout_total=0,\s*fanout_done=0", barrier)
    assert len(resets) >= 3, (
        f"expected ≥3 counter resets in _barrier_arrive (race win, race all-dead, for_each release); found {len(resets)}"
    )
    fan_out = _func_body(TW_SRC, "_fan_out")
    assert re.search(r"fanout_total=0,\s*fanout_done=0", fan_out), (
        "_fan_out empty/done path must release the -1 claim sentinel"
    )


def test_barrier_updates_are_pinned_to_origin_node():
    """A ghost redelivery from an earlier fan-out must not mutate a barrier the
    same lead opened at a LATER node — every parent counter/release statement in
    _barrier_arrive must be pinned to current_node_id = the origin (parking)
    node. Counters reset on release now (SEQ-FANOUT), so unpinned barrier ops
    could hit a later fan-out's barrier on the same lead."""
    barrier = _func_body(TW_SRC, "_barrier_arrive")
    pins = barrier.count("AND current_node_id=$3")
    assert pins >= 6, (
        f"expected ≥6 origin-node pins across the race win/increment/select/release "
        f"and for_each increment/select/release statements; found {pins}"
    )


def test_run_workflow_errors_before_publishing():
    """REGRESSION SM-3: the seed-and-fire path must check the entry node's error
    BEFORE publishing its events, and must terminalize the seed lead (not leave
    it stranded 'active' at the entry node forever). This logic lives in the
    shared seed_and_run (reused by /run and the objective re-seed)."""
    body = _func_body(RUN_SRC, "seed_and_run")
    err_at = body.find("if result.error:")
    pub_at = body.find("for ev in result.events:")
    assert err_at != -1 and pub_at != -1 and err_at < pub_at, (
        "seed_and_run must check result.error before publishing events"
    )
    assert "SET status='errored'" in body[err_at:pub_at], (
        "seed_and_run error path must terminalize the seed lead"
    )


# ── Decision C: identity minted once ───────────────────────────────────────────

def test_correlation_minted_once_at_spine_entry():
    """REGRESSION SPINE-1: handle_transition and _fire_node must each backstop-
    mint the correlation_id ONCE, so fan-out children share one run identity
    instead of fragmenting the trace."""
    handle = _func_body(TW_SRC, "handle_transition")
    assert re.search(r'correlation_id"\)\s+or\s+str\(uuid\.uuid4\(\)\)', handle), (
        "handle_transition must mint correlation_id when upstream lost it"
    )
    fire = _func_body(TW_SRC, "_fire_node")
    assert "correlation_id = correlation_id or str(uuid.uuid4())" in fire


def test_dispatcher_warns_on_synthetic_lead():
    """REGRESSION SPINE-2: dispatching with a synthetic (node-id) lead is a
    silent black hole — results can't advance any lead. It must be LOUD."""
    assert "SYNTHETIC lead" in DISPATCH_SRC and "log.warning" in DISPATCH_SRC.split("SYNTHETIC lead")[0][-400:] + DISPATCH_SRC.split("SYNTHETIC lead")[0][-1:], (
        "dispatcher must warn loudly when building a synthetic lead"
    )


# ── Decision D: wire-contract honesty ─────────────────────────────────────────

def test_lead_context_carries_social_routing_fields():
    """REGRESSION CONTRACT-1: every Option field Rust's LeadContext declares
    must be populated when the data exists. Functional check against the real
    builder."""
    from app.execution.commands import _lead_context

    lead = {
        "id": "11111111-1111-1111-1111-111111111111",
        "workflow_id": "22222222-2222-2222-2222-222222222222",
        "custom_fields": {"chat_id": "wa-123", "ig_chat_id": "ig-456", "tg_chat_id": "tg-789"},
    }
    contact = {
        "email": "a@b.co",
        "headline": "VP Eng",
        "source": "naukri",
        "custom_fields": {"location": "Pune", "instagram_username": "vp.eng", "telegram_username": "vpeng"},
    }
    ctx = _lead_context(lead, contact)
    assert ctx["headline"] == "VP Eng"
    assert ctx["source"] == "naukri"
    assert ctx["location"] == "Pune"
    assert ctx["chat_id"] == "wa-123"
    assert ctx["ig_chat_id"] == "ig-456"
    assert ctx["tg_chat_id"] == "tg-789"
    assert ctx["instagram_username"] == "vp.eng"
    assert ctx["telegram_username"] == "vpeng"
    # And the no-contact path stays None-safe.
    bare = _lead_context({"id": lead["id"], "custom_fields": {}}, None)
    assert bare["chat_id"] is None and bare["headline"] is None


def test_lead_mutations_persist_chat_session_markers():
    """REGRESSION CONTRACT-3: the muscle's chat-session mutations (chat_id /
    ig_chat_id / tg_chat_id / provider_id / invited_at / inmail_sent_at) must be
    persisted into custom_fields — dropping them meant every DM opened a brand
    new chat instead of continuing the thread."""
    body = _func_body(TW_SRC, "_apply_lead_mutations")
    for key in ("chat_id", "ig_chat_id", "tg_chat_id", "provider_id", "invited_at", "inmail_sent_at"):
        assert f'"{key}"' in body, f"_apply_lead_mutations no longer persists {key}"
