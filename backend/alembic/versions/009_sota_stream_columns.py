"""SOTA streaming columns and tables

Revision ID: 009
Revises: 008
Create Date: 2026-05-17

Adds infrastructure the SOTA bridge code already writes to but no prior
migration created:

- ``stream_log`` table — written by ``EventBus._log_event`` for every
  command/transition. Acts as the legacy mirror of the Redpanda stream.
- ``leads.last_contacted_at`` — written by ``stream_sync`` when a Rust
  execution result reports ``status='sent'``. Used by UI to show the last
  touch on a lead independent of queue rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stream_log (
            id BIGSERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stream_log_occurred_at ON stream_log(occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stream_log_event_type ON stream_log(event_type, occurred_at DESC)"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_contacted_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS last_contacted_at")
    op.execute("DROP INDEX IF EXISTS idx_stream_log_event_type")
    op.execute("DROP INDEX IF EXISTS idx_stream_log_occurred_at")
    op.execute("DROP TABLE IF EXISTS stream_log")
