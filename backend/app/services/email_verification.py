"""Email verification primitives for deliverability-safe sending.

The local verifier deliberately makes a narrow claim:

* syntax + MX checks can prove an address/domain is structurally invalid;
* they can identify obvious disposable and role-based risk;
* they cannot prove that a mailbox exists.

Only an external verification provider or a future safe SMTP-verification
worker should write ``status='verified'``. This avoids the common (and costly)
mistake of labelling every MX-bearing address as verified.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import dns.asyncresolver
import dns.exception
import dns.resolver
from email_validator import EmailNotValidError, validate_email

from app.db import execute, fetch_all, fetch_one, system_scope
from app.services.encryption import decrypt

VerificationStatus = Literal["verified", "valid_domain", "risky", "invalid", "unknown"]
VerificationPolicy = Literal["off", "block_invalid", "require_safe", "require_verified"]
MxLookup = Callable[[str], Awaitable[list[str]]]

ROLE_LOCAL_PARTS = frozenset(
    {
        "admin",
        "billing",
        "careers",
        "contact",
        "hello",
        "hr",
        "info",
        "jobs",
        "marketing",
        "office",
        "sales",
        "security",
        "support",
        "team",
    }
)

# Intentionally small and explicit. A maintained external dataset/provider will
# replace this seed list; the durable contract does not depend on its size.
DISPOSABLE_DOMAINS = frozenset(
    {
        "10minutemail.com",
        "guerrillamail.com",
        "mailinator.com",
        "sharklasers.com",
        "temp-mail.org",
        "tempmail.com",
        "yopmail.com",
    }
)


@dataclass(frozen=True)
class VerificationResult:
    email_normalized: str
    status: VerificationStatus
    reason: str
    provider: str
    mx_domain: str | None
    mx_hosts: list[str]
    disposable: bool
    role_based: bool
    checked_at: datetime
    expires_at: datetime
    details: dict[str, Any]

    def event_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checked_at"] = self.checked_at.isoformat()
        payload["expires_at"] = self.expires_at.isoformat()
        return payload


def result_from_record(record: dict[str, Any]) -> VerificationResult:
    """Restore a persisted result without weakening its provider provenance."""
    mx_hosts = record.get("mx_hosts") or []
    details = record.get("details") or {}
    if isinstance(mx_hosts, str):
        mx_hosts = json.loads(mx_hosts)
    if isinstance(details, str):
        details = json.loads(details)
    return VerificationResult(
        email_normalized=str(record["email_normalized"]),
        status=record["status"],
        reason=str(record["reason"]),
        provider=str(record["provider"]),
        mx_domain=record.get("mx_domain"),
        mx_hosts=list(mx_hosts),
        disposable=bool(record.get("disposable")),
        role_based=bool(record.get("role_based")),
        checked_at=record["checked_at"],
        expires_at=record["expires_at"],
        details=dict(details),
    )


async def _lookup_mx(domain: str) -> list[str]:
    answers = await dns.asyncresolver.resolve(domain, "MX", lifetime=5)
    rows = sorted(
        ((int(answer.preference), str(answer.exchange).rstrip(".").lower()) for answer in answers),
        key=lambda item: item[0],
    )
    return [host for _preference, host in rows if host and host != "."]


def _result(
    email: str,
    status: VerificationStatus,
    reason: str,
    *,
    domain: str | None = None,
    mx_hosts: list[str] | None = None,
    disposable: bool = False,
    role_based: bool = False,
    provider: str = "local_dns",
    ttl_days: int = 7,
    details: dict[str, Any] | None = None,
) -> VerificationResult:
    now = datetime.now(UTC)
    return VerificationResult(
        email_normalized=email,
        status=status,
        reason=reason,
        provider=provider,
        mx_domain=domain,
        mx_hosts=mx_hosts or [],
        disposable=disposable,
        role_based=role_based,
        checked_at=now,
        expires_at=now + timedelta(days=ttl_days),
        details=details or {},
    )


async def verify_email(
    email: str,
    *,
    mx_lookup: MxLookup | None = None,
) -> VerificationResult:
    """Verify syntax/domain evidence without claiming mailbox-level certainty."""
    raw = (email or "").strip()
    try:
        parsed = validate_email(raw, check_deliverability=False)
    except EmailNotValidError as exc:
        return _result(raw.lower(), "invalid", "invalid_syntax", details={"error": str(exc)})

    normalized = parsed.normalized.lower()
    local, domain = normalized.rsplit("@", 1)
    disposable = domain in DISPOSABLE_DOMAINS
    role_based = local in ROLE_LOCAL_PARTS
    if disposable:
        return _result(
            normalized,
            "invalid",
            "disposable_domain",
            domain=domain,
            disposable=True,
            role_based=role_based,
            ttl_days=30,
        )

    lookup = mx_lookup or _lookup_mx
    try:
        mx_hosts = await lookup(domain)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return _result(
            normalized,
            "invalid",
            "no_mx",
            domain=domain,
            role_based=role_based,
            ttl_days=3,
        )
    except (dns.exception.Timeout, dns.resolver.NoNameservers, OSError) as exc:
        return _result(
            normalized,
            "unknown",
            "dns_unavailable",
            domain=domain,
            role_based=role_based,
            ttl_days=1,
            details={"error": type(exc).__name__},
        )

    if not mx_hosts:
        return _result(
            normalized,
            "invalid",
            "no_mx",
            domain=domain,
            role_based=role_based,
            ttl_days=3,
        )
    if role_based:
        return _result(
            normalized,
            "risky",
            "role_based",
            domain=domain,
            mx_hosts=mx_hosts,
            role_based=True,
        )
    return _result(
        normalized,
        "valid_domain",
        "mx_present_mailbox_unverified",
        domain=domain,
        mx_hosts=mx_hosts,
    )


async def save_verification(workspace_id: str, result: VerificationResult) -> None:
    async with system_scope():
        await execute(
            """
            INSERT INTO omni_email_verifications (
                workspace_id, email_normalized, status, reason, provider,
                mx_domain, mx_hosts, disposable, role_based, checked_at,
                expires_at, details
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12::jsonb)
            ON CONFLICT (workspace_id, email_normalized) DO UPDATE SET
                status=EXCLUDED.status,
                reason=EXCLUDED.reason,
                provider=EXCLUDED.provider,
                mx_domain=EXCLUDED.mx_domain,
                mx_hosts=EXCLUDED.mx_hosts,
                disposable=EXCLUDED.disposable,
                role_based=EXCLUDED.role_based,
                checked_at=EXCLUDED.checked_at,
                expires_at=EXCLUDED.expires_at,
                details=EXCLUDED.details
            WHERE omni_email_verifications.status <> 'verified'
               OR omni_email_verifications.expires_at <= NOW()
               OR EXCLUDED.status = 'verified'
            """,
            workspace_id,
            result.email_normalized,
            result.status,
            result.reason,
            result.provider,
            result.mx_domain,
            json.dumps(result.mx_hosts),
            result.disposable,
            result.role_based,
            result.checked_at,
            result.expires_at,
            json.dumps(result.details),
        )


async def get_verification(workspace_id: str, email: str) -> dict[str, Any] | None:
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    async with system_scope():
        row = await fetch_one(
            """
            SELECT email_normalized, status, reason, provider, mx_domain,
                   mx_hosts, disposable, role_based, checked_at, expires_at, details
            FROM omni_email_verifications
            WHERE workspace_id=$1 AND email_normalized=$2
            """,
            workspace_id,
            normalized,
        )
    return dict(row) if row else None


async def _provider_connections(workspace_id: str) -> list[dict[str, Any]]:
    async with system_scope():
        rows = await fetch_all(
            """
            SELECT c.id, c.provider, c.credentials_encrypted, c.metadata,
                   s.consecutive_failures, s.open_until
            FROM omni_connections c
            LEFT JOIN omni_verification_provider_state s
              ON s.workspace_id=c.workspace_id AND s.connection_id=c.id
            WHERE c.workspace_id=$1
              AND c.provider IN ('hunter','zerobounce','zero_bounce')
              AND COALESCE((c.metadata->>'verification_enabled')::boolean, TRUE)
            ORDER BY COALESCE((c.metadata->>'verification_priority')::int, 100),
                     c.connected_at
            """,
            workspace_id,
        )
    return [dict(row) for row in rows]


def _provider_error_code(exc: Exception) -> str:
    try:
        import httpx

        if isinstance(exc, httpx.HTTPStatusError):
            return f"provider_http_{exc.response.status_code}"
        if isinstance(exc, httpx.TimeoutException):
            return "provider_timeout"
        if isinstance(exc, httpx.TransportError):
            return "provider_transport"
    except ImportError:
        pass
    message = str(exc)
    if message in {"missing_api_key", "unsupported_provider"}:
        return message
    return f"provider_{type(exc).__name__.lower()}"


async def _record_provider_attempt(
    workspace_id: str,
    email: str,
    connection_id: str,
    provider: str,
    ordinal: int,
    *,
    latency_ms: int,
    result: VerificationResult | None = None,
    error_code: str | None = None,
) -> None:
    async with system_scope():
        await execute(
            """
            INSERT INTO omni_email_verification_attempts (
                workspace_id, email_normalized, connection_id, provider, ordinal,
                status, reason, latency_ms, succeeded, error_code, details
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb)
            """,
            workspace_id,
            email,
            connection_id,
            provider,
            ordinal,
            result.status if result else None,
            result.reason if result else None,
            latency_ms,
            result is not None,
            error_code,
            json.dumps(result.details if result else {}),
        )


async def _mark_provider_success(
    workspace_id: str,
    connection_id: str,
    provider: str,
    status: VerificationStatus,
    latency_ms: int,
) -> None:
    async with system_scope():
        await execute(
            """
            INSERT INTO omni_verification_provider_state (
                workspace_id, connection_id, provider, success_count,
                consecutive_failures, last_status, last_latency_ms, last_checked_at
            )
            VALUES ($1,$2,$3,1,0,$4,$5,NOW())
            ON CONFLICT (workspace_id, connection_id) DO UPDATE SET
                provider=EXCLUDED.provider,
                success_count=omni_verification_provider_state.success_count + 1,
                consecutive_failures=0,
                last_status=EXCLUDED.last_status,
                last_error_code=NULL,
                last_latency_ms=EXCLUDED.last_latency_ms,
                last_checked_at=NOW(),
                open_until=NULL,
                updated_at=NOW()
            """,
            workspace_id,
            connection_id,
            provider,
            status,
            latency_ms,
        )


async def _mark_provider_failure(
    workspace_id: str,
    connection_id: str,
    provider: str,
    error_code: str,
    latency_ms: int,
) -> None:
    async with system_scope():
        await execute(
            """
            INSERT INTO omni_verification_provider_state (
                workspace_id, connection_id, provider, failure_count,
                consecutive_failures, last_error_code, last_latency_ms,
                last_checked_at, open_until
            )
            VALUES ($1,$2,$3,1,1,$4,$5,NOW(),NULL)
            ON CONFLICT (workspace_id, connection_id) DO UPDATE SET
                provider=EXCLUDED.provider,
                failure_count=omni_verification_provider_state.failure_count + 1,
                consecutive_failures=omni_verification_provider_state.consecutive_failures + 1,
                last_error_code=EXCLUDED.last_error_code,
                last_latency_ms=EXCLUDED.last_latency_ms,
                last_checked_at=NOW(),
                open_until=CASE
                    WHEN omni_verification_provider_state.consecutive_failures + 1 >= 3
                    THEN NOW() + INTERVAL '15 minutes'
                    ELSE omni_verification_provider_state.open_until
                END,
                updated_at=NOW()
            """,
            workspace_id,
            connection_id,
            provider,
            error_code,
            latency_ms,
        )


async def verify_and_save(workspace_id: str, email: str) -> VerificationResult:
    """Run local preflight then an ordered, failure-isolated provider waterfall."""
    existing = await get_verification(workspace_id, email)
    now = datetime.now(UTC)
    if (
        existing
        and existing.get("status") == "verified"
        and existing.get("expires_at")
        and existing["expires_at"] > now
    ):
        return result_from_record(existing)

    local_result = await verify_email(email)
    if local_result.status == "invalid":
        await save_verification(workspace_id, local_result)
        return local_result

    from app.services.verification_providers import verify_with_provider

    providers = await _provider_connections(workspace_id)
    strongest = local_result
    for ordinal, connection in enumerate(providers, start=1):
        connection_id = str(connection["id"])
        provider = str(connection["provider"]).lower()
        open_until = connection.get("open_until")
        if open_until and open_until > now:
            await _record_provider_attempt(
                workspace_id,
                local_result.email_normalized,
                connection_id,
                provider,
                ordinal,
                latency_ms=0,
                error_code="circuit_open",
            )
            continue

        started = time.monotonic()
        metadata = connection.get("metadata") or {}
        timeout = max(3.0, min(float(metadata.get("verification_timeout_seconds") or 12), 30.0))
        try:
            credentials = json.loads(decrypt(connection["credentials_encrypted"]))
            outcome = await verify_with_provider(
                provider,
                local_result.email_normalized,
                credentials,
                timeout,
            )
            latency_ms = max(0, int((time.monotonic() - started) * 1000))
            provider_result = _result(
                local_result.email_normalized,
                outcome.status,
                outcome.reason,
                domain=local_result.mx_domain,
                mx_hosts=local_result.mx_hosts,
                disposable=outcome.disposable or local_result.disposable,
                role_based=outcome.role_based or local_result.role_based,
                provider=outcome.provider,
                ttl_days=30 if outcome.status in {"verified", "invalid"} else 7,
                details={
                    **outcome.details,
                    "connection_id": connection_id,
                    "waterfall_ordinal": ordinal,
                },
            )
            await _record_provider_attempt(
                workspace_id,
                local_result.email_normalized,
                connection_id,
                provider,
                ordinal,
                latency_ms=latency_ms,
                result=provider_result,
            )
            await _mark_provider_success(
                workspace_id,
                connection_id,
                provider,
                provider_result.status,
                latency_ms,
            )
        except Exception as exc:  # noqa: BLE001 - provider failures must fall through
            latency_ms = max(0, int((time.monotonic() - started) * 1000))
            error_code = _provider_error_code(exc)
            await _record_provider_attempt(
                workspace_id,
                local_result.email_normalized,
                connection_id,
                provider,
                ordinal,
                latency_ms=latency_ms,
                error_code=error_code,
            )
            await _mark_provider_failure(
                workspace_id,
                connection_id,
                provider,
                error_code,
                latency_ms,
            )
            continue

        if provider_result.status in {"verified", "invalid"}:
            strongest = provider_result
            break
        if provider_result.status == "risky":
            strongest = provider_result

    await save_verification(workspace_id, strongest)
    persisted = await get_verification(workspace_id, strongest.email_normalized)
    return result_from_record(persisted) if persisted else strongest


def send_decision(
    verification: dict[str, Any] | None,
    policy: VerificationPolicy,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Pure send policy. Returns (allowed, reason)."""
    if policy == "off":
        return True, "verification_off"
    if not verification:
        return (policy == "block_invalid", "not_checked")

    now = now or datetime.now(UTC)
    expires_at = verification.get("expires_at")
    if expires_at and expires_at <= now:
        return (policy == "block_invalid", "verification_expired")

    status = verification.get("status")
    if status == "invalid":
        return False, str(verification.get("reason") or "invalid")
    if policy == "block_invalid":
        return True, str(status or "unknown")
    if policy == "require_safe":
        return status in {"verified", "valid_domain"}, str(status or "unknown")
    if policy == "require_verified":
        return status == "verified", str(status or "unknown")
    return False, "unknown_policy"
