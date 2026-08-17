"""omni_tasks + omni_approvals projections (CONTRACT-004 / CONTRACT-005).

CONTRACT-004: crm.create_task emits ``task.created`` but had no projector branch
or table — the emitter was orphaned. Adds omni_tasks; _project_task writes here.

CONTRACT-005: flow.human_approval emits ``approval.requested`` and parks the
lead; the resolve endpoint emits ``approval.resolved``. Neither had a table or
projector. Adds omni_approvals; _project_approval tracks pending -> resolved.

RLS mirrors the other omni_* tables (migration 020 pattern): workspace-scoped
policy on ``app.workspace_id``.
"""

from __future__ import annotations

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_tasks (
            id                  UUID PRIMARY KEY,
            workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            contact_id          UUID,
            title               TEXT NOT NULL,
            due_date            DATE,
            assign_to_user_id   UUID,
            priority            TEXT NOT NULL DEFAULT 'normal',
            status              TEXT NOT NULL DEFAULT 'open',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_omni_tasks_workspace ON omni_tasks(workspace_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_omni_tasks_contact ON omni_tasks(workspace_id, contact_id)")

    # RLS: workspace-scoped, same shape as the other omni_* tables (migration 020).
    op.execute("ALTER TABLE omni_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_tasks FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_tasks_workspace_isolation ON omni_tasks
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )

    # ── omni_approvals (CONTRACT-005) ──────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_approvals (
            id              UUID PRIMARY KEY,
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            lead_id         UUID NOT NULL,
            node_id         UUID,
            prompt          TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | timeout
            resolved_handle TEXT,
            resolved_by     UUID,
            correlation_id  UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at     TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_omni_approvals_workspace_status ON omni_approvals(workspace_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_omni_approvals_lead ON omni_approvals(workspace_id, lead_id)")
    op.execute("ALTER TABLE omni_approvals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_approvals FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_approvals_workspace_isolation ON omni_approvals
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_approvals CASCADE")
    op.execute("DROP TABLE IF EXISTS omni_tasks CASCADE")
