"""Flink SQL analytics sink tables.

Revision ID: 016
Revises: 015
Create Date: 2026-05-20

The Flink SQL pipeline (backend-flink/analytics.sql) emits tumbling-window
rollups into these tables via the JDBC sink. The /analytics router reads
them directly. Upserts are keyed on the natural window keys.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS flink_metrics_daily (
            window_day    TEXT NOT NULL,
            status        TEXT NOT NULL,
            total_events  BIGINT NOT NULL,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (window_day, status)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS flink_metrics_channel_mix (
            window_hour   TEXT NOT NULL,
            channel       TEXT NOT NULL,
            status        TEXT NOT NULL,
            total_events  BIGINT NOT NULL,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (window_hour, channel, status)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_flink_metrics_daily_day "
        "ON flink_metrics_daily(window_day DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_flink_metrics_channel_mix_hour "
        "ON flink_metrics_channel_mix(window_hour DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_flink_metrics_channel_mix_hour")
    op.execute("DROP INDEX IF EXISTS idx_flink_metrics_daily_day")
    op.execute("DROP TABLE IF EXISTS flink_metrics_channel_mix")
    op.execute("DROP TABLE IF EXISTS flink_metrics_daily")
