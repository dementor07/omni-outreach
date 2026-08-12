"""Flink SQL analytics sink tables.

Revision ID: 016
Revises: 015
Create Date: 2026-05-20

The Flink SQL pipeline (backend-flink/analytics.sql) emits tumbling-window
rollups into these tables via the JDBC sink. The /analytics router reads
them directly. Upserts are keyed on the natural window keys.
"""

from collections.abc import Sequence

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
