"""Phone-only leads — partial unique index for phone

Revision ID: 008
Revises: 007
Create Date: 2026-05-05

Changes:
- Adds a partial unique index on (campaign_id, phone) where linkedin_url IS NULL 
  and email IS NULL and phone IS NOT NULL.
  This enables leads with ONLY a name and phone number (e.g. trade show contacts)
  while preserving dedupe logic.
"""
from collections.abc import Sequence
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_unique_phone
        ON leads(campaign_id, phone)
        WHERE linkedin_url IS NULL AND email IS NULL AND phone IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_leads_unique_phone")
