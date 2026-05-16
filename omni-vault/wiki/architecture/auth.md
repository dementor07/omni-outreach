---
title: Authentication
category: architecture
tags: [auth, jwt, pbkdf2, fastapi, security]
updated: 2026-05-16
related: [[system-overview]], [[omni-api-tutorial]], [[postmortem-queue-sequence-crash-may-2026]]
---

# Authentication

`backend/app/auth.py` is the entire auth surface. JWT bearer tokens. PBKDF2-SHA256 password hashes. No sessions, no cookies, no refresh tokens.

## Contract

```python
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> str:
```

**`get_current_user` returns the JWT subject as a `str`.** Not a `dict`, not a user row, not an `Annotated` wrapper — a bare string that is the `users.id` UUID.

Every authenticated endpoint takes it as:

```python
async def list_things(
    ...,
    user_id: str = Depends(get_current_user),
):
```

The dependency itself is what owns the 401 path — if the JWT is missing, malformed, expired, or has no `sub` claim, it raises `HTTPException(401, "Invalid token")`. Handlers never have to check.

## Token format

- **Algorithm**: `HS256` (`settings.jwt_algorithm`, configurable but not changed in prod).
- **Lifetime**: `jwt_expire_minutes` from settings — currently 24h × 60 = 1440 minutes.
- **Payload**: `{"sub": <user_uuid>, "exp": <epoch>}`. Nothing else. No roles, no email, no scopes.
- **Signing key**: `settings.secret_key`, sourced from the `SECRET_KEY` env var. Loss = mass logout.

`create_access_token(user_id)` is the only minter; called from `POST /auth/login` and `POST /auth/register`.

## Password storage

```python
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
```

**PBKDF2-SHA256, not bcrypt.** `passlib` requires the verifier and the hasher to be the same major version, so password rotation runbooks must execute `hash_password()` inside the live backend container (see `omni-vault/credentials.local.md` for the canonical procedure). Never hash on your laptop and INSERT the result.

Database column: `users.password_hash TEXT NOT NULL`. Format: `$pbkdf2-sha256$29000$...$...`.

## The `user["id"]` bug class

**Don't annotate the parameter as `dict` and dereference `user["id"]`.** That's been a recurring bug:

- 2026-05-15: `notifications.py` had three handlers doing `user_id = str(user["id"])` against a string-typed dependency. Every `GET /api/notifications` 500'd with `TypeError: string indices must be integers, not 'str'`. The dashboard's notifications bell polled every 30s and silently dropped the result via TanStack Query retry. Fixed in `2a6cd8b`. Postmortem-style notes in [[log]] (2026-05-15 entry).
- Same pattern existed in `activity.py` as a type-lie (annotated `dict` but never indexed — runtime-safe but stylistically wrong). Same fix.

**The right shape**:

```python
@router.get("")
async def list_things(user_id: str = Depends(get_current_user)):
    rows = await fetch_all("SELECT ... WHERE user_id=$1", user_id)
```

**Wrong**:

```python
async def list_things(user: dict = Depends(get_current_user)):
    user_id = str(user["id"])  # runtime TypeError, get_current_user returns str
```

When a future handler needs *more* than just the user UUID (email, role, etc.), the right move is a separate dependency that *uses* `get_current_user` and joins to `users`:

```python
async def get_current_user_row(user_id: str = Depends(get_current_user)) -> dict:
    row = await fetch_one("SELECT * FROM users WHERE id=$1", user_id)
    if not row:
        raise HTTPException(401, "User not found")
    return row
```

Don't change the shape of `get_current_user` itself — too many call sites.

## Rate limiting

`POST /auth/register` is limited to 5/hour; `POST /auth/login` to 10/minute. Via SlowAPI on the FastAPI app instance (see `main.py:69`). The keying function is the client IP, not the user (the user doesn't exist yet at login).

## Frontend contract

`frontend/src/api/client.ts`:

- JWT stored in `localStorage['token']`.
- Request interceptor adds `Authorization: Bearer <token>` if the key is set.
- Response interceptor: on 401, clears `localStorage['token']` and hard-redirects to `/login`. All TanStack queries fail with the 401; the redirect happens before the rejection propagates to render.
- The SSE notification consumer (`useNotifications`) cannot use axios interceptors because `EventSource` bypasses them. It reads the token directly and appends it as a query param: `${apiBase}/notifications/stream?token=<jwt>`.

## Open gaps (flagged in audit-2026-05-16)

- **No refresh tokens.** A user's session dies hard at 24h. There's no way to extend it without re-typing the password. Adding refresh would require a separate `refresh_tokens` table with revocation support — currently nothing of the kind exists.
- **No token revocation.** Logout is purely client-side (clears localStorage). A leaked JWT is valid until its `exp` regardless of any server action.
- **No role-based scopes.** The system is single-tenant in practice; every user can do everything. Multi-tenant or role-based access control would require expanding the JWT payload (or going to opaque session tokens).
- **No 2FA.** Email/password only. Worth adding TOTP via `pyotp` if/when multi-tenant lands.

## Related Pages

- [[system-overview]] — pipeline / deploy context.
- [[omni-api-tutorial]] — full API reference (every endpoint that takes `get_current_user`).
- [[audit-2026-05-16]] — refresh-token gap + auth tech-debt enumeration.
- [[postmortem-queue-sequence-crash-may-2026]] — operationally-related (same time period, same chrome-devtools-mcp diagnostic loop surfaced the user["id"] bug).
