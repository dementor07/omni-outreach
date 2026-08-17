"""Contact-level suppression list (DNC) — re-checked at outbound send.

The legacy contact `blacklists` table (entry_type/value) was dropped in 025
with the rest of the pre-v2 schema and never rebuilt. This is its v2
replacement: workspace-scoped, RLS-isolated, and ENFORCED at the outbound
channel-send seam (transition_worker._fire_node) so a suppressed email / phone
/ linkedin / domain can never be messaged on ANY channel — the compliance
gate (unsubscribe, competitor, do-not-contact) v1 needs.

`kind` ∈ {email, domain, phone, linkedin}. Matching:
  - email     → exact (lowercased) match on contact.email
  - domain    → contact.email's domain endswith the pattern
  - phone     → digit-normalized exact match on contact.phone
  - linkedin  → contact.linkedin_url contains the pattern (handle-tolerant)

Chains off 030.
"""

from __future__ import annotations

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_suppression_list (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            kind          TEXT NOT NULL CHECK (kind IN ('email', 'domain', 'phone', 'linkedin')),
            value         TEXT NOT NULL,
            reason        TEXT,
            source        TEXT NOT NULL DEFAULT 'manual',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, kind, value)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_suppression_lookup "
        "ON omni_suppression_list(workspace_id, kind, value)"
    )
    op.execute("ALTER TABLE omni_suppression_list ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_suppression_list FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_suppression_list_workspace_isolation ON omni_suppression_list
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_suppression_list")
