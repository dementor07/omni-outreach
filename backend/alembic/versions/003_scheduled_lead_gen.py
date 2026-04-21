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
    op.execute(
        "ALTER TABLE lead_gen_configs ADD COLUMN IF NOT EXISTS cron_schedule TEXT"
    )
    op.execute(
        "ALTER TABLE lead_gen_configs ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lead_gen_configs_cron "
        "ON lead_gen_configs(cron_schedule) WHERE cron_schedule IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE lead_gen_runs ADD COLUMN IF NOT EXISTS triggered_by TEXT DEFAULT 'manual'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lead_gen_configs_cron")
    op.execute("ALTER TABLE lead_gen_configs DROP COLUMN IF EXISTS cron_schedule")
    op.execute("ALTER TABLE lead_gen_configs DROP COLUMN IF EXISTS last_run_at")
    op.execute("ALTER TABLE lead_gen_runs DROP COLUMN IF EXISTS triggered_by")
