"""AGENT-HARNESS-002 — persist proposal provenance and executable review evidence.

The original harness table proved only that a returned ViewSpec compiled.  A
schema-valid query can still answer the wrong business question, so proposals
now retain their authoring origin and the RLS-scoped review produced by running
their candidate queries.  This is control-plane metadata only: it neither
publishes events nor changes workflow/campaign execution.
"""

from __future__ import annotations

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE omni_agent_jobs
            ADD COLUMN origin TEXT NOT NULL DEFAULT 'harness'
                CHECK (origin IN ('harness', 'connection', 'import')),
            ADD COLUMN review JSONB NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM omni_agent_jobs
                WHERE status IN ('queued', 'working', 'succeeded')
                  AND applied_at IS NULL
                GROUP BY workspace_id, kind, target_type, target_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'migration 057 found duplicate unapplied proposals; inspect and resolve them before retrying';
            END IF;
        END
        $$
        """
    )
    op.execute(
        "DROP INDEX IF EXISTS uq_agent_jobs_one_open_target"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_agent_jobs_one_unapplied_proposal "
        "ON omni_agent_jobs(workspace_id, kind, target_type, target_id) "
        "WHERE status IN ('queued', 'working', 'succeeded') AND applied_at IS NULL"
    )
    op.execute(
        """
        CREATE TABLE omni_agent_runners (
            workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            harness_id       TEXT NOT NULL
                             CHECK (
                                 harness_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$'
                             ),
            runner_id        UUID NOT NULL,
            active_job_id    UUID REFERENCES omni_agent_jobs(id) ON DELETE SET NULL,
            lease_expires_at TIMESTAMPTZ NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workspace_id, harness_id),
            UNIQUE (active_job_id)
        )
        """
    )
    op.execute("ALTER TABLE omni_agent_runners ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_agent_runners FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_agent_runners_workspace_isolation ON omni_agent_runners
            USING (workspace_id = app_current_workspace() OR app_is_system())
            WITH CHECK (workspace_id = app_current_workspace() OR app_is_system())
        """
    )
    op.execute("GRANT ALL PRIVILEGES ON omni_agent_runners TO omni_app_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_agent_runners")
    op.execute("DROP INDEX IF EXISTS uq_agent_jobs_one_unapplied_proposal")
    op.execute(
        "CREATE UNIQUE INDEX uq_agent_jobs_one_open_target "
        "ON omni_agent_jobs(workspace_id, kind, target_type, target_id) "
        "WHERE status IN ('queued', 'working')"
    )
    op.execute(
        "ALTER TABLE omni_agent_jobs DROP COLUMN IF EXISTS review, "
        "DROP COLUMN IF EXISTS origin"
    )
