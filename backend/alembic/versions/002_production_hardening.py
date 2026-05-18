"""Production hardening — indexes, dead-letter column

Revision ID: 002
Revises: 001
Create Date: 2026-04-20

"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Dead-letter reason column on queue
    op.execute("ALTER TABLE queue ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT")

    # Missing performance indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_queue_status_sched_locked ON queue(status, scheduled_at, locked_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_leads_current_node ON leads(current_node_id) WHERE current_node_id IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email) WHERE email IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_campaign_type ON events(campaign_id, event_type, occurred_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_events_campaign_type")
    op.execute("DROP INDEX IF EXISTS idx_leads_email")
    op.execute("DROP INDEX IF EXISTS idx_leads_current_node")
    op.execute("DROP INDEX IF EXISTS idx_queue_status_sched_locked")
    op.execute("ALTER TABLE queue DROP COLUMN IF EXISTS dead_letter_reason")
