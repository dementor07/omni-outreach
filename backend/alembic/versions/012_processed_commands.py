"""Idempotency ledger for the Redpanda command bus.

Revision ID: 012
Revises: 011
Create Date: 2026-05-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_commands (
            command_id UUID PRIMARY KEY,
            channel TEXT NOT NULL,
            task_id UUID,
            lead_id UUID,
            status TEXT NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_processed_commands_processed_at "
        "ON processed_commands(processed_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS processed_commands")
