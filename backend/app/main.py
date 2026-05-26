"""Omni v2 control plane.

Six routers: auth + workspaces + integrations + canvas + events + nodes.
Everything else is a projection over the event log. See
omni-vault/wiki/architecture/0001-v2-nuke.md for the ADR.
"""

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
from app.routers import (
    auth,
    auth_google,
    internal,
    oauth,
    oauth_producthunt,
    workspaces,
)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Omni v2 backend")
    await init_pool(settings.get_asyncpg_dsn())
    await init_redis(settings.get_redis_url())
    logger.info("Database and Redis connections established")
    yield
    logger.info("Shutting down — closing connections")
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

# v2 routers land here as they are built:
#   events, projections, nodes, canvas, inbox, integrations


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
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
