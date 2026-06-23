"""Durable email-verification results and send-time policy inputs.

The first deliverability slice records normalized verification outcomes with
provider/provenance, freshness, domain evidence, and an RLS boundary. The local
verifier can prove syntax + MX/domain risk; external waterfall providers can
later write the stronger ``verified`` outcome into the same contract.
"""

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE omni_email_verifications (
            workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            email_normalized TEXT NOT NULL,
            status           TEXT NOT NULL CHECK (status IN
                                ('verified','valid_domain','risky','invalid','unknown')),
            reason           TEXT NOT NULL,
            provider         TEXT NOT NULL,
            mx_domain        TEXT,
            mx_hosts         JSONB NOT NULL DEFAULT '[]'::jsonb,
            disposable       BOOLEAN NOT NULL DEFAULT FALSE,
            role_based       BOOLEAN NOT NULL DEFAULT FALSE,
            checked_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at       TIMESTAMPTZ NOT NULL,
            details          JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (workspace_id, email_normalized)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_email_verifications_status "
        "ON omni_email_verifications(workspace_id, status, expires_at)"
    )
    op.execute("ALTER TABLE omni_email_verifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_email_verifications FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_email_verifications_workspace_isolation
            ON omni_email_verifications
        USING (workspace_id = app_current_workspace() OR app_is_system())
        WITH CHECK (workspace_id = app_current_workspace() OR app_is_system())
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_email_verifications")
