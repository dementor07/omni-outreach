"""B5 — shared message template library.

v2 message copy lives on channel + ai.compose nodes inside each campaign, but
there was no reusable, workspace-shared library. This adds one: named templates
with a channel, optional subject (email), a body that supports the same
``{{variable}}`` placeholders the channel payload renderer already understands,
and a category for organisation. Workspace-scoped + RLS, mirroring the other
omni_* tables (migration 020/031 pattern).

Chains off 032.
"""

from __future__ import annotations

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_templates (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name          TEXT NOT NULL,
            channel       TEXT NOT NULL DEFAULT 'email',
            category      TEXT,
            subject       TEXT,
            body          TEXT NOT NULL,
            created_by    UUID,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_omni_templates_workspace "
        "ON omni_templates(workspace_id, updated_at DESC)"
    )
    op.execute("ALTER TABLE omni_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_templates_workspace_isolation ON omni_templates
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_templates")
