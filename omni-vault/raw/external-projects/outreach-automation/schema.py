from collections import defaultdict

from db import execute, fetch_all


REQUIRED_TABLE_COLUMNS = {
    "status_types": {
        "status_type_id",
        "code",
    },
    "campaigns": {
        "campaign_id",
        "status_type_id",
        "created_at",
    },
    "linkedin_accounts": {
        "account_id",
        "account_name",
        "provider_account_id",
        "timezone",
    },
    "campaign_linkedin_accounts": {
        "campaign_id",
        "account_id",
    },
    "linkedin_templates": {
        "template_id",
        "campaign_id",
        "template_key",
        "body",
        "active",
        "version_no",
        "updated_at",
    },
    "system_constants": {
        "updated_at",
        "run_interval_seconds",
        "core_run_interval_seconds",
        "manual_run_interval_seconds",
        "max_leads_per_account",
        "global_max_leads_per_account",
        "global_daily_invite_cap",
        "global_daily_message_cap",
        "account_daily_invite_cap",
        "account_daily_message_cap",
        "invite_delay_min_seconds",
        "invite_delay_max_seconds",
        "followup_jitter_min_seconds",
        "followup_jitter_max_seconds",
        "core_run_jitter_min_seconds",
        "core_run_jitter_max_seconds",
        "outbound_timezone_mode",
        "default_account_timezone",
        "send_window_start_hour",
        "send_window_end_hour",
        "send_window_days",
        "queue_retention_days",
        "campaign_discovery_interval_seconds",
        "global_active",
    },
    "campaign_constants": {
        "campaign_id",
        "campaign_max_leads_per_account",
        "campaign_max_leads_per_day",
        "invite_delay_min_seconds",
        "invite_delay_max_seconds",
        "first_followup_days",
        "second_followup_days",
        "third_followup_days",
        "followup_jitter_min_seconds",
        "followup_jitter_max_seconds",
        "followup_1_jitter_days",
        "followup_2_jitter_days",
        "followup_3_jitter_days",
        "first_message_jitter_minutes",
        "claude_enabled",
        "claude_model",
        "claude_max_tokens",
        "claude_temperature",
        "message_approval_required",
        "simulation_mode",
        "is_active",
        "inbound_response_enabled",
        "inbound_response_delay_min_minutes",
        "inbound_response_delay_max_minutes",
        "outbound_timezone_mode",
        "default_account_timezone",
        "send_window_start_hour",
        "send_window_end_hour",
        "send_window_days",
        "global_dedup",
    },
    "campaign_sheets": {
        "campaign_id",
        "leads_sheet_id",
        "leads_tab",
        "lead_full_stats_sheet_id",
        "lead_full_stats_tab",
        "manual_messages_sheet_id",
        "manual_messages_tab",
    },
    "leads": {
        "lead_id",
        "campaign_id",
        "linkedin_url",
        "product_name",
        "product_url",
        "created_at",
    },
    "lead_state": {
        "lead_id",
        "campaign_id",
        "assigned_linkedin_account_id",
        "account_name",
        "provider_id",
        "chat_id",
        "first_name",
        "invite_sent_at",
        "accepted_at",
        "first_message_sent_at",
        "followup_1_sent_at",
        "followup_2_sent_at",
        "followup_3_sent_at",
        "manual_message_sent_at",
        "last_inbound_message_at",
        "last_inbound_message",
        "conversation_active",
        "automation_stopped_at",
        "last_action",
        "last_action_at",
        "run_id",
        "assignment_status",
        "inbound_response_count",
        "last_response_sent_at",
        "last_processed_inbound_id",
    },
    "lead_full_stats": {
        "lead_id",
        "linkedin_url",
        "campaign_id",
        "account_id",
        "account_name",
        "provider_id",
        "chat_id",
        "first_name",
        "invite_sent_at",
        "accepted_at",
        "first_message_sent_at",
        "followup_1_sent_at",
        "followup_2_sent_at",
        "followup_3_sent_at",
        "manual_message",
        "manual_message_sent_at",
        "manual_message_status",
        "last_inbound_message_at",
        "conversation_active",
        "automation_stopped_at",
        "last_action",
        "last_action_at",
        "run_id",
        "product_name",
        "product_url",
        "assignment_status",
        "inbound_response_count",
        "last_response_sent_at",
        "last_processed_inbound_id",
        "last_processed_outbound_id",
    },
    "lead_timeline": {
        "id",
        "lead_id",
        "campaign_id",
        "event_type",
        "occurred_at",
        "meta_json",
    },
    "dispatcher_queue": {
        "queue_id",
        "campaign_id",
        "lead_id",
        "account_id",
        "provider_id",
        "chat_id",
        "task_type",
        "template_key",
        "message",
        "status",
        "scheduled_at",
        "locked_by",
        "locked_at",
        "sent_at",
        "failure_reason",
        "created_at",
        "retry_count",
        "first_name",
        "linkedin_url",
        "account_name",
    },
    "runs": {
        "run_id",
        "campaign_id",
        "started_at",
        "finished_at",
        "duration_seconds",
        "status",
        "error",
    },
    "claude_usage_log": {
        "id",
        "service",
        "call_type",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "cost_usd",
        "campaign_id",
        "lead_id",
        "occurred_at",
    },
}


def _create_base_tables() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS status_types (
            status_type_id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            description TEXT
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            campaign_id TEXT PRIMARY KEY,
            status_type_id TEXT,
            name TEXT,
            description TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS linkedin_accounts (
            account_id TEXT PRIMARY KEY,
            account_name TEXT,
            provider_account_id TEXT,
            timezone TEXT,
            active_campaign_count INT DEFAULT 0
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_linkedin_accounts (
            campaign_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            PRIMARY KEY (campaign_id, account_id)
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS linkedin_templates (
            template_id TEXT PRIMARY KEY,
            campaign_id TEXT,
            template_key TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            active BOOLEAN DEFAULT TRUE,
            version_no INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS system_constants (
            id BIGSERIAL PRIMARY KEY,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            run_interval_seconds INTEGER,
            core_run_interval_seconds INTEGER,
            manual_run_interval_seconds INTEGER,
            max_leads_per_account INTEGER,
            global_max_leads_per_account INTEGER,
            global_daily_invite_cap INTEGER,
            global_daily_message_cap INTEGER,
            account_daily_invite_cap INTEGER,
            account_daily_message_cap INTEGER,
            invite_delay_min_seconds INTEGER,
            invite_delay_max_seconds INTEGER,
            followup_jitter_min_seconds INTEGER,
            followup_jitter_max_seconds INTEGER,
            core_run_jitter_min_seconds INTEGER,
            core_run_jitter_max_seconds INTEGER,
            outbound_timezone_mode TEXT,
            default_account_timezone TEXT,
            send_window_start_hour INTEGER,
            send_window_end_hour INTEGER,
            send_window_days TEXT,
            queue_retention_days INTEGER DEFAULT 30,
            campaign_discovery_interval_seconds INTEGER DEFAULT 900,
            global_active BOOLEAN DEFAULT TRUE
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_constants (
            campaign_id TEXT PRIMARY KEY,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            campaign_max_leads_per_account INTEGER,
            campaign_max_leads_per_day INTEGER,
            invite_delay_min_seconds INTEGER,
            invite_delay_max_seconds INTEGER,
            first_followup_days INTEGER,
            second_followup_days INTEGER,
            third_followup_days INTEGER,
            followup_jitter_min_seconds INTEGER,
            followup_jitter_max_seconds INTEGER,
            followup_1_jitter_days INTEGER DEFAULT 3,
            followup_2_jitter_days INTEGER DEFAULT 3,
            followup_3_jitter_days INTEGER DEFAULT 3,
            first_message_jitter_minutes INTEGER DEFAULT 15,
            claude_enabled BOOLEAN DEFAULT FALSE,
            claude_model TEXT DEFAULT 'claude-sonnet-4-6',
            claude_max_tokens INTEGER DEFAULT 5000,
            claude_temperature NUMERIC DEFAULT 0.6,
            message_approval_required BOOLEAN DEFAULT FALSE,
            simulation_mode BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            inbound_response_enabled BOOLEAN DEFAULT FALSE,
            inbound_response_delay_min_minutes INTEGER DEFAULT 30,
            inbound_response_delay_max_minutes INTEGER DEFAULT 180,
            outbound_timezone_mode TEXT,
            default_account_timezone TEXT,
            send_window_start_hour INTEGER,
            send_window_end_hour INTEGER,
            send_window_days TEXT,
            global_dedup BOOLEAN DEFAULT FALSE
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_sheets (
            campaign_id TEXT PRIMARY KEY,
            leads_sheet_id TEXT,
            leads_tab TEXT,
            lead_full_stats_sheet_id TEXT,
            lead_full_stats_tab TEXT,
            manual_messages_sheet_id TEXT,
            manual_messages_tab TEXT,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            lead_id TEXT PRIMARY KEY,
            campaign_id TEXT,
            linkedin_url TEXT UNIQUE,
            product_name TEXT,
            product_url TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS lead_state (
            lead_id TEXT PRIMARY KEY,
            campaign_id TEXT,
            assigned_linkedin_account_id TEXT,
            account_name TEXT,
            provider_id TEXT,
            chat_id TEXT,
            first_name TEXT,
            invite_sent_at TIMESTAMP,
            accepted_at TIMESTAMP,
            first_message_sent_at TIMESTAMP,
            followup_1_sent_at TIMESTAMP,
            followup_2_sent_at TIMESTAMP,
            followup_3_sent_at TIMESTAMP,
            manual_message_sent_at TIMESTAMP,
            last_inbound_message_at TIMESTAMP,
            last_inbound_message TEXT,
            conversation_active BOOLEAN DEFAULT FALSE,
            automation_stopped_at TIMESTAMP,
            last_action TEXT,
            last_action_at TIMESTAMP,
            run_id TEXT,
            assignment_status TEXT,
            inbound_response_count INTEGER DEFAULT 0,
            last_response_sent_at TIMESTAMP,
            last_processed_inbound_id TEXT
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS lead_full_stats (
            lead_id TEXT PRIMARY KEY,
            linkedin_url TEXT UNIQUE,
            account_id TEXT,
            account_name TEXT,
            provider_id TEXT,
            chat_id TEXT,
            first_name TEXT,
            invite_sent_at TIMESTAMP,
            accepted_at TIMESTAMP,
            first_message_sent_at TIMESTAMP,
            followup_1_sent_at TIMESTAMP,
            followup_2_sent_at TIMESTAMP,
            followup_3_sent_at TIMESTAMP,
            last_inbound_message_at TIMESTAMP,
            conversation_active BOOLEAN DEFAULT FALSE,
            automation_stopped_at TIMESTAMP,
            manual_message_sent_at TIMESTAMP,
            manual_message_status TEXT,
            last_action TEXT,
            last_action_at TIMESTAMP,
            run_id TEXT,
            campaign_id TEXT,
            manual_message TEXT,
            product_name TEXT,
            product_url TEXT,
            assignment_status TEXT,
            inbound_response_count INTEGER DEFAULT 0,
            last_response_sent_at TIMESTAMP,
            last_processed_inbound_id TEXT,
            last_processed_outbound_id TEXT
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS lead_timeline (
            id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL,
            campaign_id TEXT,
            event_type TEXT NOT NULL,
            occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
            meta_json TEXT
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS dispatcher_queue (
            queue_id TEXT PRIMARY KEY,
            campaign_id TEXT,
            lead_id TEXT,
            account_id TEXT,
            provider_id TEXT,
            chat_id TEXT,
            task_type TEXT,
            template_key TEXT,
            message TEXT,
            status TEXT DEFAULT 'queued',
            scheduled_at TIMESTAMP,
            locked_by TEXT,
            locked_at TIMESTAMP,
            sent_at TIMESTAMP,
            failure_reason TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            retry_count INT DEFAULT 0,
            first_name TEXT,
            linkedin_url TEXT,
            account_name TEXT
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            campaign_id TEXT,
            started_at TIMESTAMP NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMP,
            duration_seconds FLOAT,
            leads_ingested INT DEFAULT 0,
            invites_sent INT DEFAULT 0,
            first_messages_sent INT DEFAULT 0,
            followups_sent INT DEFAULT 0,
            status TEXT DEFAULT 'running',
            error TEXT
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS channel_types (
            channel_type_id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            description TEXT,
            enabled BOOLEAN DEFAULT TRUE
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS direction_types (
            direction_type_id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            description TEXT
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS step_types (
            step_type_id TEXT PRIMARY KEY,
            channel_type_id TEXT,
            code TEXT NOT NULL UNIQUE,
            display_order INTEGER,
            is_terminal BOOLEAN DEFAULT FALSE,
            default_delay_days INTEGER DEFAULT 0,
            description TEXT
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS message_types (
            message_type_id TEXT PRIMARY KEY,
            channel_type_id TEXT,
            code TEXT NOT NULL UNIQUE,
            description TEXT,
            active BOOLEAN DEFAULT TRUE
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS template_types (
            template_type_id TEXT PRIMARY KEY,
            channel_type_id TEXT,
            step_type_id TEXT,
            code TEXT NOT NULL UNIQUE,
            requires_subject BOOLEAN DEFAULT FALSE,
            requires_body BOOLEAN DEFAULT TRUE,
            description TEXT,
            active BOOLEAN DEFAULT TRUE
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS claude_usage_log (
            id BIGSERIAL PRIMARY KEY,
            service TEXT NOT NULL,
            call_type TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_write_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd NUMERIC(12, 8) NOT NULL DEFAULT 0,
            campaign_id TEXT,
            lead_id TEXT,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_claude_usage_occurred_at ON claude_usage_log (occurred_at DESC);
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage_log (
            id BIGSERIAL PRIMARY KEY,
            service TEXT NOT NULL,
            call_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'success',
            latency_ms INTEGER,
            campaign_id TEXT,
            lead_id TEXT,
            error_msg TEXT,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_api_usage_occurred_at ON api_usage_log (occurred_at DESC);
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS job_search_configs (
            campaign_id TEXT PRIMARY KEY REFERENCES campaigns(campaign_id),
            apify_actor_id TEXT NOT NULL DEFAULT 'worldunboxer~rapid-linkedin-scraper',
            job_keywords TEXT[] NOT NULL DEFAULT '{}',
            job_location TEXT,
            decision_maker_titles TEXT[] NOT NULL DEFAULT '{CEO,Founder,Co-Founder,CMO,VP Marketing,Head of Growth}',
            screening_prompt TEXT,
            max_results_per_run INTEGER NOT NULL DEFAULT 100,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS job_search_runs (
            id BIGSERIAL PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            companies_found INTEGER NOT NULL DEFAULT 0,
            candidates_found INTEGER NOT NULL DEFAULT 0,
            accepted INTEGER NOT NULL DEFAULT 0,
            rejected INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            error_msg TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ
        );
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_job_search_runs_campaign ON job_search_runs (campaign_id, started_at DESC);
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_step_rules (
            rule_id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            step_type_id TEXT NOT NULL,
            step_order INTEGER,
            enabled BOOLEAN DEFAULT TRUE,
            delay_days_from_previous INTEGER,
            linkedin_template_id TEXT,
            stop_automation_after BOOLEAN DEFAULT FALSE
        );
        """
    )


def _migrate_non_destructive() -> None:
    execute("CREATE INDEX IF NOT EXISTS idx_lead_full_stats_campaign ON lead_full_stats (campaign_id);")
    execute("CREATE INDEX IF NOT EXISTS idx_dispatcher_queue_status ON dispatcher_queue (status, scheduled_at);")
    execute("CREATE INDEX IF NOT EXISTS idx_dispatcher_queue_lead_task ON dispatcher_queue (lead_id, task_type);")
    execute("CREATE INDEX IF NOT EXISTS idx_dispatcher_queue_account ON dispatcher_queue (account_id);")


def _seed_lookup_tables() -> None:
    execute(
        """
        INSERT INTO status_types (status_type_id, code, description) VALUES
            ('ST_ACTIVE', 'active', 'Active campaign'),
            ('ST_PAUSED', 'paused', 'Paused campaign'),
            ('ST_DISABLED', 'disabled', 'Disabled campaign'),
            ('ST_ARCHIVED', 'archived', 'Archived campaign'),
            ('ST_STOPPED', 'stopped', 'Stopped campaign')
        ON CONFLICT (status_type_id) DO NOTHING;
        """
    )
    execute(
        """
        INSERT INTO channel_types (channel_type_id, code, description, enabled) VALUES
            ('CH_LINKEDIN', 'linkedin', 'LinkedIn outreach', TRUE),
            ('CH_EMAIL', 'email', 'Email outreach', TRUE)
        ON CONFLICT (channel_type_id) DO NOTHING;
        """
    )
    execute(
        """
        INSERT INTO direction_types (direction_type_id, code, description) VALUES
            ('DIR_OUTBOUND', 'outbound', 'Sent by us'),
            ('DIR_INBOUND', 'inbound', 'Received from lead')
        ON CONFLICT (direction_type_id) DO NOTHING;
        """
    )
    execute(
        """
        INSERT INTO step_types (step_type_id, channel_type_id, code, display_order, is_terminal, default_delay_days, description) VALUES
            ('ST_LI_INVITE', 'CH_LINKEDIN', 'linkedin_invite', 1, FALSE, 0, 'LinkedIn connection invite'),
            ('ST_LI_MSG1', 'CH_LINKEDIN', 'linkedin_first_message', 2, FALSE, 0, 'LinkedIn first message after acceptance'),
            ('ST_LI_FOLLOWUP1', 'CH_LINKEDIN', 'linkedin_followup_1', 3, FALSE, 3, 'LinkedIn follow-up 1'),
            ('ST_LI_FOLLOWUP2', 'CH_LINKEDIN', 'linkedin_followup_2', 4, FALSE, 6, 'LinkedIn follow-up 2'),
            ('ST_LI_FOLLOWUP3', 'CH_LINKEDIN', 'linkedin_followup_3', 5, TRUE, 9, 'LinkedIn follow-up 3'),
            ('ST_LI_MANUAL', 'CH_LINKEDIN', 'linkedin_manual', 6, FALSE, 0, 'LinkedIn manual message'),
            ('ST_EM_MSG1', 'CH_EMAIL', 'email_first_message', 1, FALSE, 0, 'Email first message'),
            ('ST_EM_FOLLOWUP1', 'CH_EMAIL', 'email_followup_1', 2, FALSE, 3, 'Email follow-up 1'),
            ('ST_EM_FOLLOWUP2', 'CH_EMAIL', 'email_followup_2', 3, TRUE, 6, 'Email follow-up 2')
        ON CONFLICT (step_type_id) DO NOTHING;
        """
    )
    execute(
        """
        INSERT INTO message_types (message_type_id, channel_type_id, code, description, active) VALUES
            ('MT_LI_INVITE', 'CH_LINKEDIN', 'invite', 'Connection invite', TRUE),
            ('MT_LI_MESSAGE', 'CH_LINKEDIN', 'message', 'LinkedIn message', TRUE),
            ('MT_EM_MESSAGE', 'CH_EMAIL', 'email', 'Email message', TRUE)
        ON CONFLICT (message_type_id) DO NOTHING;
        """
    )
    execute(
        """
        INSERT INTO template_types (template_type_id, channel_type_id, step_type_id, code, requires_subject, requires_body, description, active) VALUES
            ('TT_LI_MSG1', 'CH_LINKEDIN', 'ST_LI_MSG1', 'linkedin_first_message', FALSE, TRUE, 'LinkedIn first message template', TRUE),
            ('TT_LI_FOLLOWUP1', 'CH_LINKEDIN', 'ST_LI_FOLLOWUP1', 'linkedin_followup_1', FALSE, TRUE, 'LinkedIn followup 1 template', TRUE),
            ('TT_LI_FOLLOWUP2', 'CH_LINKEDIN', 'ST_LI_FOLLOWUP2', 'linkedin_followup_2', FALSE, TRUE, 'LinkedIn followup 2 template', TRUE),
            ('TT_LI_FOLLOWUP3', 'CH_LINKEDIN', 'ST_LI_FOLLOWUP3', 'linkedin_followup_3', FALSE, TRUE, 'LinkedIn followup 3 template', TRUE),
            ('TT_EM_MSG1', 'CH_EMAIL', 'ST_EM_MSG1', 'email_first_message', TRUE, TRUE, 'Email first message template', TRUE),
            ('TT_EM_FOLLOWUP1', 'CH_EMAIL', 'ST_EM_FOLLOWUP1', 'email_followup_1', TRUE, TRUE, 'Email followup 1 template', TRUE),
            ('TT_EM_FOLLOWUP2', 'CH_EMAIL', 'ST_EM_FOLLOWUP2', 'email_followup_2', TRUE, TRUE, 'Email followup 2 template', TRUE)
        ON CONFLICT (template_type_id) DO NOTHING;
        """
    )
    execute(
        """
        INSERT INTO campaign_step_rules (rule_id, campaign_id, step_type_id, step_order, enabled, delay_days_from_previous, linkedin_template_id, stop_automation_after)
        SELECT
            md5('CAMPAIGN_1:' || st.step_type_id),
            'CAMPAIGN_1',
            st.step_type_id,
            st.display_order,
            TRUE,
            st.default_delay_days,
            NULL,
            st.is_terminal
        FROM step_types st
        WHERE st.channel_type_id = 'CH_LINKEDIN'
          AND NOT EXISTS (
              SELECT 1
              FROM campaign_step_rules csr
              WHERE csr.campaign_id = 'CAMPAIGN_1'
                AND csr.step_type_id = st.step_type_id
          );
        """
    )
    execute(
        """
        CREATE OR REPLACE FUNCTION _sync_linkedin_account_campaign_count()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status = 'active' THEN
                    UPDATE linkedin_accounts
                    SET active_campaign_count = active_campaign_count + 1
                    WHERE account_id = NEW.account_id;
                END IF;
            ELSIF TG_OP = 'DELETE' THEN
                IF OLD.status = 'active' THEN
                    UPDATE linkedin_accounts
                    SET active_campaign_count = GREATEST(0, active_campaign_count - 1)
                    WHERE account_id = OLD.account_id;
                END IF;
            ELSIF TG_OP = 'UPDATE' THEN
                IF OLD.status != 'active' AND NEW.status = 'active' THEN
                    UPDATE linkedin_accounts
                    SET active_campaign_count = active_campaign_count + 1
                    WHERE account_id = NEW.account_id;
                ELSIF OLD.status = 'active' AND NEW.status != 'active' THEN
                    UPDATE linkedin_accounts
                    SET active_campaign_count = GREATEST(0, active_campaign_count - 1)
                    WHERE account_id = OLD.account_id;
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    execute("DROP TRIGGER IF EXISTS trg_linkedin_account_campaign_count ON campaign_linkedin_accounts;")
    execute(
        """
        CREATE TRIGGER trg_linkedin_account_campaign_count
        AFTER INSERT OR UPDATE OR DELETE ON campaign_linkedin_accounts
        FOR EACH ROW EXECUTE FUNCTION _sync_linkedin_account_campaign_count();
        """
    )
    execute(
        """
        UPDATE linkedin_accounts la
        SET active_campaign_count = (
            SELECT COUNT(*)
            FROM campaign_linkedin_accounts cla
            WHERE cla.account_id = la.account_id
              AND cla.status = 'active'
        );
        """
    )


def bootstrap_schema() -> None:
    """
    Create and migrate the database schema non-destructively.
    Safe to run multiple times.
    """
    _create_base_tables()
    _migrate_non_destructive()
    _seed_lookup_tables()
    verify_runtime_schema()


def verify_runtime_schema() -> None:
    """
    Verify that the runtime schema exists and is compatible.
    This function must be read-only and safe to call on every startup.
    """
    rows = fetch_all(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        """
    )

    table_columns = defaultdict(set)
    for row in rows:
        table_columns[row["table_name"]].add(row["column_name"])

    missing_tables = []
    missing_columns = []

    for table_name, required_columns in REQUIRED_TABLE_COLUMNS.items():
        existing_columns = table_columns.get(table_name)
        if not existing_columns:
            missing_tables.append(table_name)
            continue
        for column_name in sorted(required_columns - existing_columns):
            missing_columns.append(f"{table_name}.{column_name}")

    if missing_tables or missing_columns:
        parts = []
        if missing_tables:
            parts.append("missing tables: " + ", ".join(sorted(missing_tables)))
        if missing_columns:
            parts.append("missing columns: " + ", ".join(missing_columns))
        raise RuntimeError(
            "Runtime schema verification failed; "
            + "; ".join(parts)
            + ". Run `python bootstrap_db.py` before starting the service."
        )


def ensure_schema() -> None:
    """
    Backward-compatible runtime entrypoint.
    Runtime no longer mutates schema; it only verifies compatibility.
    """
    verify_runtime_schema()
