"""Allow legacy email_accounts.resend_api_key to be omitted.

Revision ID: 011
Revises: 010
Create Date: 2026-05-17
"""

from collections.abc import Sequence

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
