"""Lead-gen canvas primitives: pull-run debounce ledger, leads-imported event,
sub-graph fragments, linked templates.

Revision ID: 014
Revises: 013
Create Date: 2026-05-18
"""

from collections.abc import Sequence

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
