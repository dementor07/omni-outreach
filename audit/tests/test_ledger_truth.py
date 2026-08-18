"""LEDGER-TRUTH-001 — only a real provider attempt belongs in the send ledger.

_emit_synthetic_result must claim status='sent' for a DELAYED synthetic, because
the Flink orchestrator only applies its timer to 'sent' results. Nothing is
actually sent. _emit_send_outcome did not distinguish, so every hold wrote a
phantom 'sent' row into omni_send_outcomes.

Measured on 2026-08-18 across C1+C2: 121 duplicate clusters, and in EVERY one
only a single command_id appeared in processed_commands (the muscle's
exactly-once ledger). The extra rows carried no provider and no
sending_account_id — the signature of a result the muscle never produced.

Two consequences, one cosmetic and one dangerous:
  * every "messages sent" number was inflated;
  * SEND-ONCE-001's guard is `status='sent' AND node_id=...`, so a phantom row
    for a node makes the guard believe that node already sent. That is the
    mechanism behind SEND-ONCE-002's 13 stranded leads.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    return SRC.split(f"async def {name}")[1].split("\nasync def ")[0]


def test_synthetic_results_are_marked_as_synthetic():
    body = _fn("_emit_synthetic_result")
    assert '"synthetic": True' in body
    # The delayed variant still has to say 'sent' for the orchestrator's timer.
    assert '"status": "sent" if delay_seconds > 0 else "skipped"' in body


def test_the_send_ledger_refuses_synthetic_results():
    body = _fn("_emit_send_outcome")
    assert 'if meta.get("synthetic"):' in body
    # and it bails BEFORE the status check that would let 'sent' through
    idx_guard = body.index('if meta.get("synthetic"):')
    idx_status = body.index('status = str(meta.get("status") or "").lower()')
    assert idx_guard < idx_status


def test_the_send_once_guard_still_keys_on_the_sent_ledger():
    """The guard is unchanged on purpose. It is only trustworthy once the ledger
    stops carrying rows for sends that never happened."""
    body = _fn("_already_sent_this_node")
    assert "status='sent'" in body
    assert "node_id=$3" in body


def test_a_real_muscle_result_is_still_recorded():
    """The fix must not suppress genuine outcomes: only the synthetic marker
    short-circuits, not a missing provider or seat."""
    body = _fn("_emit_send_outcome")
    assert 'if meta.get("provider")' not in body
    assert 'status not in {"sent", "failed", "skipped"}' in body
