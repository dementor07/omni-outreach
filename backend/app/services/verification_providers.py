"""External email-verification provider adapters.

Adapters expose one conservative contract. Provider-specific marketing labels
are translated into Omni's evidence levels; raw API responses and credentials
never leave this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.email_verification import VerificationStatus


@dataclass(frozen=True)
class ProviderOutcome:
    status: VerificationStatus
    reason: str
    provider: str
    disposable: bool = False
    role_based: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def _hunter_outcome(data: dict[str, Any]) -> ProviderOutcome:
    status = str(data.get("status") or "").lower()
    score = int(data.get("score") or 0)
    details = {
        "score": score,
        "accept_all": bool(data.get("accept_all")),
        "smtp_check": bool(data.get("smtp_check")),
        "webmail": bool(data.get("webmail")),
    }
    if data.get("disposable") or data.get("block"):
        return ProviderOutcome(
            "invalid",
            "provider_do_not_mail",
            "hunter",
            disposable=bool(data.get("disposable")),
            details=details,
        )
    if status == "valid" and data.get("accept_all"):
        return ProviderOutcome("risky", "catch_all", "hunter", details=details)
    if status == "valid":
        return ProviderOutcome("verified", "provider_verified", "hunter", details=details)
    if status == "invalid":
        return ProviderOutcome("invalid", "provider_invalid", "hunter", details=details)
    if status in {"accept_all", "risky"}:
        return ProviderOutcome("risky", "catch_all", "hunter", details=details)
    return ProviderOutcome("unknown", "provider_unknown", "hunter", details=details)


async def verify_hunter(email: str, credentials: dict[str, Any], timeout: float) -> ProviderOutcome:
    api_key = str(credentials.get("api_key") or "")
    if not api_key:
        raise ValueError("missing_api_key")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": api_key},
        )
        response.raise_for_status()
    return _hunter_outcome((response.json() or {}).get("data") or {})


def _zerobounce_outcome(data: dict[str, Any]) -> ProviderOutcome:
    status = str(data.get("status") or "").lower()
    sub_status = str(data.get("sub_status") or "").lower()
    details = {"sub_status": sub_status, "free_email": bool(data.get("free_email"))}
    if status == "valid" and sub_status == "accept_all":
        return ProviderOutcome("risky", "catch_all", "zerobounce", details=details)
    if status == "valid":
        return ProviderOutcome("verified", "provider_verified", "zerobounce", details=details)
    if status in {"invalid", "spamtrap", "abuse"}:
        return ProviderOutcome("invalid", sub_status or f"provider_{status}", "zerobounce", details=details)
    if status == "do_not_mail":
        return ProviderOutcome(
            "invalid",
            sub_status or "provider_do_not_mail",
            "zerobounce",
            disposable=sub_status == "disposable",
            role_based=sub_status in {"role_based", "role_based_catch_all"},
            details=details,
        )
    if status in {"catch-all", "catch_all"}:
        return ProviderOutcome("risky", "catch_all", "zerobounce", details=details)
    return ProviderOutcome("unknown", sub_status or "provider_unknown", "zerobounce", details=details)


async def verify_zerobounce(email: str, credentials: dict[str, Any], timeout: float) -> ProviderOutcome:
    api_key = str(credentials.get("api_key") or "")
    if not api_key:
        raise ValueError("missing_api_key")
    base_url = str(credentials.get("base_url") or "https://api.zerobounce.net").rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{base_url}/v2/validate",
            params={"email": email, "api_key": api_key, "timeout": max(3, min(int(timeout), 60))},
        )
        response.raise_for_status()
    return _zerobounce_outcome(response.json() or {})


async def verify_with_provider(
    provider: str,
    email: str,
    credentials: dict[str, Any],
    timeout: float,
) -> ProviderOutcome:
    normalized = provider.strip().lower()
    if normalized == "hunter":
        return await verify_hunter(email, credentials, timeout)
    if normalized in {"zerobounce", "zero_bounce"}:
        return await verify_zerobounce(email, credentials, timeout)
    raise ValueError("unsupported_provider")
