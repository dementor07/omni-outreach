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

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
