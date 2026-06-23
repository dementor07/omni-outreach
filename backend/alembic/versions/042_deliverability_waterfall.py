"""Verification waterfall attempts, provider health, and sender transport results."""

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE omni_email_verification_attempts (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            email_normalized TEXT NOT NULL,
            connection_id    UUID REFERENCES omni_connections(id) ON DELETE SET NULL,
            provider         TEXT NOT NULL,
            ordinal          INTEGER NOT NULL CHECK (ordinal > 0),
            status           TEXT CHECK (status IN
                                ('verified','valid_domain','risky','invalid','unknown')),
            reason           TEXT,
            latency_ms       INTEGER NOT NULL DEFAULT 0,
            succeeded        BOOLEAN NOT NULL,
            error_code       TEXT,
            details          JSONB NOT NULL DEFAULT '{}'::jsonb,
            checked_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_verification_attempts_email "
        "ON omni_email_verification_attempts(workspace_id, email_normalized, checked_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE omni_verification_provider_state (
            workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connection_id       UUID NOT NULL REFERENCES omni_connections(id) ON DELETE CASCADE,
            provider            TEXT NOT NULL,
            success_count       BIGINT NOT NULL DEFAULT 0,
            failure_count       BIGINT NOT NULL DEFAULT 0,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            last_status         TEXT,
            last_error_code     TEXT,
            last_latency_ms     INTEGER,
            last_checked_at     TIMESTAMPTZ,
            open_until          TIMESTAMPTZ,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, connection_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE omni_sender_delivery_results (
            workspace_id      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            result_key        TEXT NOT NULL,
            sending_account_id UUID NOT NULL REFERENCES omni_sending_accounts(id) ON DELETE CASCADE,
            command_id        TEXT NOT NULL,
            status            TEXT NOT NULL,
            error_code        TEXT,
            retriable         BOOLEAN NOT NULL DEFAULT FALSE,
            occurred_at       TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (workspace_id, result_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_sender_delivery_results_account "
        "ON omni_sender_delivery_results(workspace_id, sending_account_id, occurred_at DESC)"
    )

    for table in (
        "omni_email_verification_attempts",
        "omni_verification_provider_state",
        "omni_sender_delivery_results",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
            USING (workspace_id = app_current_workspace() OR app_is_system())
            WITH CHECK (workspace_id = app_current_workspace() OR app_is_system())
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_sender_delivery_results")
    op.execute("DROP TABLE IF EXISTS omni_verification_provider_state")
    op.execute("DROP TABLE IF EXISTS omni_email_verification_attempts")
