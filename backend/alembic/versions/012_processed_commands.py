"""Idempotency ledger for the Redpanda command bus.

Revision ID: 012
Revises: 011
Create Date: 2026-05-17
"""

from collections.abc import Sequence

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
