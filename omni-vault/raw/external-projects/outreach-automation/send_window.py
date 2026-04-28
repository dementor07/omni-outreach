from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import config
from db import requeue_task


def _parse_days(days_str: str):
    if not days_str:
        return {0, 1, 2, 3, 4}
    mapping = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    out = set()
    for part in days_str.split(","):
        key = part.strip()[:3].title()
        if key in mapping:
            out.add(mapping[key])
    return out or {0, 1, 2, 3, 4}


def _in_send_window(local_now, start_hour, end_hour, allowed_days):
    if local_now.weekday() not in allowed_days:
        return False
    hour = local_now.hour
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _next_window_start(local_now, start_hour, end_hour, allowed_days):
    if local_now.weekday() in allowed_days:
        if start_hour <= end_hour:
            if local_now.hour < start_hour:
                return local_now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        else:
            if end_hour <= local_now.hour < start_hour:
                return local_now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    for i in range(1, 8):
        candidate = local_now + timedelta(days=i)
        if candidate.weekday() in allowed_days:
            return candidate.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return (local_now + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)



def ensure_send_window(task: dict, cfg: dict) -> bool:
    """Returns True if within send window. Requeues task and returns False if not."""
    account_id = task.get("account_id", "")

    mode = (cfg.get("OUTBOUND_TIMEZONE_MODE") or config.cfg("OUTBOUND_TIMEZONE_MODE", "account")).lower()
    default_tz = cfg.get("DEFAULT_ACCOUNT_TIMEZONE") or config.cfg("DEFAULT_ACCOUNT_TIMEZONE", "UTC")
    days_str = cfg.get("SEND_WINDOW_DAYS") or config.cfg("SEND_WINDOW_DAYS", "Mon,Tue,Wed,Thu,Fri")
    start_raw = cfg.get("SEND_WINDOW_START_HOUR")
    start_hour = int(start_raw if start_raw is not None else config.cfg("SEND_WINDOW_START_HOUR", 9))
    end_raw = cfg.get("SEND_WINDOW_END_HOUR")
    end_hour = int(end_raw if end_raw is not None else config.cfg("SEND_WINDOW_END_HOUR", 18))

    account_tz_map = cfg.get("ACCOUNT_TIMEZONES") or {}
    tz_name = account_tz_map.get(account_id) or default_tz if mode == "account" else default_tz

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    now_utc = datetime.now(timezone.utc)
    local_now = now_utc.astimezone(tz)
    allowed_days = _parse_days(days_str)

    if _in_send_window(local_now, start_hour, end_hour, allowed_days):
        return True

    next_local = _next_window_start(local_now, start_hour, end_hour, allowed_days)
    next_utc = next_local.astimezone(timezone.utc)
    window_delay = max(60, int((next_utc - now_utc).total_seconds()))

    # Add per-task jitter so tasks that all miss the window don't pile up at window open.
    # Use the same delay range as the inter-send delay config.
    jitter_min = int(config.cfg("INVITE_DELAY_MIN", 90))
    jitter_max = int(config.cfg("INVITE_DELAY_MAX", 240))
    import random as _random
    jitter = _random.randint(0, jitter_max - jitter_min) + jitter_min

    requeue_task(task["queue_id"], delay_seconds=window_delay + jitter)
    return False
