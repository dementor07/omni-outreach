"""SEND-LANE-001 — send spacing moves off one campaign-wide pointer.

SEND-SPACE-001's own docstring says the goal is that a cohort "doesn't burst
FROM ONE SEAT". It was implemented as a single ``omni_workflows.next_send_at``
per CAMPAIGN, which is a different thing, and it cost real money twice:

  * A DM to somebody who had just accepted queued behind every cold invite
    already holding a slot. Measured 2026-08-21: composed 10:23, scheduled
    13:29 — three hours, on the warmest lead in the campaign.
  * Two pooled seats took TURNS through the one pointer, so two healthy
    accounts produced one send per gap between them rather than one each.

These lock the two rules that fix it, and the safety property that must survive:
no single ACCOUNT may ever send faster than the configured gap.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import send_policy as sp


# ── which queue a send waits in ─────────────────────────────────────────────


def test_invites_share_one_rotating_lane():
    assert sp.spacing_lane("channel.linkedin_invite", "seat-a") == sp.INVITE_LANE
    # the pin is irrelevant for invites — the pool rotates by LRU
    assert sp.spacing_lane("channel.linkedin_invite", "seat-b") == sp.INVITE_LANE


def test_a_dm_gets_a_lane_per_seat():
    """SEAT-PIN-001 pins a follow-up to the seat that sent the accepted invite,
    so two DMs can land on the same account. Per-seat lanes let different seats
    run in parallel without ever speeding up an individual one."""
    assert sp.spacing_lane("channel.linkedin_dm", "seat-a") == "msg:seat-a"
    assert sp.spacing_lane("channel.linkedin_dm", "seat-b") == "msg:seat-b"
    assert sp.spacing_lane("channel.linkedin_dm", "seat-a") != sp.spacing_lane(
        "channel.linkedin_dm", "seat-b"
    )


def test_a_dm_never_shares_the_invite_lane():
    """The whole point: a warm reply must not queue behind cold outreach."""
    for seat in ("seat-a", "", None):
        assert sp.spacing_lane("channel.linkedin_dm", seat) != sp.INVITE_LANE


def test_an_unpinned_dm_falls_back_to_one_shared_lane():
    """Without the pin there is nothing proving which account carries it, so it
    takes the conservative shared lane at the full gap rather than a per-seat
    lane that might not match reality."""
    assert sp.spacing_lane("channel.linkedin_dm", None) == sp.MESSAGE_LANE
    assert sp.spacing_lane("channel.linkedin_dm", "   ") == sp.MESSAGE_LANE


# ── how wide the gap is ─────────────────────────────────────────────────────


def test_the_rotating_gap_divides_across_seats():
    """Two seats, and the CAMPAIGN emits twice as often — while each seat still
    averages a full gap, because LRU alternates between them."""
    assert sp.effective_gap_seconds(600, 2) == 300.0
    assert sp.effective_gap_seconds(600, 4) == 150.0


def test_one_seat_is_unchanged_from_today():
    """The backward-compat lock: a single-seat campaign must drip exactly as it
    does now, so this change is invisible to it."""
    assert sp.effective_gap_seconds(600, 1) == 600.0


@pytest.mark.parametrize("bad", [0, -3])
def test_a_nonsense_seat_count_never_speeds_sending_up(bad):
    """Over-spacing is the safe direction. A zero or negative count must clamp
    to one full gap, never to an unbounded burst."""
    assert sp.effective_gap_seconds(600, bad) == 600.0


def test_disabled_spacing_stays_disabled():
    assert sp.effective_gap_seconds(0, 4) == 0.0


def test_a_gap_always_advances_the_clock():
    """A reservation that returns 0 would hand every lead the same slot."""
    assert sp.effective_gap_seconds(1, 100) >= 1.0


# ── the safety property, stated directly ────────────────────────────────────


def test_no_single_account_sends_faster_than_the_gap():
    """The invariant the provider actually cares about. With N seats the campaign
    fires every gap/N, but consecutive sends alternate seats by LRU, so any ONE
    account's successive sends are still a full gap apart."""
    gap, seats = 600.0, 3
    campaign_gap = sp.effective_gap_seconds(gap, seats)
    start = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    # campaign emits at 0, 200, 400, 600, 800, 1000s; LRU cycles a,b,c,a,b,c
    fires = [(start + timedelta(seconds=campaign_gap * i), i % seats) for i in range(6)]
    for seat in range(seats):
        times = [t for t, s in fires if s == seat]
        for earlier, later in zip(times, times[1:]):
            assert (later - earlier).total_seconds() >= gap
