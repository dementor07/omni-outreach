"""Parked-node race guard (RACE-PARK-001) — exactly-one advance.

A lead parked ('waiting') at an event.* / flow.race node is the target of two
concurrent transitions that share the same source node but route differently:
  - the awaited signal's resume (invite-accepted webhook / reply / open / click),
  - the EVENT-PARK-001 / race timeout escape.
Both must NOT advance the lead — that double-sends down two branches (the user's
#1 named edge case: "the client responds faster than we have scheduled the
first message"). A single atomic waiting→active claim must decide the one
winner; the loser no-ops.

This pins the claim into the seam so a refactor can't reopen the window.
Static/source-faithful checks (house style). No DB, no Kafka.
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


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"^async def {name}\(.*?(?=^(?:async )?def |\Z)", src, re.M | re.S)
    assert m, f"function {name} not found"
    return m.group(0)


def test_claim_is_a_single_atomic_waiting_to_active_update():
    body = _func_body(TW_SRC, "_claim_parked_node")
    # ONE atomic UPDATE: flips waiting→active only if the lead is still parked
    # at this exact node, RETURNING so only the winner gets a row.
    assert "status='active'" in body
    assert "status='waiting'" in body, "the claim must gate on the parked status"
    assert "current_node_id IS NOT DISTINCT FROM" in body, "and on the exact node"
    assert "RETURNING id" in body
    # the winner is the one (and only) caller that gets a row back.
    assert "return won is not None" in body


def test_timeout_path_claims_before_side_effects():
    body = _func_body(TW_SRC, "handle_transition")
    timeout_idx = body.find('if handle == "timeout":')
    claim_idx = body.find("_claim_parked_node(", timeout_idx)
    cancel_idx = body.find("status='cancelled'", timeout_idx)
    assert timeout_idx != -1 and claim_idx != -1 and cancel_idx != -1
    # the claim must precede the sibling-cancel / barrier-reset side effects —
    # only the winner may run them (the old check-then-act ran them in a window
    # where a concurrent resume had already advanced the lead).
    assert timeout_idx < claim_idx < cancel_idx
    # and a lost claim is a no-op return, not a fall-through.
    assert "already resolved/resumed" in body


def test_resume_of_a_parked_lead_also_wins_the_same_claim():
    body = _func_body(TW_SRC, "handle_transition")
    # a success-signal resume arriving at a STILL-parked lead must win the SAME
    # claim before advancing — so resume vs timeout resolves to one advance.
    assert 'elif (row.get("status") or "") == "waiting":' in body
    # the resume branch calls the same claim helper and drops on a loss.
    resume_idx = body.find('elif (row.get("status") or "") == "waiting":')
    assert resume_idx != -1
    assert "_claim_parked_node(" in body[resume_idx:resume_idx + 400]
    assert "lost the parked-node claim" in body


def test_normal_active_advance_is_unaffected_by_the_park_claim():
    body = _func_body(TW_SRC, "handle_transition")
    # a normal (non-parked) active lead must NOT hit the park claim — its
    # positional advance claim (current_node_id match) remains the guard. The
    # park claim is gated on status=='waiting', so active leads skip it.
    assert "current_node_id IS NOT DISTINCT FROM $4" in body, (
        "the normal positional advance claim must remain intact"
    )
    # the park claim is an elif on the waiting status — mutually exclusive with
    # the timeout branch and skipped entirely for active leads.
    assert body.find('if handle == "timeout":') < body.find('elif (row.get("status") or "") == "waiting":')
