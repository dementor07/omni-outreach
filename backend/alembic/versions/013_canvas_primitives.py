"""Canvas primitives: companies, lead timezone, iteration counter, agent runs,
reply-classifier confidence column, race tracking.

Revision ID: 013
Revises: 012
Create Date: 2026-05-18
"""

from collections.abc import Sequence

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
