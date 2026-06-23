"""Deliverability P0: email verification and send-policy regression tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import dns.resolver
import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.services import email_verification  # noqa: E402
from app.services.email_verification import VerificationResult, send_decision, verify_email  # noqa: E402
from app.services import verification_providers  # noqa: E402
from app.services.verification_providers import ProviderOutcome, _hunter_outcome, _zerobounce_outcome  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_invalid_syntax_is_blocked_without_dns():
    result = await verify_email("not-an-email")
    assert result.status == "invalid"
    assert result.reason == "invalid_syntax"


@pytest.mark.asyncio
async def test_disposable_domain_is_invalid_without_dns():
    result = await verify_email("person@mailinator.com")
    assert result.status == "invalid"
    assert result.reason == "disposable_domain"
    assert result.disposable is True


@pytest.mark.asyncio
async def test_mx_present_is_not_overclaimed_as_mailbox_verified():
    async def mx(_domain: str) -> list[str]:
        return ["mx.example.com"]

    result = await verify_email("person@example.com", mx_lookup=mx)
    assert result.status == "valid_domain"
    assert result.reason == "mx_present_mailbox_unverified"


@pytest.mark.asyncio
async def test_role_address_is_risky():
    async def mx(_domain: str) -> list[str]:
        return ["mx.example.com"]

    result = await verify_email("sales@example.com", mx_lookup=mx)
    assert result.status == "risky"
    assert result.role_based is True


@pytest.mark.asyncio
async def test_no_mx_is_invalid():
    async def no_mx(_domain: str) -> list[str]:
        raise dns.resolver.NoAnswer

    result = await verify_email("person@example.com", mx_lookup=no_mx)
    assert result.status == "invalid"
    assert result.reason == "no_mx"


def test_send_policy_is_progressively_stricter():
    future = datetime.now(UTC) + timedelta(days=1)
    safe = {"status": "valid_domain", "expires_at": future}
    verified = {"status": "verified", "expires_at": future}
    risky = {"status": "risky", "expires_at": future}
    invalid = {"status": "invalid", "reason": "no_mx", "expires_at": future}

    assert send_decision(None, "block_invalid")[0] is True
    assert send_decision(invalid, "block_invalid")[0] is False
    assert send_decision(risky, "block_invalid")[0] is True
    assert send_decision(risky, "require_safe")[0] is False
    assert send_decision(safe, "require_safe")[0] is True
    assert send_decision(safe, "require_verified")[0] is False
    assert send_decision(verified, "require_verified")[0] is True


def test_expired_verification_does_not_satisfy_strict_policy():
    expired = {
        "status": "verified",
        "expires_at": datetime.now(UTC) - timedelta(seconds=1),
    }
    assert send_decision(expired, "block_invalid") == (True, "verification_expired")
    assert send_decision(expired, "require_verified") == (False, "verification_expired")


def test_deliverability_router_is_mounted():
    source = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    assert "deliverability.router" in source
    assert 'prefix="/deliverability"' in source


def test_verification_migration_has_rls_boundary():
    source = (ROOT / "backend/alembic/versions/041_email_verification.py").read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "app_current_workspace()" in source


@pytest.mark.asyncio
async def test_fresh_provider_verification_is_not_downgraded(monkeypatch):
    now = datetime.now(UTC)
    existing = {
        "email_normalized": "person@example.com",
        "status": "verified",
        "reason": "provider_safe",
        "provider": "waterfall",
        "mx_domain": "example.com",
        "mx_hosts": ["mx.example.com"],
        "disposable": False,
        "role_based": False,
        "checked_at": now,
        "expires_at": now + timedelta(days=1),
        "details": {},
    }

    async def get_existing(_workspace_id: str, _email: str):
        return existing

    async def should_not_verify(_email: str) -> VerificationResult:
        raise AssertionError("fresh provider evidence must be reused")

    monkeypatch.setattr(email_verification, "get_verification", get_existing)
    monkeypatch.setattr(email_verification, "verify_email", should_not_verify)

    result = await email_verification.verify_and_save("workspace", "person@example.com")
    assert result.status == "verified"
    assert result.provider == "waterfall"


def test_hunter_statuses_are_mapped_conservatively():
    assert _hunter_outcome({"status": "valid", "score": 98}).status == "verified"
    assert _hunter_outcome({"status": "valid", "accept_all": True}).status == "risky"
    assert _hunter_outcome({"status": "invalid"}).status == "invalid"
    assert _hunter_outcome({"status": "valid", "block": True}).status == "invalid"


def test_zerobounce_risk_statuses_are_not_overclaimed():
    assert _zerobounce_outcome({"status": "valid"}).status == "verified"
    assert _zerobounce_outcome({"status": "catch-all"}).status == "risky"
    assert _zerobounce_outcome({"status": "do_not_mail", "sub_status": "role_based"}).status == "invalid"
    assert _zerobounce_outcome({"status": "unknown"}).status == "unknown"


def test_waterfall_migration_has_attempts_circuit_and_sender_results():
    source = (ROOT / "backend/alembic/versions/042_deliverability_waterfall.py").read_text(encoding="utf-8")
    assert "omni_email_verification_attempts" in source
    assert "omni_verification_provider_state" in source
    assert "omni_sender_delivery_results" in source
    assert source.count("ENABLE ROW LEVEL SECURITY") >= 1


def test_sender_results_are_forwarded_and_projected():
    flink = (ROOT / "backend-flink/orchestrator.py").read_text(encoding="utf-8")
    worker = (ROOT / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
    projector = (ROOT / "backend/app/projector/main.py").read_text(encoding="utf-8")
    assert '"is_retriable": data.get("is_retriable")' in flink
    assert '"sender.delivery_result"' in worker
    assert "omni_sender_delivery_results" in projector


def test_verification_providers_are_operator_configurable():
    catalog = (ROOT / "frontend/src/utils/providerCatalog.ts").read_text(encoding="utf-8")
    assert "id: 'zerobounce'" in catalog
    assert catalog.count("verification_priority") >= 2
    assert catalog.count("verification_timeout_seconds") >= 2


@pytest.mark.asyncio
async def test_waterfall_falls_through_failed_provider_to_verified_provider(monkeypatch):
    now = datetime.now(UTC)
    local = VerificationResult(
        email_normalized="person@example.com",
        status="valid_domain",
        reason="mx_present_mailbox_unverified",
        provider="local_dns",
        mx_domain="example.com",
        mx_hosts=["mx.example.com"],
        disposable=False,
        role_based=False,
        checked_at=now,
        expires_at=now + timedelta(days=7),
        details={},
    )
    attempts: list[tuple[str, bool]] = []

    async def no_existing(_workspace_id: str, _email: str):
        return None

    async def local_check(_email: str):
        return local

    async def connections(_workspace_id: str):
        return [
            {"id": "one", "provider": "hunter", "credentials_encrypted": "x", "metadata": {}, "open_until": None},
            {"id": "two", "provider": "zerobounce", "credentials_encrypted": "x", "metadata": {}, "open_until": None},
        ]

    async def provider_check(provider: str, _email: str, _credentials: dict, _timeout: float):
        if provider == "hunter":
            raise RuntimeError("temporary provider failure")
        return ProviderOutcome("verified", "provider_verified", "zerobounce")

    async def record(_workspace_id: str, _email: str, _connection_id: str, provider: str, _ordinal: int, **kwargs):
        attempts.append((provider, kwargs.get("result") is not None))

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(email_verification, "get_verification", no_existing)
    monkeypatch.setattr(email_verification, "verify_email", local_check)
    monkeypatch.setattr(email_verification, "_provider_connections", connections)
    monkeypatch.setattr(email_verification, "_record_provider_attempt", record)
    monkeypatch.setattr(email_verification, "_mark_provider_failure", noop)
    monkeypatch.setattr(email_verification, "_mark_provider_success", noop)
    monkeypatch.setattr(email_verification, "save_verification", noop)
    monkeypatch.setattr(email_verification, "decrypt", lambda _value: '{"api_key":"test"}')
    monkeypatch.setattr(verification_providers, "verify_with_provider", provider_check)

    result = await email_verification.verify_and_save("workspace", "person@example.com")
    assert result.status == "verified"
    assert result.provider == "zerobounce"
    assert attempts == [("hunter", False), ("zerobounce", True)]
