CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS workspace (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    timezone        TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS linkedin_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unipile_id      TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    email           TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    daily_invite_cap INTEGER DEFAULT 20,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_name       TEXT NOT NULL,
    from_email      TEXT NOT NULL UNIQUE,
    resend_api_key  TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retell_agent_id TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaigns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    status          TEXT DEFAULT 'draft',
    daily_lead_cap  INTEGER DEFAULT 50,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_linkedin_accounts (
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    account_id      UUID REFERENCES linkedin_accounts(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, account_id)
);

CREATE TABLE IF NOT EXISTS templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    channel         TEXT NOT NULL,
    subject         TEXT,
    body            TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sequence_steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    step_order      INTEGER NOT NULL,
    channel         TEXT NOT NULL,
    delay_days      INTEGER DEFAULT 0,
    template_id     UUID REFERENCES templates(id),
    voice_agent_id  UUID REFERENCES voice_agents(id),
    email_account_id UUID REFERENCES email_accounts(id),
    UNIQUE (campaign_id, step_order)
);

CREATE TABLE IF NOT EXISTS leads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    linkedin_url    TEXT,
    email           TEXT,
    phone           TEXT,
    first_name      TEXT,
    last_name       TEXT,
    headline        TEXT,
    company         TEXT,
    location        TEXT,
    status          TEXT DEFAULT 'active',
    source          TEXT,
    provider_id     TEXT,
    linkedin_account_id UUID REFERENCES linkedin_accounts(id),
    chat_id         TEXT,
    invited_at      TIMESTAMPTZ,
    accepted_at     TIMESTAMPTZ,
    current_step    INTEGER DEFAULT 0,
    stopped_at      TIMESTAMPTZ,
    stop_reason     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (campaign_id, linkedin_url)
);

CREATE TABLE IF NOT EXISTS queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID REFERENCES campaigns(id),
    lead_id         UUID REFERENCES leads(id),
    step_id         UUID REFERENCES sequence_steps(id),
    channel         TEXT NOT NULL,
    status          TEXT DEFAULT 'queued',
    scheduled_at    TIMESTAMPTZ NOT NULL,
    locked_at       TIMESTAMPTZ,
    locked_by       TEXT,
    sent_at         TIMESTAMPTZ,
    failure_reason  TEXT,
    retry_count     INTEGER DEFAULT 0,
    payload         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_queue_lead ON queue(lead_id);

CREATE TABLE IF NOT EXISTS events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id         UUID REFERENCES leads(id),
    campaign_id     UUID REFERENCES campaigns(id),
    event_type      TEXT NOT NULL,
    channel         TEXT,
    meta            JSONB DEFAULT '{}',
    occurred_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id, occurred_at);

CREATE TABLE IF NOT EXISTS inbound_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id         UUID REFERENCES leads(id),
    channel         TEXT NOT NULL,
    body            TEXT,
    received_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_credentials (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_search_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    apify_actor_id  TEXT DEFAULT 'worldunboxer~rapid-linkedin-scraper',
    keywords        TEXT[] NOT NULL,
    location        TEXT,
    titles          TEXT[],
    screening_prompt TEXT,
    max_results     INTEGER DEFAULT 50,
    is_enabled      BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_search_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID REFERENCES campaigns(id),
    status          TEXT DEFAULT 'running',
    companies_found INTEGER DEFAULT 0,
    candidates_found INTEGER DEFAULT 0,
    accepted        INTEGER DEFAULT 0,
    rejected        INTEGER DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

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
