"""Campaign audience — bind known recipients to a campaign for outbound-first runs.

OUTBOUND-FIRST-001. The whole engine assumed a campaign BEGINS by discovering
leads from a source: seed_and_run seeds one root lead with contact_id=NULL
("the source discovers entities that fan out"), and the validator forbids any
non-source root (ENTRY_NOT_SOURCE). That makes "reach out to a known list of
people" — a first-class outbound use case — impossible to express or run, which
contradicts the product promise (lead-gen OR outbound OR any mix).

This table is the missing abstraction: an explicit audience attached to a
campaign. When a campaign's entry node is an outbound/channel node (not a
source), the runner enrolls ONE lead per audience contact, WITH contact_id and
the recipient's identity — instead of one empty root lead. Sources keep their
existing discover-and-fan-out behavior; a campaign may use either or both.

  (workspace_id, workflow_id, contact_id)  — one row per (campaign, recipient)

Read by the runner under system_scope(), so the RLS policy MUST be the
app_is_system()-aware form (see RLS-SYSTEM-001 / migration 047) or every
enrollment read returns zero rows. FK contact_id -> omni_contacts ON DELETE
CASCADE so removing a contact cleanly drops it from every audience.
"""

from __future__ import annotations

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_campaign_audience (
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            workflow_id   UUID NOT NULL REFERENCES omni_workflows(id) ON DELETE CASCADE,
            contact_id    UUID NOT NULL REFERENCES omni_contacts(id) ON DELETE CASCADE,
            added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workflow_id, contact_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_audience_ws_wf "
        "ON omni_campaign_audience(workspace_id, workflow_id)"
    )
    op.execute("ALTER TABLE omni_campaign_audience ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_campaign_audience FORCE ROW LEVEL SECURITY")
    # The runner enrolls from this table under system_scope() — the policy must
    # permit the system scope via app_is_system(), exactly like the other
    # worker-read tables (RLS-SYSTEM-001). A raw current_setting() form would
    # make every enrollment read return zero rows.
    op.execute(
        """
        CREATE POLICY omni_campaign_audience_workspace_isolation ON omni_campaign_audience
            USING (workspace_id = app_current_workspace() OR app_is_system())
            WITH CHECK (workspace_id = app_current_workspace() OR app_is_system())
        """
    )
    op.execute("GRANT ALL PRIVILEGES ON omni_campaign_audience TO omni_app_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_campaign_audience")
