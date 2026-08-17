"""ATS company slugs — GLOBAL reference data harvested from CommonCrawl.

The ATS sources (source.greenhouse … source.rippling) discover hiring companies
by harvesting company "slugs" (e.g. ``andurilindustries`` on greenhouse,
``acme|wd1|careers`` on workday) from the CommonCrawl index, then hitting each
ATS's public job API per slug. Slug discovery is heavy (download ~100MB
cluster.idx + ~500MB CDXJ, binary-search a SURT prefix, ~90s/platform/crawl), so
it runs in a dedicated worker and persists here.

DELIBERATELY NOT workspace-scoped / NOT RLS-protected: a company's ATS slug is
public reference data (it's literally a public careers URL), identical for every
workspace. Harvesting it once and sharing it across all tenants is the whole
economic win — re-harvesting per workspace would be absurd. So these two tables
have no workspace_id and no row-level security, unlike every projection table.
Reads go through the internal API (the muscle) or the discovery worker, both
system-scoped.

  omni_ats_slugs   — (platform, slug) one row per discovered company
  omni_ats_crawls  — per (platform, crawl) discovery history (idempotent skip)

Chains off 036.
"""

from __future__ import annotations

from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_ats_slugs (
            platform          TEXT NOT NULL,
            slug              TEXT NOT NULL,
            first_seen_crawl  TEXT,
            seen_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (platform, slug)
        )
        """
    )
    # Fast "give me N slugs for platform X" reads (the muscle's slug fetch).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ats_slugs_platform ON omni_ats_slugs(platform)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_ats_crawls (
            platform          TEXT NOT NULL,
            crawl             TEXT NOT NULL,
            slugs_found       INTEGER NOT NULL DEFAULT 0,
            new_slugs         INTEGER NOT NULL DEFAULT 0,
            duration_seconds  DOUBLE PRECISION,
            ran_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (platform, crawl)
        )
        """
    )
    # NB: no ENABLE ROW LEVEL SECURITY — global reference data, see module docstring.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_ats_crawls")
    op.execute("DROP TABLE IF EXISTS omni_ats_slugs")
