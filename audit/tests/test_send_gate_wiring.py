"""Send-gate spine wiring invariants — the rate-limit + window enforcement must
stay wired into the exact seams it depends on, the way it depends on them.

The pure decision math is locked in test_send_policy.py. THIS file pins the
RUNTIME WIRING that math plugs into — the parts a refactor could silently
unhook, turning "rate limited" back into dead vocabulary:

  - the campaign cap/window gate sits AFTER the B6 absolute schedule and BEFORE
    the DNC check (a held send must not reach suppression / dispatch);
  - a tripped gate HOLDS the lead (waiting + delayed __retry__), never drops it;
  - the rate counter increments on a CONFIRMED send (status='sent'), NOT at
    dispatch — so a failed/held send never consumes capacity;
  - the increment is exactly-once (omni_send_count_claims, command-keyed) so
    Kafka/Flink at-least-once redelivery bumps the counter once;
  - build_command stamps metadata.sending_account_id and the Flink orchestrator
    FORWARDS it into the transition — without that forward the worker never sees
    which account to increment.

Static/functional checks only (house style: runtime-faithful proxies over the
source + importable pure functions). No DB, no Kafka.
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
CMD_SRC = (REPO / "backend/app/execution/commands.py").read_text(encoding="utf-8")
DISPATCH_SRC = (REPO / "backend/app/execution/dispatcher.py").read_text(encoding="utf-8")
FLINK_SRC = (REPO / "backend-flink/orchestrator.py").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^async def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


# ── gate placement: after B6 schedule, before DNC ─────────────────────────────


def test_gate_send_sits_between_schedule_and_dnc():
    body = _func_body(TW_SRC, "_fire_node")
    b6 = body.find("campaign schedule window")          # B6 absolute schedule
    gate = body.find("_gate_send(")                      # our cap/window gate
    dnc = body.find("DNC enforcement")                   # T1 suppression
    assert b6 != -1 and gate != -1 and dnc != -1, "a required seam marker is missing"
    assert b6 < gate < dnc, (
        "the rate/window gate must run after the B6 schedule and before DNC — "
        "a send held for cap/window must not reach suppression or dispatch"
    )


def test_gate_only_for_outbound_send_channels():
    body = _func_body(TW_SRC, "_fire_node")
    # the gate is inside the `node_type in _OUTBOUND_SEND_CHANNELS` block (the
    # same guard B6 uses) — non-send nodes (conditions/flow/sources) never gate.
    guard = body.find("_OUTBOUND_SEND_CHANNELS")
    gate = body.find("_gate_send(")
    assert guard != -1 and guard < gate


# ── hold, never drop ──────────────────────────────────────────────────────────


def test_held_send_parks_waiting_and_schedules_retry():
    body = _func_body(TW_SRC, "_hold_send")
    assert 'status="waiting"' in body, "a held send must park the lead 'waiting'"
    assert '"__retry__"' in body, "a held send must schedule a __retry__ re-fire"
    assert "cap_hold_marker" in body, "the hold must use the (node, reset) dedupe marker"
    # never terminal — a hold is not an end-state.
    assert "_terminalize_lead" not in body


# ── increment on confirmed send, exactly-once ─────────────────────────────────


def test_increment_only_on_confirmed_sent_status():
    body = _func_body(TW_SRC, "handle_transition")
    # the increment is gated on status == 'sent' AND a stamped account id.
    assert re.search(r'meta\.get\("status"\).*?==\s*"sent"', body), (
        "rate counter must increment only on a CONFIRMED send (status='sent'), "
        "not at dispatch and not on 'simulated'/'skipped'"
    )
    assert 'meta.get("sending_account_id")' in body
    assert "_increment_send_counters(" in body


def test_increment_is_exactly_once_claim_gated():
    body = _func_body(TW_SRC, "_increment_send_counters")
    assert "omni_send_count_claims" in body, "increment must claim via the dedupe ledger"
    assert "ON CONFLICT" in body and "DO NOTHING" in body and "RETURNING" in body, (
        "the claim must be an INSERT … ON CONFLICT DO NOTHING RETURNING so only "
        "the first delivery wins (exactly-once under at-least-once redelivery)"
    )
    # the counter UPDATE must be reset-on-rollover (CASE on the anchor), not a
    # blind +1 that never resets at day/hour boundaries.
    assert "CASE WHEN day_anchor" in body and "CASE WHEN hour_anchor" in body
    # and it must only bump AFTER the claim is won (claim check precedes UPDATE).
    claim_at = body.find("omni_send_count_claims")
    update_at = body.find("UPDATE omni_sending_accounts")
    assert claim_at != -1 and update_at != -1 and claim_at < update_at


# ── the metadata wire: stamp (commands) → forward (flink) → read (worker) ─────


def test_build_command_stamps_sending_account_id():
    body = _func_body(CMD_SRC, "build_command")
    assert '"sending_account_id": sending_account_id_used' in body, (
        "build_command must stamp metadata.sending_account_id so the worker knows "
        "which account to increment"
    )


def test_flink_forwards_sending_account_id():
    # the orchestrator only forwards an allowlist of metadata keys into the
    # transition; sending_account_id MUST be on it or the stamp is lost in transit.
    assert '"sending_account_id": _safe_get(data, "metadata", "sending_account_id")' in FLINK_SRC, (
        "Flink _build_transition must forward sending_account_id; without it the "
        "worker never sees the account and the counter never increments"
    )


def test_dispatcher_passes_account_selection_to_build_command():
    body = _func_body(DISPATCH_SRC, "handle_event")
    assert "sending_account_id=sending_account_id" in body
    assert "account_pool=account_pool" in body


# ── backward-compat: the selection path is strictly additive ─────────────────


def test_account_selection_falls_back_to_connection_name():
    body = _func_body(CMD_SRC, "build_command")
    # when no account resolves, the legacy _load_connection_bundle(connection_name)
    # path must still run — saved graphs with only connection_name are unchanged.
    assert "_load_connection_bundle(workspace_id, connection_name)" in body
