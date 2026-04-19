from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.db import init_pool, close_pool, init_redis, close_redis
from app.routers import auth, campaigns, leads, sequences, templates, accounts, queue, job_search, lead_gen, settings as settings_router, overview, webhooks, notifications, activity, blacklist, tracking, analytics, template_library, inbox

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool(settings.get_asyncpg_dsn())
    await init_redis(settings.get_redis_url())
    from app.db import execute
    await execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS path_history JSONB DEFAULT '[]'")
    await execute("""
        CREATE TABLE IF NOT EXISTS lead_gen_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            config JSONB NOT NULL DEFAULT '{}',
            label TEXT,
            is_enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await execute("""
        CREATE TABLE IF NOT EXISTS lead_gen_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
            config_id UUID REFERENCES lead_gen_configs(id) ON DELETE SET NULL,
            source_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            leads_found INT DEFAULT 0,
            leads_added INT DEFAULT 0,
            started_at TIMESTAMPTZ DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            error TEXT,
            meta JSONB DEFAULT '{}'
        )
    """)
    await execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email TEXT")
    await execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            link TEXT,
            is_read BOOLEAN DEFAULT FALSE,
            meta JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await execute("CREATE INDEX IF NOT EXISTS idx_notif_user_unread ON notifications(user_id, is_read, created_at DESC)")
    await execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID,
            campaign_id UUID,
            lead_id UUID,
            action TEXT NOT NULL,
            detail TEXT,
            meta JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await execute("CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(created_at DESC)")
    await execute("""
        CREATE TABLE IF NOT EXISTS blacklists (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entry_type TEXT NOT NULL,
            value TEXT NOT NULL,
            reason TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(entry_type, value)
        )
    """)
    await execute("""
        CREATE TABLE IF NOT EXISTS template_library (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            name TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'email',
            category TEXT NOT NULL DEFAULT 'general',
            subject TEXT,
            body TEXT NOT NULL,
            variables TEXT[] DEFAULT '{}',
            is_public BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # Add scheduling columns to campaigns if not exist
    await execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS active_days INTEGER[] DEFAULT '{1,2,3,4,5,6}'")
    await execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS scheduled_start TIMESTAMPTZ")
    await execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS scheduled_pause TIMESTAMPTZ")
    # Integration keys table (encrypted at rest)
    await execute("""
        CREATE TABLE IF NOT EXISTS integration_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            field_name TEXT NOT NULL,
            encrypted_value TEXT NOT NULL,
            is_verified BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, provider, field_name)
        )
    """)
    await execute("CREATE INDEX IF NOT EXISTS idx_intkeys_user ON integration_keys(user_id)")
    yield
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
    allow_headers=["Authorization", "Content-Type"],
)

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
    return {"status": "ok"}
