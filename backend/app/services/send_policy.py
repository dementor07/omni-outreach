"""Pure send-policy core: business-hours windows, rate-limit caps, account
rotation, and sending-account resolution precedence.

This module is intentionally I/O-FREE and fully unit-testable. The async seams
that READ the DB and HOLD/dispatch leads live in the transition worker
(``_gate_send``) and in ``execution.commands`` (account selection) — they call
these pure functions with already-fetched rows.

Why a separate module: the rate-limit + send-window logic is the riskiest part
of the outbound system (a wrong cap bans a real LinkedIn account, a wrong window
sends at 3am). Keeping the decision math pure lets ``audit/tests/test_send_policy.py``
lock every edge case without a DB or a clock.

Conventions (shared with the rest of the codebase):
  - Weekdays: Monday=0 … Sunday=6 (Python ``date.weekday()`` / the
    ``flow.wait_until`` convention in ``_compute_flow_delay_seconds``).
  - A cap of ``0`` means UNLIMITED (an account with no configured ceiling must
    not silently block every send). LinkedIn-safe non-zero defaults are applied
    at account-creation time, not here.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Literal

# ── business-hours send window ───────────────────────────────────────────────
# Faithful port of the flow.wait_until forward-search in
# transition_worker._compute_flow_delay_seconds, but PURE: the caller passes the
# already-localised ``now`` (a tz-aware datetime in the workflow's timezone) so
# the function has no clock and no zoneinfo dependency to mock.

_DEFAULT_DAYS = (0, 1, 2, 3, 4)  # Mon–Fri


def compute_window_hold_seconds(
    now_local: datetime,
    earliest_hour: int = 9,
    latest_hour: int = 17,
    days_of_week: Sequence[int] | None = None,
) -> float:
    """Seconds to hold until the next moment inside the business-hours window.

    ``earliest_hour <= local hour < latest_hour`` on an allowed weekday. Returns
    0.0 when the window is open right now (or when no allowed day is found within
    a week — never hold indefinitely). ``latest_hour`` may be 24 (end of day).
    """
    # Faithful to the worker: missing/empty days_of_week → default Mon–Fri (the
    # worker does ``cfg.get("days_of_week") or [0,1,2,3,4]``). A campaign that
    # wants every day passes [0..6] explicitly.
    days = tuple(days_of_week) if days_of_week else _DEFAULT_DAYS

    for day_offset in range(0, 8):
        d = now_local + timedelta(days=day_offset)
        if d.weekday() not in days:
            continue
        window_open = d.replace(hour=earliest_hour, minute=0, second=0, microsecond=0)
        # window_close anchors at midnight + latest_hour so latest_hour=24 means
        # end-of-day (matches the worker's existing arithmetic exactly).
        window_close = d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=latest_hour)
        if day_offset == 0 and now_local >= window_open and now_local < window_close:
            return 0.0  # already inside the window
        if d >= now_local and window_open >= now_local:
            return max(0.0, (window_open - now_local).total_seconds())
    return 0.0


def window_is_configured(
    earliest_hour: int | None,
    latest_hour: int | None,
    days_of_week: Sequence[int] | None,
) -> bool:
    """True only when the campaign actually declares a send window. An
    unconfigured campaign (all None) is always-on — the gate must not invent a
    9–5 window the operator never asked for."""
    return earliest_hour is not None and latest_hour is not None


# ── rate-limit caps ──────────────────────────────────────────────────────────
# A cap of 0 = unlimited. Counters reset lazily on rollover (the DB UPDATE does
# the same CASE-reset); here we mirror that: a counter whose anchor != the
# current bucket has effectively rolled over to 0.

Granularity = Literal["day", "hour"]


def effective_count(count: int, anchor: Any, current_bucket: Any) -> int:
    """The counter's value AS OF the current bucket: 0 if the stored anchor is a
    different bucket (it rolled over and just hasn't been written yet)."""
    if anchor is None or anchor != current_bucket:
        return 0
    return int(count or 0)


def is_over_cap(count: int, cap: int, anchor: Any = None, current_bucket: Any = None) -> bool:
    """True when a further send would exceed ``cap``. ``cap == 0`` → never over
    (unlimited). When anchor/current_bucket are given, a rolled-over counter
    reads as 0."""
    if not cap or cap <= 0:
        return False
    effective = effective_count(count, anchor, current_bucket) if current_bucket is not None else int(count or 0)
    return effective >= cap


def next_reset_seconds(now: datetime, granularity: Granularity) -> float:
    """Seconds from ``now`` until the start of the next bucket (next local hour
    or next local midnight) — how long to hold a fully-capped account/campaign."""
    if granularity == "hour":
        nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:  # day
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        nxt = midnight + timedelta(days=1)
    return max(0.0, (nxt - now).total_seconds())


# ── account rotation (least-recently-used among eligible) ────────────────────
# The DB query does the real selection (so the row lock is held), but the pure
# pick_lru lets the test assert the ordering/eligibility rules without a DB.


def _account_under_cap(acct: Mapping[str, Any], today: date, hour_bucket: Any) -> bool:
    daily_cap = int(acct.get("warmup_target") or acct.get("daily_cap") or 0)
    if is_over_cap(int(acct.get("sends_today") or 0), daily_cap, acct.get("day_anchor"), today):
        return False
    hourly_cap = int(acct.get("hourly_cap") or 0)
    if is_over_cap(int(acct.get("sends_this_hour") or 0), hourly_cap, acct.get("hour_anchor"), hour_bucket):
        return False
    return True


def eligible_accounts(
    accounts: Sequence[Mapping[str, Any]], today: date, hour_bucket: Any
) -> list[Mapping[str, Any]]:
    """Accounts that may send right now: active/warming AND under both caps."""
    return [
        a
        for a in accounts
        if a.get("status") in ("active", "warming") and _account_under_cap(a, today, hour_bucket)
    ]


def pick_lru(
    accounts: Sequence[Mapping[str, Any]], today: date, hour_bucket: Any
) -> Mapping[str, Any] | None:
    """Pick the least-recently-used eligible account (never-used first). Returns
    None when every account is paused/banned/over-cap — the caller then HOLDS the
    lead until the soonest reset rather than dropping it."""
    pool = eligible_accounts(accounts, today, hour_bucket)
    if not pool:
        return None
    # NULLS FIRST: a never-used account (last_used_at None) ramps in before any
    # used one; otherwise oldest last_used_at wins. datetime.min stand-in keeps
    # None ordering first without comparing None to datetime.
    return min(pool, key=lambda a: (a.get("last_used_at") is not None, a.get("last_used_at") or datetime.min))


# ── sending-account resolution precedence ────────────────────────────────────
# node pin > campaign pool > legacy connection_name > provider default. This is
# the backward-compat lock: a saved graph carrying only connection_name resolves
# to the legacy path with ZERO behaviour change.

ResolutionMode = Literal["account_pin", "campaign_pool", "connection_name", "default"]


def resolve_send_source(
    *,
    node_account_id: str | None,
    has_campaign_pool: bool,
    connection_name: str | None,
) -> ResolutionMode:
    """Which sender-resolution strategy applies, given what the node config and
    campaign declare. Pure — the async caller then executes the chosen strategy
    (load the pinned account / run the LRU pool query / load the named
    connection / fall back to the provider default)."""
    if node_account_id:
        return "account_pin"
    if has_campaign_pool:
        return "campaign_pool"
    if connection_name:
        return "connection_name"
    return "default"


# ── idempotency keys (shape locked so redeliveries collapse correctly) ───────


def cap_hold_marker(node_id: str, reset_ts: float | int) -> dict[str, Any]:
    """The __retry__ dedupe marker for a cap/window hold. Keyed on
    (node, reset bucket) so a redelivered hold collapses but a genuinely later
    retry (next bucket) is unaffected — same contract as the B6 schedule-hold."""
    return {"command_id": f"cap-hold:{node_id}", "retry_attempt": int(reset_ts)}


def increment_claim_id(command_id: str) -> str:
    """The processed_commands claim id for an exactly-once counter increment on a
    confirmed send. One claim per command → at-least-once Kafka redelivery of the
    same 'sent' transition increments the counter exactly once."""
    return f"send-count:{command_id}"


# ── delay jitter (anti-pattern-detection) ────────────────────────────────────


def jittered_seconds(base_seconds: float, jitter_pct: int, seed_key: str) -> float:
    """A flow.delay held for a DETERMINISTICALLY-jittered duration.

    Fixed inter-message intervals (exactly 3.00 days every time) are a robotic
    signature LinkedIn's automation detection flags. Spreading each lead's wait
    by ±``jitter_pct`` percent breaks that regularity while keeping the average
    cadence the operator configured.

    Deterministic on ``seed_key`` (``"<lead_id>:<node_id>"``): the SAME lead at
    the SAME delay node always computes the SAME jitter, so a Kafka/Flink
    at-least-once redelivery re-holds for the identical duration instead of
    drifting the timer. Different leads get independent offsets, so a cohort
    seeded together does not release in lockstep.

    jitter_pct<=0 or a zero base returns the base unchanged (backward-compatible).
    """
    if jitter_pct <= 0 or base_seconds <= 0:
        return float(base_seconds)
    pct = min(100, int(jitter_pct))
    digest = hashlib.sha256(seed_key.encode("utf-8")).hexdigest()
    rng = random.Random(int(digest, 16))
    factor = 1.0 + rng.uniform(-pct / 100.0, pct / 100.0)
    return float(base_seconds) * factor


# ── inter-send spacing (SEND-SPACE-001) ──────────────────────────────────────
# Distinct from jittered_seconds above: that spaces one lead's OWN sequence
# steps (flow.delay). This spaces DIFFERENT leads' sends from the same campaign
# so a cohort approved together does not fire in one burst (a LinkedIn ban
# signature). The gate reserves a slot per send by advancing the campaign's
# next_send_at by one jittered gap; a lead landing inside the gap is held.


def jittered_gap_seconds(base_seconds: float, jitter_pct: int, rand_uniform: float) -> float:
    """One inter-send spacing gap, ``base_seconds`` ± ``jitter_pct``%.

    Each send RESERVATION wants an INDEPENDENT random gap (so the trickle is
    uneven and human, not a metronome). Randomness is injected as ``rand_uniform``
    in [-1.0, 1.0] — the caller passes ``random.uniform(-1, 1)`` — keeping this
    pure and unit-testable. rand_uniform is clamped to [-1, 1] defensively.

    Returns at least 1.0s for any positive base so a reservation always advances
    the clock; ``base_seconds <= 0`` → 0.0 (spacing disabled)."""
    if base_seconds <= 0:
        return 0.0
    pct = max(0, min(100, int(jitter_pct)))
    r = max(-1.0, min(1.0, float(rand_uniform)))
    factor = 1.0 + (pct / 100.0) * r
    return max(1.0, float(base_seconds) * factor)


# ── SEND-LANE-001: which queue a send waits in, and how wide its gap is ──────
# SEND-SPACE-001 put every send a campaign makes behind ONE pointer. Two things
# that share a queue but shouldn't: a warm DM to somebody who just accepted, and
# a cold invite; and two different seats, which LinkedIn rate-limits separately.

INVITE_NODE_TYPE = "channel.linkedin_invite"
INVITE_LANE = "invite"       # rotates across the pool -> gap divides
MESSAGE_LANE = "message"     # unpinned fallback -> full gap, shared


def spacing_lane(node_type: str, seat_external_id: str | None) -> str:
    """The spacing queue this send belongs in.

    Invites share ONE campaign lane because the pool rotates through them by
    LRU — no invite is tied to a particular seat, so the campaign is the right
    unit and the gap gets divided across the seats (see effective_gap_seconds).

    A DM is different: SEAT-PIN-001 pins a follow-up to the seat that sent the
    accepted invite, because only that seat is a 1st-degree connection. Two
    consecutive DMs can therefore land on the SAME account, so they get a lane
    per seat at the full gap. Different seats then drip independently, which is
    the parallelism, and no single account ever sends faster than the gap.

    A DM with no pin falls back to one shared message lane at the full gap —
    conservative, because without the pin there is nothing proving which account
    will carry it.
    """
    if node_type == INVITE_NODE_TYPE:
        return INVITE_LANE
    seat = (seat_external_id or "").strip()
    return f"msg:{seat}" if seat else MESSAGE_LANE


def effective_gap_seconds(gap_seconds: float, seat_count: int) -> float:
    """Divide a campaign-wide gap across the seats that will rotate through it.

    The seat is not known when the gate runs — pick_lru chooses later, in the
    dispatcher — so an invite lane cannot key on it. Dividing gets the same
    outcome: with N healthy seats the CAMPAIGN emits every gap/N, while LRU
    rotation means each individual SEAT still averages a full gap between its
    own sends. That is the safety property that matters, since the provider
    rate-limits per account.

    Only ever used for lanes that rotate. A per-seat lane passes seat_count=1.
    """
    if gap_seconds <= 0:
        return 0.0
    return max(1.0, float(gap_seconds) / max(1, int(seat_count)))
