"""DYNAMIC-001 — omni_views: user/AI-authored dashboard views as data.

The interface layer becomes data the same way campaigns already are: a view is
a row holding a name + a JSONB layout of widget instances (validated against
app/services/view_widgets.py before every write), rendered by one generic
frontend renderer. Creating/reshaping a screen is a data write — something the
view architect (POST /views/generate) or an external agent can do — instead of
a frontend deploy.

RLS uses the migration-047 system-aware policy form (RLS-SYSTEM-001).
"""

from __future__ import annotations

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None

_SYSTEM_AWARE = "workspace_id = app_current_workspace() OR app_is_system()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_views (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name          TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            icon          TEXT NOT NULL DEFAULT 'layout-dashboard',
            layout        JSONB NOT NULL DEFAULT '[]'::jsonb,
            prompt        TEXT,
            created_by    TEXT NOT NULL DEFAULT 'user'
                          CHECK (created_by IN ('user', 'ai', 'api')),
            position      INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_omni_views_ws_position "
        "ON omni_views(workspace_id, position, updated_at DESC)"
    )
    op.execute("ALTER TABLE omni_views ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_views FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS omni_views_workspace_isolation ON omni_views")
    op.execute(
        f"""
        CREATE POLICY omni_views_workspace_isolation ON omni_views
            USING ({_SYSTEM_AWARE})
            WITH CHECK ({_SYSTEM_AWARE})
        """
    )
    op.execute("GRANT ALL PRIVILEGES ON omni_views TO omni_app_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_views")
