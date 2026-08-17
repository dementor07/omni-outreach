CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Auth ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    token           TEXT PRIMARY KEY,
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    expires_at      TIMESTAMPTZ NOT NULL
);

-- ── Multi-tenancy (migration 019) ─────────────────────────────────────────────
-- CI seeds from this hand-maintained dump; these must mirror 019_workspaces.py
-- or the auth flow (get_current_workspace -> workspace_members) 500s in CI.
CREATE TABLE IF NOT EXISTS workspaces (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,
    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON workspaces(owner_user_id);

CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('owner','admin','member')) DEFAULT 'member',
    invited_at   TIMESTAMPTZ,
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members(user_id);

-- ── Sender accounts ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS linkedin_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unipile_id      TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    email           TEXT,
    daily_invite_cap INTEGER NOT NULL DEFAULT 20,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_name       TEXT NOT NULL,
    from_email      TEXT NOT NULL UNIQUE,
    smtp_host       TEXT NOT NULL,
    smtp_port       INTEGER NOT NULL DEFAULT 587,
    smtp_username   TEXT NOT NULL,
    smtp_password   TEXT NOT NULL,
    smtp_use_tls    BOOLEAN NOT NULL DEFAULT TRUE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retell_agent_id TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS instagram_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unipile_id      TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS telegram_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unipile_id      TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Campaigns ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campaigns (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'draft', -- draft|active|paused|archived
    daily_lead_cap          INTEGER NOT NULL DEFAULT 50,
    invite_daily_cap        INTEGER NOT NULL DEFAULT 20,
    simulation_mode         BOOLEAN NOT NULL DEFAULT FALSE,
    timezone                TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    active_hours_start      INTEGER NOT NULL DEFAULT 9,
    active_hours_end        INTEGER NOT NULL DEFAULT 18,
    screening_prompt        TEXT,
    sequence_mode           TEXT NOT NULL DEFAULT 'sequential', -- sequential|canvas
    active_days             INTEGER[] DEFAULT '{1,2,3,4,5,6}',
    scheduled_start         TIMESTAMPTZ,
    scheduled_pause         TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_linkedin_accounts (
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    account_id      UUID REFERENCES linkedin_accounts(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, account_id)
);

-- ── Sequences ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sequence_nodes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id         UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    node_type           TEXT NOT NULL, -- trigger_start|action_linkedin_invite|action_linkedin_dm|action_email|action_whatsapp|action_instagram|action_telegram|action_voice|condition_replied|delay
    position_x          FLOAT NOT NULL DEFAULT 0,
    position_y          FLOAT NOT NULL DEFAULT 0,
    data                JSONB NOT NULL DEFAULT '{}', -- stores delay_days, template_id, email_account_id, voice_agent_id
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sequence_edges (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id         UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    source_node_id      UUID NOT NULL REFERENCES sequence_nodes(id) ON DELETE CASCADE,
    target_node_id      UUID NOT NULL REFERENCES sequence_nodes(id) ON DELETE CASCADE,
    source_handle       TEXT DEFAULT 'default', -- true|false|default
    target_handle       TEXT DEFAULT 'default',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    node_id         UUID REFERENCES sequence_nodes(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    channel         TEXT NOT NULL,
    subject         TEXT,
    body            TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_node_campaign ON sequence_nodes(campaign_id);
CREATE INDEX IF NOT EXISTS idx_edge_campaign ON sequence_edges(campaign_id);
CREATE INDEX IF NOT EXISTS idx_edge_source ON sequence_edges(source_node_id);

-- ── Lead gen ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_search_configs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id             UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    apify_actor_id          TEXT NOT NULL DEFAULT 'curious_coder/linkedin-jobs-scraper',
    job_keywords            TEXT[] NOT NULL,
    job_location            TEXT,
    allowed_industries      TEXT[] NOT NULL DEFAULT ARRAY['IT Services and IT Consulting','Software Development'],
    serper_roles            TEXT[] NOT NULL DEFAULT ARRAY['CEO','Founder','CTO','CMO','VP Marketing','Head of Marketing','Director'],
    max_companies           INTEGER NOT NULL DEFAULT 100,
    max_leads_per_company   INTEGER NOT NULL DEFAULT 4,
    min_employees           INTEGER,
    max_employees           INTEGER,
    is_enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_search_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id         UUID REFERENCES campaigns(id),
    config_id           UUID REFERENCES job_search_configs(id),
    status              TEXT NOT NULL DEFAULT 'running', -- running|done|failed
    jobs_scraped        INTEGER DEFAULT 0,
    companies_filtered  INTEGER DEFAULT 0,
    leads_found         INTEGER DEFAULT 0,
    leads_added         INTEGER DEFAULT 0,
    error               TEXT,
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    finished_at         TIMESTAMPTZ
);

-- ── Leads ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS leads (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id             UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    linkedin_url            TEXT NOT NULL,
    email                   TEXT,
    phone                   TEXT,
    first_name              TEXT,
    last_name               TEXT,
    headline                TEXT,
    company                 TEXT,
    company_linkedin_url    TEXT,
    job_url                 TEXT,
    location                TEXT,
    instagram_username      TEXT,
    telegram_username       TEXT,
    source                  TEXT NOT NULL DEFAULT 'job_search', -- job_search|manual|csv
    status                  TEXT NOT NULL DEFAULT 'active',     -- active|stopped|bounced
    stop_reason             TEXT,
    linkedin_account_id     UUID REFERENCES linkedin_accounts(id),
    instagram_account_id    UUID REFERENCES instagram_accounts(id),
    telegram_account_id     UUID REFERENCES telegram_accounts(id),
    chat_id                 TEXT,
    ig_chat_id              TEXT,
    tg_chat_id              TEXT,
    current_node_id         UUID REFERENCES sequence_nodes(id) ON DELETE SET NULL,
    linkedin_distance       TEXT, -- FIRST_DEGREE|SECOND_DEGREE|THIRD_DEGREE
    tags                    TEXT[] DEFAULT ARRAY[]::TEXT[],
    path_history            JSONB DEFAULT '[]',
    profile_viewed_at       TIMESTAMPTZ,
    inmail_sent_at          TIMESTAMPTZ,
    invited_at              TIMESTAMPTZ,
    accepted_at             TIMESTAMPTZ,
    email_opened_at         TIMESTAMPTZ,
    link_clicked_at         TIMESTAMPTZ,
    replied_at              TIMESTAMPTZ,
    stopped_at              TIMESTAMPTZ,
    last_reply_text         TEXT,
    last_reply_category     TEXT,
    last_reply_confidence   REAL,
    last_reply_at           TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (campaign_id, linkedin_url)
);

CREATE INDEX IF NOT EXISTS idx_leads_campaign_status ON leads(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_leads_account ON leads(linkedin_account_id);

-- ── Queue ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id),
    lead_id         UUID NOT NULL REFERENCES leads(id),
    node_id         UUID REFERENCES sequence_nodes(id),
    channel         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued', -- queued|locked|sent|failed|skipped
    scheduled_at    TIMESTAMPTZ NOT NULL,
    locked_at       TIMESTAMPTZ,
    locked_by       TEXT,
    sent_at         TIMESTAMPTZ,
    failure_reason  TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    payload         JSONB NOT NULL DEFAULT '{}',
    dead_letter_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_queue_pickup ON queue(status, scheduled_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_queue_lead ON queue(lead_id);

-- ── Events ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id         UUID REFERENCES leads(id),
    campaign_id     UUID REFERENCES campaigns(id),
    event_type      TEXT NOT NULL, -- invited|accepted|dm_sent|email_sent|call_made|reply_received|stopped
    channel         TEXT,
    meta            JSONB NOT NULL DEFAULT '{}',
    occurred_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_campaign ON events(campaign_id, occurred_at);

-- ── Inbound messages ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS inbound_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id         UUID REFERENCES leads(id),
    campaign_id     UUID REFERENCES campaigns(id),
    channel         TEXT NOT NULL,
    body            TEXT,
    raw             JSONB NOT NULL DEFAULT '{}',
    received_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inbound_lead ON inbound_messages(lead_id);

-- ── Approvals (human_approval nodes) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS approvals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id         UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    node_id         UUID NOT NULL REFERENCES sequence_nodes(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    payload         JSONB DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'pending',
    resolution      TEXT,
    resolved_by     TEXT,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_approvals_status_campaign ON approvals(status, campaign_id, created_at);

-- ── Notification channels (hot_lead_alert + approval pings) ──────────────────
CREATE TABLE IF NOT EXISTS notification_channels (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_type    TEXT NOT NULL,
    name            TEXT NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Lead gen (multi-source provider model) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS lead_gen_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}',
    label           TEXT,
    is_enabled      BOOLEAN DEFAULT TRUE,
    cron_schedule   TEXT,
    last_run_at     TIMESTAMPTZ,
    credit_budget   INT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lead_gen_configs_cron
    ON lead_gen_configs(cron_schedule) WHERE cron_schedule IS NOT NULL;

CREATE TABLE IF NOT EXISTS lead_gen_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id         UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    config_id           UUID REFERENCES lead_gen_configs(id) ON DELETE SET NULL,
    source_type         TEXT NOT NULL,
    status              TEXT DEFAULT 'pending',
    leads_found         INT DEFAULT 0,
    leads_added         INT DEFAULT 0,
    credits_consumed    INT NOT NULL DEFAULT 0,
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    error               TEXT,
    triggered_by        TEXT DEFAULT 'manual',
    meta                JSONB DEFAULT '{}'
);

-- ── Notifications ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    link            TEXT,
    is_read         BOOLEAN DEFAULT FALSE,
    meta            JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_user_unread ON notifications(user_id, is_read, created_at DESC);

-- ── Activity log ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS activity_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID,
    campaign_id     UUID,
    lead_id         UUID,
    action          TEXT NOT NULL,
    detail          TEXT,
    meta            JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(created_at DESC);

-- ── Blacklists ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS blacklists (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_type      TEXT NOT NULL,
    value           TEXT NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(entry_type, value)
);

-- ── Template library ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS template_library (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    name            TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'email',
    category        TEXT NOT NULL DEFAULT 'general',
    subject         TEXT,
    body            TEXT NOT NULL,
    variables       TEXT[] DEFAULT '{}',
    is_public       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Email tracking ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_tracking (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id         UUID REFERENCES leads(id),
    campaign_id     UUID REFERENCES campaigns(id),
    event_type      TEXT NOT NULL,
    meta            JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Integration keys (per-user encrypted API keys) ───────────────────────────
CREATE TABLE IF NOT EXISTS integration_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,
    field_name      TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    is_verified     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, provider, field_name)
);

CREATE INDEX IF NOT EXISTS idx_intkeys_user ON integration_keys(user_id);

-- ── Additional performance indexes (migration 002) ────────────────────────────
CREATE INDEX IF NOT EXISTS idx_queue_status_sched_locked
    ON queue(status, scheduled_at, locked_at);
CREATE INDEX IF NOT EXISTS idx_leads_current_node
    ON leads(current_node_id) WHERE current_node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_email
    ON leads(email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_campaign_type
    ON events(campaign_id, event_type, occurred_at);
