"""SPACE-STALE-001 — an abandoned spacing slot must not wave a send through.

SEND-SPACE-001 reserves a slot on the campaign clock and records it on the lead
as `_spacing_send_at`, so the delayed retry knows when its turn is. The marker
was only ever cleared on release, so it outlived its send whenever the lead left
the node another way: an approval, the reply gate, a graph edit, an operator
recovery. On that lead's NEXT send the stale marker read as "slot reached", the
send released immediately, and no new slot was reserved.

Measured on 2026-08-20. Ten Campaign 2 invites went out two SECONDS apart
against a 600-second setting. Every one carried a marker days old (the oldest
from 4 August), the campaign clock advanced by exactly one gap rather than ten,
and the worker log showed no holds at all. For LinkedIn invites specifically
that is the ban-risk pattern SEND-ONCE-001 was raised about.

A slot is only "reached" near the moment it was reserved for. Older than one
full spacing interval and it is abandoned: clear it and queue again.
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.execution import transition_worker  # noqa: E402

SRC = inspect.getsource(transition_worker._spacing_hold)


def test_a_slot_still_in_the_future_holds():
    """Unchanged behaviour: a retry that fires early keeps waiting."""
    assert "if remaining > 1.0:" in SRC
    assert 'reason="spacing"' in SRC


def test_a_slot_just_reached_releases():
    """The normal path — the delayed retry landed on time, so send."""
    assert "if remaining > -float(spacing):" in SRC
    body = SRC.split("if remaining > -float(spacing):")[1][:200]
    assert "_clear_spacing_slot" in body
    assert "return False" in body


def test_a_slot_older_than_one_interval_is_abandoned_not_honoured():
    """The bug: any past timestamp counted as 'reached'. Now only a recent one
    does, and an abandoned marker falls through to reserve a fresh slot."""
    tail = SRC.split("if remaining > -float(spacing):")[1]
    # after the early return for a genuinely-reached slot, the stale branch must
    # clear the marker and NOT return — it has to reach the reservation below.
    stale = tail.split("return False", 1)[1]
    assert "_clear_spacing_slot" in stale
    assert "return False" not in stale.split("# First pass")[0], \
        "an abandoned slot must fall through to the reservation, not release"
    assert "_reserve_spacing_slot" in SRC


def test_the_window_is_measured_in_spacing_intervals():
    """A fixed number of seconds would be wrong for a campaign spaced hourly and
    wrong again for one spaced by the minute."""
    assert "-float(spacing)" in SRC


def test_the_abandoned_slot_is_logged():
    """Silent re-queuing would hide the same class of bug next time."""
    assert "abandoned spacing slot" in SRC


def test_spacing_off_is_still_a_no_op():
    """A campaign with no spacing configured must be untouched by any of this."""
    assert "if spacing <= 0 or not workflow_id:" in SRC
    head = SRC.split("if spacing <= 0 or not workflow_id:")[1][:80]
    assert "return False" in head


def test_the_reservation_still_lets_the_first_sender_through():
    """With an idle clock the first send goes now; only the queue behind it waits."""
    assert "if hold <= 1.0:" in SRC
    assert "first in the cohort" in SRC
