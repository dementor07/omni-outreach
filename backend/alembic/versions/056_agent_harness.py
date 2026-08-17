"""AGENT-HARNESS-001 — durable, lease-based jobs for external agent harnesses.

The browser can now hand a grounded authoring job to Codex, Claude Code,
OpenCode, or another workspace-owned harness without clipboard shuttling.
Postgres is the durable source of truth; Redis is only the ephemeral wake and
presence layer.  The table is deliberately generic (``kind`` + JSON payload /
result) so campaign authoring can adopt the same broker later without cloning
the queue.

This is control-plane metadata only.  It has no foreign key to workflow runs,
does not publish to the event bus, and cannot activate or send a campaign.
"""

from __future__ import annotations

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None

_SYSTEM_AWARE = "workspace_id = app_current_workspace() OR app_is_system()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE omni_agent_jobs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            kind                TEXT NOT NULL,
            target_type         TEXT NOT NULL,
            target_id           UUID NOT NULL,
            target_version      TIMESTAMPTZ,
            status              TEXT NOT NULL DEFAULT 'queued'
                                CHECK (status IN (
                                    'queued', 'working', 'succeeded', 'failed',
                                    'cancelled', 'expired'
                                )),
            payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
            result              JSONB,
            progress            JSONB NOT NULL DEFAULT '[]'::jsonb,
            error               TEXT,
            created_by          UUID,
            requested_harness_id TEXT,
            harness_id          TEXT,
            lease_hash          TEXT,
            lease_expires_at    TIMESTAMPTZ,
            attempts            INTEGER NOT NULL DEFAULT 0,
            claimed_at          TIMESTAMPTZ,
            last_heartbeat_at   TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,
            applied_at          TIMESTAMPTZ,
            expires_at          TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 minutes'),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_agent_jobs_ws_status_created "
        "ON omni_agent_jobs(workspace_id, status, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_agent_jobs_requested_harness "
        "ON omni_agent_jobs(workspace_id, requested_harness_id, status, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_agent_jobs_target "
        "ON omni_agent_jobs(workspace_id, target_type, target_id, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_agent_jobs_one_open_target "
        "ON omni_agent_jobs(workspace_id, kind, target_type, target_id) "
        "WHERE status IN ('queued', 'working')"
    )
    op.execute("ALTER TABLE omni_agent_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_agent_jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY omni_agent_jobs_workspace_isolation ON omni_agent_jobs
            USING ({_SYSTEM_AWARE})
            WITH CHECK ({_SYSTEM_AWARE})
        """
    )
    op.execute("GRANT ALL PRIVILEGES ON omni_agent_jobs TO omni_app_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_agent_jobs")
