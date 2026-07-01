"""Outbound webhook subscription CRUD (N8N-001 Part 2c).

A workspace registers URLs to receive its domain events (lead replied, invite
accepted, campaign completed, lead enriched, hot lead). The fan-out worker
(app.execution.webhook_dispatch_worker) delivers HMAC-signed envelopes to these.

JWT- or API-key-authed (``get_workspace_any``). URLs are SSRF-validated at
create AND edit (the worker re-validates at send). A per-subscription ``secret``
signs deliveries; if the caller doesn't supply one we generate it and return it
ONCE.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import AuthContext
from app.auth_apikey import get_workspace_any
from app.db import execute, fetch_all, fetch_one
from app.services import webhook_events
from app.services.url_guard import UnsafeURLError, validate_outbound_url

router = APIRouter()


class SubscriptionCreate(BaseModel):
    url: str = Field(examples=["https://example.app.n8n.cloud/webhook/omni"])
    event_types: list[str] = Field(
        default_factory=list,
        description=f"Events to deliver (empty = all supported: {sorted(webhook_events.ALLOWED_EVENTS)})",
    )
    secret: str | None = Field(None, description="HMAC secret; generated if omitted")


class SubscriptionUpdate(BaseModel):
    url: str | None = None
    event_types: list[str] | None = None
    active: bool | None = None


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    url: str
    event_types: list[str]
    active: bool
    last_delivery_at: datetime | None
    last_status: int | None
    created_at: datetime
    # secret returned ONLY on create; None on list/get.
    secret: str | None = None


def _validate_events(event_types: list[str]) -> None:
    unknown = [e for e in event_types if e not in webhook_events.ALLOWED_EVENTS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported event_types {unknown}; allowed: {sorted(webhook_events.ALLOWED_EVENTS)}",
        )


def _validate_url(url: str) -> None:
    try:
        validate_outbound_url(url, resolve=True)
    except UnsafeURLError as e:
        raise HTTPException(status_code=422, detail=f"unsafe webhook URL: {e}") from e


@router.post(
    "",
    response_model=SubscriptionOut,
    status_code=201,
    summary="Create an outbound webhook subscription",
    description=(
        "Register a public HTTPS URL to receive HMAC-signed domain events. The "
        "`secret` (supplied or generated) is returned ONCE — store it to verify "
        "the `X-Omni-Signature` header on each delivery."
    ),
)
async def create_subscription(
    body: SubscriptionCreate, ctx: AuthContext = Depends(get_workspace_any)
) -> SubscriptionOut:
    _validate_url(body.url)
    _validate_events(body.event_types)
    secret = body.secret or secrets.token_urlsafe(32)
    row = await fetch_one(
        """
        INSERT INTO omni_webhook_subscriptions (workspace_id, url, event_types, secret, created_by)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, url, event_types, active, last_delivery_at, last_status, created_at
        """,
        ctx.workspace_id, body.url, body.event_types, secret, ctx.user_id or None,
    )
    out = SubscriptionOut.model_validate(row)
    return out.model_copy(update={"secret": secret})


@router.get(
    "",
    response_model=list[SubscriptionOut],
    summary="List outbound webhook subscriptions",
)
async def list_subscriptions(_: AuthContext = Depends(get_workspace_any)) -> list[SubscriptionOut]:
    rows = await fetch_all(
        "SELECT id, url, event_types, active, last_delivery_at, last_status, created_at "
        "FROM omni_webhook_subscriptions ORDER BY created_at DESC"
    )
    return [SubscriptionOut.model_validate(r) for r in rows]


@router.patch(
    "/{sub_id}",
    response_model=SubscriptionOut,
    summary="Edit a subscription (URL / events / active)",
)
async def update_subscription(
    sub_id: uuid.UUID, body: SubscriptionUpdate, ctx: AuthContext = Depends(get_workspace_any)
) -> SubscriptionOut:
    existing = await fetch_one(
        "SELECT id FROM omni_webhook_subscriptions WHERE id = $1", sub_id
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")

    sets: list[str] = []
    args: list[object] = []
    if body.url is not None:
        _validate_url(body.url)
        args.append(body.url)
        sets.append(f"url = ${len(args)}")
    if body.event_types is not None:
        _validate_events(body.event_types)
        args.append(body.event_types)
        sets.append(f"event_types = ${len(args)}")
    if body.active is not None:
        args.append(body.active)
        sets.append(f"active = ${len(args)}")
    if not sets:
        raise HTTPException(status_code=422, detail="nothing to update")
    args.append(sub_id)
    row = await fetch_one(
        f"UPDATE omni_webhook_subscriptions SET {', '.join(sets)} WHERE id = ${len(args)} "
        "RETURNING id, url, event_types, active, last_delivery_at, last_status, created_at",
        *args,
    )
    return SubscriptionOut.model_validate(row)


@router.delete(
    "/{sub_id}",
    status_code=204,
    summary="Delete a subscription",
)
async def delete_subscription(
    sub_id: uuid.UUID, _: AuthContext = Depends(get_workspace_any)
) -> None:
    result = await execute("DELETE FROM omni_webhook_subscriptions WHERE id = $1", sub_id)
    if result.endswith(" 0"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")


@router.post(
    "/{sub_id}/test",
    summary="Send a synthetic ping to a subscription",
    description="Delivers a signed `ping` event so you can wire + verify the receiver before going live.",
)
async def test_subscription(
    sub_id: uuid.UUID, ctx: AuthContext = Depends(get_workspace_any)
) -> dict[str, object]:
    row = await fetch_one(
        "SELECT id, url, secret FROM omni_webhook_subscriptions WHERE id = $1", sub_id
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")
    status_code, error = await webhook_events.deliver_one(
        url=row["url"],
        secret=row["secret"],
        event="ping",
        workspace_id=str(ctx.workspace_id),
        data={"message": "This is a test delivery from Omni."},
    )
    return {"delivered": error is None, "status_code": status_code, "error": error}
