"""Lead social handles

Revision ID: 010
Revises: 009
Create Date: 2026-05-17

Adds the Instagram and Telegram username columns that ``lead_gen.upsert_lead``
already writes to. Without them, every CSV upload of a lead row fails with
``column "instagram_username" of relation "leads" does not exist``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_username TEXT")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS telegram_username TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS telegram_username")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS instagram_username")
