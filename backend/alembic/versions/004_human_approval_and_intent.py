"""Human approval, reply intent, and hot-lead alerts

Revision ID: 004
Revises: 003
Create Date: 2026-04-22

Adds:
- leads.last_reply_text / last_reply_category / last_reply_confidence — cache
  the most recent inbound reply so condition_reply_intent can branch on it.
- approvals table — tracks pending human review requests created by
  `human_approval` nodes; resolved via POST /approvals/{id}/resolve.
- notification_channels table — destinations (email, slack webhook) for
  `action_hot_lead_alert` and approval notifications.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cache latest inbound reply on the lead for intent-based branching.
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_reply_text TEXT")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_reply_category TEXT")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_reply_confidence REAL")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_reply_at TIMESTAMPTZ")

    # Approvals — one row per pending human_approval node visit.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id     UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            lead_id         UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            node_id         UUID NOT NULL REFERENCES sequence_nodes(id) ON DELETE CASCADE,
            title           TEXT NOT NULL,
            payload         JSONB DEFAULT '{}'::jsonb,
            status          TEXT NOT NULL DEFAULT 'pending',
            resolution      TEXT,
            resolved_by     TEXT,
            resolved_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_approvals_status_campaign "
        "ON approvals(status, campaign_id, created_at)"
    )

    # Notification channels — fan-out destinations for hot-lead alerts +
    # approval pings. Stored globally (not per-campaign) for v1.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_channels (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            channel_type    TEXT NOT NULL,
            name            TEXT NOT NULL,
            config          JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_channels")
    op.execute("DROP INDEX IF EXISTS idx_approvals_status_campaign")
    op.execute("DROP TABLE IF EXISTS approvals")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS last_reply_at")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS last_reply_confidence")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS last_reply_category")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS last_reply_text")
