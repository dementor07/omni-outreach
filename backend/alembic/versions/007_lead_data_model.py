"""Lead data model — extra_data JSONB, nullable linkedin_url, partial unique indexes

Revision ID: 007
Revises: 006
Create Date: 2026-05-04

Changes:
- leads.extra_data JSONB DEFAULT '{}' — stores source-specific enrichment fields
  (Apollo city/country/seniority, ProxyCurl connections, etc.) that don't warrant
  a dedicated column.
- leads.linkedin_url becomes nullable to support email-only contacts (Apollo
  frequently returns leads without a LinkedIn profile URL).
- Replaces the UNIQUE(campaign_id, linkedin_url) table constraint with two
  partial unique indexes:
    * unique on (campaign_id, linkedin_url) where linkedin_url is not null
    * unique on (campaign_id, email) where linkedin_url is null and email is not null
  This preserves dedupe correctness for both LinkedIn and email-only leads.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add extra_data column for source-specific enrichment metadata
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS extra_data JSONB DEFAULT '{}'")

    # Make linkedin_url nullable to support email-only leads
    op.execute("ALTER TABLE leads ALTER COLUMN linkedin_url DROP NOT NULL")

    # Drop the old unique constraint and replace with partial indexes
    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_campaign_id_linkedin_url_key")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_unique_linkedin
        ON leads(campaign_id, linkedin_url)
        WHERE linkedin_url IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_unique_email
        ON leads(campaign_id, email)
        WHERE linkedin_url IS NULL AND email IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_leads_unique_email")
    op.execute("DROP INDEX IF EXISTS idx_leads_unique_linkedin")
    op.execute("ALTER TABLE leads ALTER COLUMN linkedin_url SET NOT NULL")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS extra_data")
    # Note: downgrade does not restore the old UNIQUE constraint since rows
    # with NULL linkedin_url may exist by this point.
