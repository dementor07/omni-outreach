"""Send-policy regression — rate-limit caps, business-hours windows, account
rotation, and sender-resolution precedence must hold their contract.

THE RISK: a wrong cap bans a real sending account; a wrong window sends at 3am;
a wrong precedence silently breaks every saved graph that picks a sender by
connection_name. These lock the pure decision math so none of that can regress.
Pure (no DB/network/clock — ``now`` is always passed in).

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.services.send_policy import (  # noqa: E402
    cap_hold_marker,
    compute_window_hold_seconds,
    effective_count,
    eligible_accounts,
    increment_claim_id,
    is_over_cap,
    next_reset_seconds,
    pick_lru,
    resolve_send_source,
    window_is_configured,
)


def _dt(y, m, d, h, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


# ── business-hours window ────────────────────────────────────────────────────


def test_window_open_now_returns_zero():
    # 2026-06-22 is a Monday, 11:00 is inside 9–17.
    assert compute_window_hold_seconds(_dt(2026, 6, 22, 11), 9, 17, [0, 1, 2, 3, 4]) == 0.0


def test_window_before_open_holds_until_open():
    # Monday 07:00, window opens 09:00 → hold 2h.
    held = compute_window_hold_seconds(_dt(2026, 6, 22, 7), 9, 17, [0, 1, 2, 3, 4])
    assert held == 2 * 3600


def test_window_after_close_holds_to_next_allowed_day():
    # Monday 18:00 (after 17:00 close) → next open is Tuesday 09:00 = 15h.
    held = compute_window_hold_seconds(_dt(2026, 6, 22, 18), 9, 17, [0, 1, 2, 3, 4])
    assert held == 15 * 3600


def test_window_skips_weekend():
    # 2026-06-26 is a Friday. Window Mon–Fri, 18:00 is after the 17:00 close, so
    # the next open skips Sat+Sun → Monday 09:00 = 63h (Fri 18:00 + 2d15h).
    held = compute_window_hold_seconds(_dt(2026, 6, 26, 18), 9, 17, [0, 1, 2, 3, 4])
    assert held == 63 * 3600


def test_window_latest_hour_24_is_end_of_day():
    # 23:30 with window 9..24 → still inside (close is midnight).
    assert compute_window_hold_seconds(_dt(2026, 6, 22, 23, 30), 9, 24, [0, 1, 2, 3, 4]) == 0.0


def test_window_empty_days_defaults_to_weekdays():
    # Faithful to the worker: empty days_of_week → Mon–Fri default. 2026-06-22 is
    # a Monday; 03:00 is before the 09:00 open → hold 6h.
    assert compute_window_hold_seconds(_dt(2026, 6, 22, 3), 9, 17, []) == 6 * 3600


def test_window_all_seven_days_explicit():
    # An operator wanting weekends passes [0..6] explicitly. Sunday 03:00 → 09:00.
    held = compute_window_hold_seconds(_dt(2026, 6, 28, 3), 9, 17, [0, 1, 2, 3, 4, 5, 6])
    assert held == 6 * 3600


def test_window_is_configured():
    assert window_is_configured(9, 17, [0]) is True
    assert window_is_configured(None, None, None) is False


# ── caps ─────────────────────────────────────────────────────────────────────


def test_cap_zero_is_unlimited():
    assert is_over_cap(999, 0) is False


def test_cap_blocks_at_limit():
    assert is_over_cap(20, 20) is True
    assert is_over_cap(19, 20) is False


def test_counter_rolls_over_on_anchor_mismatch():
    today = date(2026, 6, 22)
    # 50 sends but anchored to YESTERDAY → effective today is 0.
    assert effective_count(50, date(2026, 6, 21), today) == 0
    assert is_over_cap(50, 20, date(2026, 6, 21), today) is False
    # anchored to TODAY → counts.
    assert is_over_cap(50, 20, today, today) is True


def test_next_reset_seconds_hour_and_day():
    now = _dt(2026, 6, 22, 14, 30)
    assert next_reset_seconds(now, "hour") == 30 * 60  # to 15:00
    assert next_reset_seconds(now, "day") == (9 * 3600 + 30 * 60)  # to midnight


# ── rotation ─────────────────────────────────────────────────────────────────

_TODAY = date(2026, 6, 22)
_HOUR = _dt(2026, 6, 22, 14)


def _acct(**kw):
    base = {
        "id": "a", "status": "active", "daily_cap": 0, "hourly_cap": 0,
        "sends_today": 0, "sends_this_hour": 0, "day_anchor": None,
        "hour_anchor": None, "warmup_target": None, "last_used_at": None,
    }
    base.update(kw)
    return base


def test_pick_lru_never_used_first():
    used = _acct(id="used", last_used_at=_dt(2026, 6, 20, 9))
    fresh = _acct(id="fresh", last_used_at=None)
    assert pick_lru([used, fresh], _TODAY, _HOUR)["id"] == "fresh"


def test_pick_lru_oldest_used_wins():
    older = _acct(id="older", last_used_at=_dt(2026, 6, 19, 9))
    newer = _acct(id="newer", last_used_at=_dt(2026, 6, 21, 9))
    assert pick_lru([newer, older], _TODAY, _HOUR)["id"] == "older"


def test_pick_lru_excludes_paused_banned_and_overcap():
    paused = _acct(id="p", status="paused")
    banned = _acct(id="b", status="banned")
    capped = _acct(id="c", daily_cap=5, sends_today=5, day_anchor=_TODAY)
    ok = _acct(id="ok", last_used_at=_dt(2026, 6, 1, 9))
    picked = pick_lru([paused, banned, capped, ok], _TODAY, _HOUR)
    assert picked["id"] == "ok"


def test_pick_lru_all_exhausted_returns_none():
    capped = _acct(id="c", daily_cap=5, sends_today=5, day_anchor=_TODAY)
    paused = _acct(id="p", status="paused")
    assert pick_lru([capped, paused], _TODAY, _HOUR) is None


def test_warming_uses_warmup_target_as_cap():
    # warming account, warmup_target 3, already 3 today → over cap, excluded.
    warming = _acct(id="w", status="warming", daily_cap=100, warmup_target=3,
                    sends_today=3, day_anchor=_TODAY)
    assert eligible_accounts([warming], _TODAY, _HOUR) == []


# ── resolution precedence (the backward-compat lock) ─────────────────────────


def test_precedence_node_pin_wins():
    assert resolve_send_source(node_account_id="acct-1", has_campaign_pool=True,
                               connection_name="smtp key") == "account_pin"


def test_precedence_pool_over_connection_name():
    assert resolve_send_source(node_account_id=None, has_campaign_pool=True,
                               connection_name="smtp key") == "campaign_pool"


def test_precedence_legacy_connection_name():
    # The critical case: an old saved graph with only connection_name → legacy path.
    assert resolve_send_source(node_account_id=None, has_campaign_pool=False,
                               connection_name="smtp key") == "connection_name"


def test_precedence_default_when_nothing_declared():
    assert resolve_send_source(node_account_id=None, has_campaign_pool=False,
                               connection_name=None) == "default"


# ── idempotency keys ─────────────────────────────────────────────────────────


def test_cap_hold_marker_distinct_per_reset_bucket():
    a = cap_hold_marker("node-1", 1000)
    b = cap_hold_marker("node-1", 2000)
    assert a["command_id"] == b["command_id"] == "cap-hold:node-1"
    assert a["retry_attempt"] != b["retry_attempt"]  # later bucket = genuine retry


def test_increment_claim_id_is_per_command():
    assert increment_claim_id("cmd-1") == "send-count:cmd-1"
    assert increment_claim_id("cmd-1") != increment_claim_id("cmd-2")
