"""Production hardening — indexes, dead-letter column

Revision ID: 002
Revises: 001
Create Date: 2026-04-20

"""

from collections.abc import Sequence

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
