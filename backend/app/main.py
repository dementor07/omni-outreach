"""Omni v2 control plane.

Routers: auth + workspaces + integrations + canvas + events + nodes +
inbox + projections + ai (AI Studio: scoring/compose/enrich/classify).
Everything else is a projection over the event log. See
omni-vault/wiki/architecture/0001-v2-nuke.md for the ADR.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import close_pool, close_redis, init_pool, init_redis
from app.logging_config import get_logger, setup_logging
from app.nodes import discover as discover_nodes
from app.routers import (
    ai_studio,
    approvals,
    auth,
    auth_google,
    canvas,
    events,
    inbox,
    integrations,
    internal,
    nodes,
    oauth,
    oauth_producthunt,
    projections,
    webhooks_in,
    workspaces,
)
from app.services.bus import close_producer, init_producer

setup_logging()
logger = get_logger(__name__)

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject X-Request-ID into every request/response for tracing."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


async def _credential_sweep_loop(interval_seconds: int = 3600) -> None:
    """CMP2: periodically hard-delete released/expired credential_refs so the
    table doesn't grow unbounded. Runs on the backend (it holds the DB pool);
    the muscle only mints + redeems. Tolerant of transient failures — logs and
    retries on the next tick."""
    from app.routers.internal import sweep_expired_credentials

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            deleted = await sweep_expired_credentials()
            if deleted:
                logger.info("[credential-sweep] removed %d expired/released refs", deleted)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[credential-sweep] tick failed; will retry next interval")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Omni v2 backend")
    await init_pool(settings.get_asyncpg_dsn())
    await init_redis(settings.get_redis_url())
    await init_producer()
    discover_nodes()
    sweep_task = asyncio.create_task(_credential_sweep_loop())
    logger.info("Database, Redis, bus, node registry, and credential sweep initialised")
    yield
    logger.info("Shutting down — closing connections")
    sweep_task.cancel()
    try:
        await sweep_task
    except asyncio.CancelledError:
        pass
    await close_producer()
    await close_pool()
    await close_redis()


app = FastAPI(
    title="Omni v2",
    description="Streaming-native multi-tenant CRM with a pluggable canvas.",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

cors_origins = [o.strip() for o in settings.frontend_url.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.add_middleware(RequestIDMiddleware)

# Auth + tenancy
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(auth_google.router, prefix="/auth/google", tags=["auth"])
app.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])

# OAuth (will collapse into integrations.py once that lands)
app.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
app.include_router(oauth_producthunt.router, prefix="/oauth/producthunt", tags=["oauth"])

# Internal (muscle ↔ control plane)
app.include_router(internal.router, prefix="/internal", tags=["internal"])

# v2 surface
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(projections.router, prefix="/projections", tags=["projections"])
app.include_router(nodes.router, prefix="/nodes", tags=["nodes"])
app.include_router(canvas.router, prefix="/canvas", tags=["canvas"])
app.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
app.include_router(inbox.router, prefix="/inbox", tags=["inbox"])
app.include_router(ai_studio.router, prefix="/ai", tags=["ai"])
app.include_router(approvals.router, prefix="/approvals", tags=["approvals"])

# Inbound webhooks (source.webhook_in runtime). UNAUTHENTICATED by design —
# external systems POST here; trust comes from the opaque ids + optional HMAC.
app.include_router(webhooks_in.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
async def health():
    from app.db import fetch_one, redis_client, system_scope

    checks = {"api": "ok"}
    try:
        async with system_scope():
            row = await fetch_one("SELECT 1 AS ok")
        checks["db"] = "ok" if row else "error"
    except Exception as e:
        logger.warning("Health check DB failed: %s", e)
        checks["db"] = "error"
    try:
        if redis_client:
            await redis_client.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not_connected"
    except Exception as e:
        logger.warning("Health check Redis failed: %s", e)
        checks["redis"] = "error"

    # PY-001: surface any node that failed to import during discovery. A broken
    # node is silently missing from the palette otherwise; here it flips /health
    # to degraded and names the offending module(s).
    import app.nodes as noderegistry

    node_failures = noderegistry.import_failures()
    checks["nodes"] = "ok" if not node_failures else "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    body: dict[str, object] = {"status": status, "checks": checks}
    if node_failures:
        body["node_import_failures"] = node_failures
    return body
