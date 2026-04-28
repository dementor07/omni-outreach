"""
Generic API call logger for external services (Unipile, Sheets, etc.).
Writes one row per call to api_usage_log in the shared DB.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from db import execute

log = logging.getLogger(__name__)


def log_call(
    *,
    service: str,
    call_type: str,
    status: str,
    latency_ms: int,
    campaign_id: str | None = None,
    lead_id: str | None = None,
    error_msg: str | None = None,
) -> None:
    try:
        execute(
            """
            INSERT INTO api_usage_log
                (service, call_type, status, latency_ms, campaign_id, lead_id, error_msg)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (service, call_type, status, latency_ms, campaign_id, lead_id, error_msg),
        )
    except Exception:
        log.warning("api_usage: failed to log call", exc_info=True)


def track(service: str, call_type: str) -> Callable:
    """Decorator that times a function and logs to api_usage_log.

    The wrapped function may accept optional keyword args `campaign_id` and
    `lead_id` which are extracted for the log row and NOT forwarded to the
    underlying function.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            campaign_id = kwargs.pop("campaign_id", None)
            lead_id = kwargs.pop("lead_id", None)
            t0 = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                latency_ms = int((time.monotonic() - t0) * 1000)
                log_call(
                    service=service,
                    call_type=call_type,
                    status="success",
                    latency_ms=latency_ms,
                    campaign_id=campaign_id,
                    lead_id=lead_id,
                )
                return result
            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                log_call(
                    service=service,
                    call_type=call_type,
                    status="error",
                    latency_ms=latency_ms,
                    campaign_id=campaign_id,
                    lead_id=lead_id,
                    error_msg=str(exc)[:500],
                )
                raise
        return wrapper
    return decorator
