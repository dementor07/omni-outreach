"""Scheduled lead gen — cron_schedule + last_run_at on lead_gen_configs

Revision ID: 003
Revises: 002
Create Date: 2026-04-21

"""

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
