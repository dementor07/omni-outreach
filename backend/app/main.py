from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_pool, close_pool, init_redis, close_redis
from app.routers import auth, campaigns, leads, sequences, templates, accounts, queue, job_search, settings as settings_router, overview, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool(settings.get_asyncpg_dsn())
    await init_redis("redis://redis:6379")
    yield
    await close_pool()
    await close_redis()


app = FastAPI(title="Omni Outreach", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(leads.router, prefix="/leads", tags=["leads"])
app.include_router(sequences.router, prefix="/sequences", tags=["sequences"])
app.include_router(templates.router, prefix="/templates", tags=["templates"])
app.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
app.include_router(queue.router, prefix="/queue", tags=["queue"])
app.include_router(job_search.router, prefix="/job-search", tags=["job-search"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])
app.include_router(overview.router, prefix="/overview", tags=["overview"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
async def health():
    return {"status": "ok"}
