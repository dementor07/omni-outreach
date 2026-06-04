"""asyncpg pool + Redis client + tenant-scoped query helpers.

Tenant isolation model
----------------------
Every query that flows through ``fetch_one`` / ``fetch_all`` / ``execute``
runs inside a short-lived transaction with::

    SET LOCAL app.workspace_id = '<uuid>'

set on the connection. Migration 020 turns on Postgres row-level security
on every owned table with a policy of::

    workspace_id = current_setting('app.workspace_id')::uuid

The net effect: even if a router forgets ``WHERE workspace_id=$N``, the
database silently filters cross-tenant rows out of the result. RLS is the
security boundary; explicit WHERE clauses are an index-plan optimisation.

The tenant is propagated through a ``ContextVar`` set by
``app.auth.get_current_workspace`` (FastAPI's request scope). Background
jobs and migrations that need cross-tenant access call ``system_scope()``
which sets ``app.workspace_id`` to the all-zero UUID — migration 020's
policy treats that as a superuser bypass.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar

import asyncpg
from redis import asyncio as aioredis

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
redis_client: aioredis.Redis | None = None

# Sentinel — RLS policy in migration 020 treats this as "system" and lets
# the query through regardless of workspace_id. Used by Alembic migrations,
# the worker bootstrap, and tasks that legitimately span tenants.
SYSTEM_WORKSPACE: str = "00000000-0000-0000-0000-000000000000"

# Request-scoped tenant. Default ``None`` means "no tenant set" — queries
# in that state are rejected by RLS unless they explicitly call
# ``system_scope()``. This is intentional: a missing tenant should fail
# loudly, not silently fall back to cross-tenant reads.
_current_workspace: ContextVar[str | None] = ContextVar(
    "_current_workspace", default=None
)


def set_request_workspace(workspace_id: str) -> None:
    """Bind a workspace_id to the current request's ContextVar.

    Called by ``app.auth.get_current_workspace``. Routers don't call this
    directly — the auth dependency does it for them."""
    _current_workspace.set(workspace_id)


def get_request_workspace() -> str | None:
    """Read the current request's workspace (None if unset)."""
    return _current_workspace.get()


@asynccontextmanager
async def system_scope() -> AsyncGenerator[None, None]:
    """Temporarily set the current workspace to ``SYSTEM_WORKSPACE``.

    Use only for: background workers iterating across all tenants,
    bootstrap tasks, cross-tenant analytics jobs, and migrations. Wrap the
    cross-tenant work in this context manager so RLS is bypassed for the
    duration::

        async with system_scope():
            await fetch_all("SELECT * FROM leads WHERE ...")
    """
    token = _current_workspace.set(SYSTEM_WORKSPACE)
    try:
        yield
    finally:
        _current_workspace.reset(token)


def _json_encode(value):
    """Encode for jsonb. Accept pre-serialized JSON strings unchanged so legacy
    callsites that still do their own json.dumps() before INSERT don't get
    double-stringified."""
    if isinstance(value, str):
        # Trust that the caller already produced valid JSON. If it's not valid
        # JSON, asyncpg's COPY will surface the syntax error from Postgres.
        return value
    return json.dumps(value)


async def _setup_connection(conn: asyncpg.Connection) -> None:
    """Register codecs so jsonb columns arrive as dict/list, not str."""
    await conn.set_type_codec(
        "jsonb",
        encoder=_json_encode,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=_json_encode,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_pool(dsn: str, *, retries: int = 30, backoff_s: float = 2.0) -> None:
    """Create the asyncpg pool, retrying while Postgres comes up.

    DEPLOY-004: db/redpanda live in the master compose project, so v2 workers
    can't `depends_on` them. On a cold boot the worker starts before Postgres is
    accepting connections; without this it would raise, exit, and crash-loop
    (restart: unless-stopped) churning the host. Retry-with-backoff lets the
    worker wait for infra instead. Bounded so a genuinely-misconfigured DSN
    still fails loudly rather than retrying forever."""
    global _pool
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            _pool = await asyncpg.create_pool(
                dsn, min_size=2, max_size=10, ssl=False, init=_setup_connection
            )
            if attempt > 1:
                log.info("[db] pool established on attempt %d", attempt)
            return
        except (asyncpg.InvalidPasswordError, asyncpg.InvalidCatalogNameError, asyncpg.InvalidAuthorizationSpecificationError):
            # Deterministic config errors — wrong password / missing database /
            # bad role. Retrying can't fix these; fail fast and loud.
            raise
        except (OSError, ConnectionError, asyncpg.CannotConnectNowError) as e:
            # Transient "infra not up yet" on cold boot — Postgres still starting,
            # network not ready. These are what the retry loop is for (DEPLOY-004).
            last_err = e
            log.warning(
                "[db] pool init attempt %d/%d failed (%s); retrying in %.1fs",
                attempt,
                retries,
                type(e).__name__,
                backoff_s,
            )
            await asyncio.sleep(backoff_s)
    raise RuntimeError(f"could not establish DB pool after {retries} attempts") from last_err


async def init_redis(url: str = "redis://redis:6379") -> None:
    global redis_client
    redis_client = aioredis.from_url(url, decode_responses=True)


async def close_pool() -> None:
    if _pool:
        await _pool.close()


async def close_redis() -> None:
    if redis_client:
        await redis_client.aclose()


@asynccontextmanager
async def acquire() -> AsyncGenerator[asyncpg.Connection, None]:
    """Acquire a connection with the tenant context bound for the txn.

    Refuses to yield a connection when no workspace is bound. Without this
    guard, RLS evaluates ``workspace_id = NULL`` (always false) and every
    query returns zero rows silently — turning auth/tenancy bugs into
    "the data disappeared" mysteries. Fail loud at the boundary instead.

    Callers that legitimately need cross-tenant access wrap in
    ``system_scope()``; callers that need raw access can use
    ``acquire_raw()``.
    """
    ws = _current_workspace.get()
    if ws is None:
        raise RuntimeError(
            "db.acquire() called with no workspace context — wrap in "
            "system_scope() for background work, or ensure the route "
            "depends on get_current_workspace."
        )
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.workspace_id', $1, true)", ws
            )
            yield conn


@asynccontextmanager
async def acquire_raw() -> AsyncGenerator[asyncpg.Connection, None]:
    """Acquire a connection WITHOUT binding a tenant context.

    Use only for: pool-level health checks, server startup probes, and
    any code path that runs before request scope exists. Any business
    query through this helper will be blocked by RLS unless the caller
    explicitly sets ``app.workspace_id`` itself."""
    async with _pool.acquire() as conn:
        yield conn


async def fetch_all(query: str, *args) -> list[dict]:
    async with acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]


async def fetch_one(query: str, *args) -> dict | None:
    async with acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None


async def execute(query: str, *args) -> str:
    async with acquire() as conn:
        return await conn.execute(query, *args)
