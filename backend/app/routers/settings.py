"""Integration key management and application settings.

Provides CRUD for encrypted API keys with masked read, verification per provider.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one
from app.services.encryption import decrypt, encrypt, mask

router = APIRouter()
log = logging.getLogger(__name__)

# ── Provider Registry ────────────────────────────────────────────────────────

PROVIDERS = {
    "unipile": {"label": "Unipile", "fields": ["api_key", "base_url"], "required": ["api_key", "base_url"]},
    "retell": {"label": "Retell AI", "fields": ["api_key"], "required": ["api_key"]},
    "resend": {"label": "Resend", "fields": ["api_key"], "required": ["api_key"]},
    "anthropic": {"label": "Anthropic", "fields": ["api_key"], "required": ["api_key"]},
    "apify": {"label": "Apify", "fields": ["api_key"], "required": ["api_key"]},
    "serper": {"label": "Serper", "fields": ["api_key"], "required": ["api_key"]},
    "apollo": {"label": "Apollo.io", "fields": ["api_key"], "required": ["api_key"]},
    "hunter": {"label": "Hunter.io", "fields": ["api_key"], "required": ["api_key"]},
    "proxycurl": {"label": "ProxyCurl", "fields": ["api_key"], "required": ["api_key"]},
    "github": {"label": "GitHub", "fields": ["token"], "required": ["token"]},
    "twilio": {
        "label": "Twilio SMS",
        "fields": ["account_sid", "auth_token", "from_number"],
        "required": ["account_sid", "auth_token", "from_number"],
    },
}


# ── Models ───────────────────────────────────────────────────────────────────


class IntegrationKeyUpsert(BaseModel):
    provider: str
    field_name: str
    value: str


class IntegrationKeyDelete(BaseModel):
    provider: str
    field_name: str


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/integrations/providers")
async def list_providers(_user: str = Depends(get_current_user)):
    """List all supported integration providers and their required fields."""
    return PROVIDERS


@router.get("/integrations")
async def list_integration_keys(user_id: str = Depends(get_current_user)):
    """List all stored integration keys (masked values)."""
    rows = await fetch_all(
        "SELECT id, provider, field_name, encrypted_value, is_verified, updated_at FROM integration_keys WHERE user_id=$1 ORDER BY provider, field_name",
        user_id,
    )
    result = []
    for row in rows:
        try:
            plaintext = decrypt(row["encrypted_value"])
            masked = mask(plaintext)
        except ValueError:
            masked = "••••(corrupted)"
        result.append(
            {
                "id": str(row["id"]),
                "provider": row["provider"],
                "field_name": row["field_name"],
                "masked_value": masked,
                "is_verified": row["is_verified"],
                "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
            }
        )
    return result


@router.put("/integrations")
async def upsert_integration_key(body: IntegrationKeyUpsert, user_id: str = Depends(get_current_user)):
    """Create or update an integration key (encrypted at rest)."""
    if body.provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {body.provider}")
    valid_fields = PROVIDERS[body.provider]["fields"]
    if body.field_name not in valid_fields:
        raise HTTPException(
            400, f"Invalid field '{body.field_name}' for provider '{body.provider}'. Valid: {valid_fields}"
        )
    if not body.value.strip():
        raise HTTPException(400, "Value cannot be empty")

    encrypted = encrypt(body.value.strip())
    row = await fetch_one(
        """INSERT INTO integration_keys (user_id, provider, field_name, encrypted_value)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id, provider, field_name) DO UPDATE
           SET encrypted_value = EXCLUDED.encrypted_value, is_verified = FALSE, updated_at = NOW()
           RETURNING id, provider, field_name, updated_at""",
        user_id,
        body.provider,
        body.field_name,
        encrypted,
    )
    return {
        **row,
        "id": str(row["id"]),
        "masked_value": mask(body.value.strip()),
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


@router.delete("/integrations")
async def delete_integration_key(body: IntegrationKeyDelete, user_id: str = Depends(get_current_user)):
    """Remove an integration key."""
    await execute(
        "DELETE FROM integration_keys WHERE user_id=$1 AND provider=$2 AND field_name=$3",
        user_id,
        body.provider,
        body.field_name,
    )
    return {"status": "deleted"}


@router.post("/integrations/{provider}/verify")
async def verify_integration(provider: str, user_id: str = Depends(get_current_user)):
    """Test an integration key by making a lightweight API call to the provider."""
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")

    keys = await _get_provider_keys(user_id, provider)
    required = PROVIDERS[provider]["required"]
    missing = [f for f in required if f not in keys]
    if missing:
        raise HTTPException(400, f"Missing required fields: {missing}")

    try:
        ok, detail = await _verify_provider(provider, keys)
    except Exception as e:
        log.warning(f"Verification failed for {provider}: {e}")
        ok, detail = False, str(e)

    # Update verification status
    for field_name in keys:
        await execute(
            "UPDATE integration_keys SET is_verified=$1 WHERE user_id=$2 AND provider=$3 AND field_name=$4",
            ok,
            user_id,
            provider,
            field_name,
        )

    return {"provider": provider, "verified": ok, "detail": detail}


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_provider_keys(user_id: str, provider: str) -> dict[str, str]:
    """Retrieve and decrypt all keys for a provider."""
    rows = await fetch_all(
        "SELECT field_name, encrypted_value FROM integration_keys WHERE user_id=$1 AND provider=$2",
        user_id,
        provider,
    )
    result = {}
    for row in rows:
        try:
            result[row["field_name"]] = decrypt(row["encrypted_value"])
        except ValueError:
            pass
    return result


async def get_integration_key(user_id: str, provider: str, field_name: str) -> str | None:
    """Get a single decrypted key. Falls back to env var via config if not in DB."""
    from app.config import settings as cfg

    row = await fetch_one(
        "SELECT encrypted_value FROM integration_keys WHERE user_id=$1 AND provider=$2 AND field_name=$3",
        user_id,
        provider,
        field_name,
    )
    if row:
        try:
            return decrypt(row["encrypted_value"])
        except ValueError:
            pass
    # Fallback to env vars
    env_map = {
        ("unipile", "api_key"): cfg.unipile_api_key,
        ("unipile", "base_url"): cfg.unipile_base,
        ("retell", "api_key"): cfg.retell_api_key,
        ("resend", "api_key"): cfg.resend_api_key,
        ("anthropic", "api_key"): cfg.anthropic_api_key,
        ("apify", "api_key"): cfg.apify_api_key,
        ("serper", "api_key"): cfg.serper_api_key,
        ("apollo", "api_key"): cfg.apollo_api_key,
        ("hunter", "api_key"): cfg.hunter_api_key,
        ("proxycurl", "api_key"): cfg.proxycurl_api_key,
        ("github", "token"): cfg.github_token,
    }
    return env_map.get((provider, field_name), "") or None


async def _verify_provider(provider: str, keys: dict[str, str]) -> tuple[bool, str]:
    """Make a lightweight API call to verify credentials."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        if provider == "unipile":
            r = await client.get(
                f"{keys['base_url'].rstrip('/')}/api/v1/users/me",
                headers={"X-API-KEY": keys["api_key"]},
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "retell":
            r = await client.get(
                "https://api.retellai.com/v2/agent",
                headers={"Authorization": f"Bearer {keys['api_key']}"},
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "resend":
            r = await client.get(
                "https://api.resend.com/domains",
                headers={"Authorization": f"Bearer {keys['api_key']}"},
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "anthropic":
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": keys["api_key"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "apify":
            r = await client.get(
                "https://api.apify.com/v2/acts",
                params={"token": keys["api_key"], "limit": 1},
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "serper":
            r = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": keys["api_key"], "Content-Type": "application/json"},
                json={"q": "test", "num": 1},
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "apollo":
            r = await client.post(
                "https://api.apollo.io/v1/people/search",
                headers={"x-api-key": keys["api_key"], "Content-Type": "application/json"},
                json={"page": 1, "per_page": 1},
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "hunter":
            r = await client.get(
                "https://api.hunter.io/v2/account",
                params={"api_key": keys["api_key"]},
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "proxycurl":
            r = await client.get(
                "https://nubela.co/proxycurl/api/v2/linkedin",
                headers={"Authorization": f"Bearer {keys['api_key']}"},
                params={"url": "https://www.linkedin.com/in/williamhgates"},
            )
            return r.status_code in (200, 403), f"HTTP {r.status_code}"

        if provider == "github":
            r = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {keys['token']}"},
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

        if provider == "twilio":
            r = await client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{keys['account_sid']}.json",
                auth=(keys["account_sid"], keys["auth_token"]),
            )
            return r.status_code == 200, f"HTTP {r.status_code}"

    return False, "Unknown provider"


# ── Notification channels ───────────────────────────────────────────────────

_CHANNEL_COLS = "id, channel_type, name, config, is_active, created_at"


class NotificationChannelCreate(BaseModel):
    channel_type: str  # 'slack' | 'email'
    name: str
    config: dict


class NotificationChannelUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    is_active: bool | None = None


@router.get("/notification-channels")
async def list_notification_channels(user_id: str = Depends(get_current_user)):
    rows = await fetch_all(f"SELECT {_CHANNEL_COLS} FROM notification_channels ORDER BY created_at DESC")
    return rows


@router.post("/notification-channels", status_code=201)
async def create_notification_channel(
    body: NotificationChannelCreate,
    user_id: str = Depends(get_current_user),
):
    if body.channel_type not in ("slack", "email"):
        raise HTTPException(status_code=400, detail=f"Unsupported channel_type: {body.channel_type}")
    if body.channel_type == "slack" and not body.config.get("webhook_url"):
        raise HTTPException(status_code=400, detail="Slack channel requires config.webhook_url")
    if body.channel_type == "email" and not body.config.get("to"):
        raise HTTPException(status_code=400, detail="Email channel requires config.to")

    row = await fetch_one(
        f"""
        INSERT INTO notification_channels (channel_type, name, config)
        VALUES ($1, $2, $3)
        RETURNING {_CHANNEL_COLS}
        """,
        body.channel_type,
        body.name,
        body.config,
    )
    return row


@router.patch("/notification-channels/{channel_id}")
async def update_notification_channel(
    channel_id: str,
    body: NotificationChannelUpdate,
    user_id: str = Depends(get_current_user),
):
    existing = await fetch_one("SELECT id FROM notification_channels WHERE id=$1", channel_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Channel not found")

    sets: list[str] = []
    params: list = []
    for col, val in [("name", body.name), ("config", body.config), ("is_active", body.is_active)]:
        if val is not None:
            params.append(val)
            sets.append(f"{col}=${len(params)}")
    if not sets:
        row = await fetch_one(f"SELECT {_CHANNEL_COLS} FROM notification_channels WHERE id=$1", channel_id)
        return row
    params.append(channel_id)
    row = await fetch_one(
        f"UPDATE notification_channels SET {', '.join(sets)} WHERE id=${len(params)} RETURNING {_CHANNEL_COLS}",
        *params,
    )
    return row


@router.delete("/notification-channels/{channel_id}", status_code=204)
async def delete_notification_channel(channel_id: str, user_id: str = Depends(get_current_user)):
    await execute("DELETE FROM notification_channels WHERE id=$1", channel_id)
