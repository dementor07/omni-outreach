from contextlib import asynccontextmanager
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import init_pool, close_pool, init_redis, close_redis
from app.logging_config import setup_logging, get_logger
from app.routers import auth, campaigns, leads, sequences, templates, accounts, queue, job_search, lead_gen, settings as settings_router, overview, webhooks, notifications, activity, blacklist, tracking, analytics, template_library, inbox

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
    logger.info("Starting Omni Outreach backend")
    await init_pool(settings.get_asyncpg_dsn())
    await init_redis(settings.get_redis_url())
    logger.info("Database and Redis connections established")
    yield
    logger.info("Shutting down — closing connections")
    await close_pool()
    await close_redis()


app = FastAPI(title="Omni Outreach", version="0.1.0", lifespan=lifespan)

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

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(leads.router, prefix="/leads", tags=["leads"])
app.include_router(sequences.router, prefix="/sequences", tags=["sequences"])
app.include_router(templates.router, prefix="/templates", tags=["templates"])
app.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
app.include_router(queue.router, prefix="/queue", tags=["queue"])
app.include_router(job_search.router, prefix="/job-search", tags=["job-search"])
app.include_router(lead_gen.router, prefix="/lead-gen", tags=["lead-gen"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])
app.include_router(overview.router, prefix="/overview", tags=["overview"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
app.include_router(activity.router, prefix="/activity", tags=["activity"])
app.include_router(blacklist.router, prefix="/blacklist", tags=["blacklist"])
app.include_router(tracking.router, prefix="/track", tags=["tracking"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(template_library.router, prefix="/template-library", tags=["template-library"])
app.include_router(inbox.router, prefix="/inbox", tags=["inbox"])


@app.get("/health")
async def health():
    from app.db import fetch_one, redis_client
    checks = {"api": "ok"}
    try:
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
