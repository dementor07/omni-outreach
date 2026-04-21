"""Initial schema — consolidated from schema.sql + main.py lifespan

Revision ID: 001
Revises: None
Create Date: 2026-04-19

"""
from collections.abc import Sequence

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ── Auth ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            token TEXT PRIMARY KEY,
            user_id UUID REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL
        )
    """)

    # ── Sender accounts ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS linkedin_accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            unipile_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            email TEXT,
            daily_invite_cap INTEGER NOT NULL DEFAULT 20,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS email_accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            from_name TEXT NOT NULL,
            from_email TEXT NOT NULL UNIQUE,
            smtp_host TEXT NOT NULL,
            smtp_port INTEGER NOT NULL DEFAULT 587,
            smtp_username TEXT NOT NULL,
            smtp_password TEXT NOT NULL,
            smtp_use_tls BOOLEAN NOT NULL DEFAULT TRUE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS voice_agents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            retell_agent_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS instagram_accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            unipile_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS telegram_accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            unipile_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # ── Campaigns ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            daily_lead_cap INTEGER NOT NULL DEFAULT 50,
            invite_daily_cap INTEGER NOT NULL DEFAULT 20,
            simulation_mode BOOLEAN NOT NULL DEFAULT FALSE,
            timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
            active_hours_start INTEGER NOT NULL DEFAULT 9,
            active_hours_end INTEGER NOT NULL DEFAULT 18,
            screening_prompt TEXT,
            sequence_mode TEXT NOT NULL DEFAULT 'sequential',
            active_days INTEGER[] DEFAULT '{1,2,3,4,5,6}',
            scheduled_start TIMESTAMPTZ,
            scheduled_pause TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_linkedin_accounts (
            campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
            account_id UUID REFERENCES linkedin_accounts(id) ON DELETE CASCADE,
            PRIMARY KEY (campaign_id, account_id)
        )
    """)

    # ── Sequences ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sequence_nodes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            node_type TEXT NOT NULL,
            position_x FLOAT NOT NULL DEFAULT 0,
            position_y FLOAT NOT NULL DEFAULT 0,
            data JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS sequence_edges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            source_node_id UUID NOT NULL REFERENCES sequence_nodes(id) ON DELETE CASCADE,
            target_node_id UUID NOT NULL REFERENCES sequence_nodes(id) ON DELETE CASCADE,
            source_handle TEXT DEFAULT 'default',
            target_handle TEXT DEFAULT 'default',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            node_id UUID REFERENCES sequence_nodes(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            channel TEXT NOT NULL,
            subject TEXT,
            body TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_node_campaign ON sequence_nodes(campaign_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_edge_campaign ON sequence_edges(campaign_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_edge_source ON sequence_edges(source_node_id)")

    # ── Job search ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS job_search_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            apify_actor_id TEXT NOT NULL DEFAULT 'curious_coder/linkedin-jobs-scraper',
            job_keywords TEXT[] NOT NULL,
            job_location TEXT,
            allowed_industries TEXT[] NOT NULL DEFAULT ARRAY['IT Services and IT Consulting','Software Development'],
            serper_roles TEXT[] NOT NULL DEFAULT ARRAY['CEO','Founder','CTO','CMO','VP Marketing','Head of Marketing','Director'],
            max_companies INTEGER NOT NULL DEFAULT 100,
            max_leads_per_company INTEGER NOT NULL DEFAULT 4,
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS job_search_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID REFERENCES campaigns(id),
            config_id UUID REFERENCES job_search_configs(id),
            status TEXT NOT NULL DEFAULT 'running',
            jobs_scraped INTEGER DEFAULT 0,
            companies_filtered INTEGER DEFAULT 0,
            leads_found INTEGER DEFAULT 0,
            leads_added INTEGER DEFAULT 0,
            error TEXT,
            started_at TIMESTAMPTZ DEFAULT NOW(),
            finished_at TIMESTAMPTZ
        )
    """)

    # ── Leads ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            linkedin_url TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            first_name TEXT,
            last_name TEXT,
            headline TEXT,
            company TEXT,
            company_linkedin_url TEXT,
            job_url TEXT,
            location TEXT,
            instagram_username TEXT,
            telegram_username TEXT,
            source TEXT NOT NULL DEFAULT 'job_search',
            status TEXT NOT NULL DEFAULT 'active',
            stop_reason TEXT,
            linkedin_account_id UUID REFERENCES linkedin_accounts(id),
            instagram_account_id UUID REFERENCES instagram_accounts(id),
            telegram_account_id UUID REFERENCES telegram_accounts(id),
            chat_id TEXT,
            ig_chat_id TEXT,
            tg_chat_id TEXT,
            current_node_id UUID REFERENCES sequence_nodes(id) ON DELETE SET NULL,
            linkedin_distance TEXT,
            tags TEXT[] DEFAULT ARRAY[]::TEXT[],
            path_history JSONB DEFAULT '[]',
            profile_viewed_at TIMESTAMPTZ,
            inmail_sent_at TIMESTAMPTZ,
            invited_at TIMESTAMPTZ,
            accepted_at TIMESTAMPTZ,
            email_opened_at TIMESTAMPTZ,
            link_clicked_at TIMESTAMPTZ,
            replied_at TIMESTAMPTZ,
            stopped_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (campaign_id, linkedin_url)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_campaign_status ON leads(campaign_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_account ON leads(linkedin_account_id)")

    # ── Queue ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id),
            lead_id UUID NOT NULL REFERENCES leads(id),
            node_id UUID REFERENCES sequence_nodes(id),
            channel TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            scheduled_at TIMESTAMPTZ NOT NULL,
            locked_at TIMESTAMPTZ,
            locked_by TEXT,
            sent_at TIMESTAMPTZ,
            failure_reason TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            payload JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_queue_pickup ON queue(status, scheduled_at) WHERE status = 'queued'")
    op.execute("CREATE INDEX IF NOT EXISTS idx_queue_lead ON queue(lead_id)")

    # ── Events ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            lead_id UUID REFERENCES leads(id),
            campaign_id UUID REFERENCES campaigns(id),
            event_type TEXT NOT NULL,
            channel TEXT,
            meta JSONB NOT NULL DEFAULT '{}',
            occurred_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id, occurred_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_campaign ON events(campaign_id, occurred_at)")

    # ── Inbound messages ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS inbound_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            lead_id UUID REFERENCES leads(id),
            campaign_id UUID REFERENCES campaigns(id),
            channel TEXT NOT NULL,
            body TEXT,
            raw JSONB NOT NULL DEFAULT '{}',
            received_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_inbound_lead ON inbound_messages(lead_id)")

    # ── Lead gen (multi-source) ──
    op.execute("""
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
    op.execute("""
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

    # ── Notifications ──
    op.execute("""
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
    op.execute("CREATE INDEX IF NOT EXISTS idx_notif_user_unread ON notifications(user_id, is_read, created_at DESC)")

    # ── Activity log ──
    op.execute("""
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
    op.execute("CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(created_at DESC)")

    # ── Blacklists ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS blacklists (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entry_type TEXT NOT NULL,
            value TEXT NOT NULL,
            reason TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(entry_type, value)
        )
    """)

    # ── Template library ──
    op.execute("""
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

    # ── Email tracking ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS email_tracking (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            lead_id UUID REFERENCES leads(id),
            campaign_id UUID REFERENCES campaigns(id),
            event_type TEXT NOT NULL,
            meta JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # ── Integration keys ──
    op.execute("""
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
    op.execute("CREATE INDEX IF NOT EXISTS idx_intkeys_user ON integration_keys(user_id)")


def downgrade() -> None:
    tables = [
        "integration_keys", "email_tracking", "template_library", "blacklists",
        "activity_log", "notifications", "lead_gen_runs", "lead_gen_configs",
        "inbound_messages", "events", "queue", "leads", "job_search_runs",
        "job_search_configs", "templates", "sequence_edges", "sequence_nodes",
        "campaign_linkedin_accounts", "campaigns", "telegram_accounts",
        "instagram_accounts", "voice_agents", "email_accounts",
        "linkedin_accounts", "refresh_tokens", "users",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
