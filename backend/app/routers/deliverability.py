"""Operator-facing email verification and deliverability evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all, fetch_one
from app.services import email_verification

router = APIRouter()

VerificationStatus = Literal["verified", "valid_domain", "risky", "invalid", "unknown"]


class VerifyEmailIn(BaseModel):
    email: str = Field(min_length=1, max_length=320)


class VerificationOut(BaseModel):
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


class DeliverabilitySummary(BaseModel):
    total: int
    verified: int
    valid_domain: int
    risky: int
    invalid: int
    unknown: int
    expired: int


class ProviderHealthOut(BaseModel):
    connection_id: str
    connection_name: str
    provider: str
    priority: int
    success_count: int
    failure_count: int
    consecutive_failures: int
    last_status: str | None
    last_error_code: str | None
    last_latency_ms: int | None
    last_checked_at: datetime | None
    open_until: datetime | None


class SenderHealthOut(BaseModel):
    sending_account_id: str
    identity: str
    provider: str
    account_status: str
    sent_7d: int
    transient_failures_7d: int
    permanent_failures_7d: int
    health_status: Literal["healthy", "warning", "critical", "unknown"]
    last_event_at: datetime | None


@router.post("/verify", response_model=VerificationOut, summary="Verify and store an email address")
async def verify_address(
    body: VerifyEmailIn,
    ctx: AuthContext = Depends(get_current_workspace),
) -> VerificationOut:
    result = await email_verification.verify_and_save(ctx.workspace_id, body.email)
    return VerificationOut.model_validate(result, from_attributes=True)


@router.get(
    "/verifications",
    response_model=list[VerificationOut],
    summary="List recent email verification evidence",
)
async def list_verifications(
    status: VerificationStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthContext = Depends(get_current_workspace),
) -> list[VerificationOut]:
    rows = await fetch_all(
        """
        SELECT email_normalized, status, reason, provider, mx_domain, mx_hosts,
               disposable, role_based, checked_at, expires_at
        FROM omni_email_verifications
        WHERE ($1::text IS NULL OR status=$1)
        ORDER BY checked_at DESC
        LIMIT $2
        """,
        status,
        limit,
    )
    return [VerificationOut.model_validate(row) for row in rows]


@router.get("/summary", response_model=DeliverabilitySummary, summary="Summarise verification evidence")
async def summary(_: AuthContext = Depends(get_current_workspace)) -> DeliverabilitySummary:
    row = await fetch_one(
        """
        SELECT
            COUNT(*)::int AS total,
            COUNT(*) FILTER (WHERE status='verified' AND expires_at > NOW())::int AS verified,
            COUNT(*) FILTER (WHERE status='valid_domain' AND expires_at > NOW())::int AS valid_domain,
            COUNT(*) FILTER (WHERE status='risky' AND expires_at > NOW())::int AS risky,
            COUNT(*) FILTER (WHERE status='invalid' AND expires_at > NOW())::int AS invalid,
            COUNT(*) FILTER (WHERE status='unknown' AND expires_at > NOW())::int AS unknown,
            COUNT(*) FILTER (WHERE expires_at <= NOW())::int AS expired
        FROM omni_email_verifications
        """
    )
    return DeliverabilitySummary.model_validate(row)


@router.get(
    "/providers",
    response_model=list[ProviderHealthOut],
    summary="List verification waterfall stages and circuit health",
)
async def provider_health(_: AuthContext = Depends(get_current_workspace)) -> list[ProviderHealthOut]:
    rows = await fetch_all(
        """
        SELECT c.id::text AS connection_id, c.name AS connection_name, c.provider,
               COALESCE((c.metadata->>'verification_priority')::int, 100) AS priority,
               COALESCE(s.success_count, 0)::int AS success_count,
               COALESCE(s.failure_count, 0)::int AS failure_count,
               COALESCE(s.consecutive_failures, 0) AS consecutive_failures,
               s.last_status, s.last_error_code, s.last_latency_ms,
               s.last_checked_at, s.open_until
        FROM omni_connections c
        LEFT JOIN omni_verification_provider_state s
          ON s.workspace_id=c.workspace_id AND s.connection_id=c.id
        WHERE c.provider IN ('hunter','zerobounce','zero_bounce')
          AND COALESCE((c.metadata->>'verification_enabled')::boolean, TRUE)
        ORDER BY COALESCE((c.metadata->>'verification_priority')::int, 100),
                 c.connected_at
        """
    )
    return [ProviderHealthOut.model_validate(row) for row in rows]


@router.get(
    "/sender-health",
    response_model=list[SenderHealthOut],
    summary="List seven-day email sender transport health",
)
async def sender_health(_: AuthContext = Depends(get_current_workspace)) -> list[SenderHealthOut]:
    rows = await fetch_all(
        """
        WITH health AS (
            SELECT sending_account_id,
                   COUNT(*) FILTER (WHERE status='sent')::int AS sent_7d,
                   COUNT(*) FILTER (
                       WHERE status='failed' AND retriable
                   )::int AS transient_failures_7d,
                   COUNT(*) FILTER (
                       WHERE status='failed' AND NOT retriable
                   )::int AS permanent_failures_7d,
                   MAX(occurred_at) AS last_event_at
            FROM omni_sender_delivery_results
            WHERE occurred_at >= NOW() - INTERVAL '7 days'
            GROUP BY sending_account_id
        )
        SELECT a.id::text AS sending_account_id,
               a.external_identity AS identity,
               a.provider,
               a.status AS account_status,
               COALESCE(h.sent_7d, 0) AS sent_7d,
               COALESCE(h.transient_failures_7d, 0) AS transient_failures_7d,
               COALESCE(h.permanent_failures_7d, 0) AS permanent_failures_7d,
               CASE
                   WHEN h.last_event_at IS NULL THEN 'unknown'
                   WHEN a.status IN ('paused','banned') THEN 'critical'
                   WHEN h.permanent_failures_7d >= 3 THEN 'critical'
                   WHEN h.permanent_failures_7d > 0 OR h.transient_failures_7d >= 3 THEN 'warning'
                   ELSE 'healthy'
               END AS health_status,
               h.last_event_at
        FROM omni_sending_accounts a
        LEFT JOIN health h ON h.sending_account_id=a.id
        WHERE a.channel_kind='email'
        ORDER BY
            CASE
                WHEN a.status IN ('paused','banned') THEN 0
                WHEN h.permanent_failures_7d >= 3 THEN 0
                WHEN h.permanent_failures_7d > 0 OR h.transient_failures_7d >= 3 THEN 1
                WHEN h.last_event_at IS NULL THEN 2
                ELSE 3
            END,
            a.created_at
        """
    )
    return [SenderHealthOut.model_validate(row) for row in rows]
