"""T3 — email open/click tracking events.

Outbound emails get an open pixel + click-redirect links injected at render
time (services.email_tracking). When a recipient opens the mail or clicks a
link, the public tracking endpoints log an ``email.opened`` / ``email.clicked``
event; the projector materialises this append-only table. Engagement rolls up
into Analytics.

Append-only (one row per hit), workspace-scoped + RLS, mirrors the omni_*
pattern. Chains off 033.
"""

from __future__ import annotations

from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_email_tracking (
            id            UUID PRIMARY KEY,
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            lead_id       UUID,
            contact_id    UUID,
            event_type    TEXT NOT NULL CHECK (event_type IN ('open', 'click')),
            url           TEXT,
            occurred_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_tracking_workspace "
        "ON omni_email_tracking(workspace_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_tracking_contact "
        "ON omni_email_tracking(contact_id) WHERE contact_id IS NOT NULL"
    )
    op.execute("ALTER TABLE omni_email_tracking ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_email_tracking FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_email_tracking_workspace_isolation ON omni_email_tracking
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_email_tracking")
