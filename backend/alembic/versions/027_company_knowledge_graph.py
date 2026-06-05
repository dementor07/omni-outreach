"""Company knowledge graph: dedup + aliases + people cache.

Absorbs the lead-intelligence moat from the parallel org-repo implementation
(omni_outreach_v3: company_profiles / company_aliases / people_profiles) into our
multi-tenant v2 schema so the system gets cheaper as it runs — a repeat company
costs zero discovery.

- omni_companies gains screening_status, employee_count, people_discovered,
  source_count, lead_count, last_seen so the resolver can dedup + gate.
- omni_company_aliases: alternate names ("SourceMash" = "SourceMash Technologies"),
  auto-created on fuzzy suffix-strip match.
- omni_people_cache: people previously discovered per company (the KG cache).
  A company with cached people skips people-discovery entirely.

All workspace-scoped with RLS (migration 020 pattern). Chains off 026.
"""

from __future__ import annotations

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extend omni_companies with dedup / screening / KG counters ──────────
    op.execute("ALTER TABLE omni_companies ADD COLUMN IF NOT EXISTS screening_status TEXT NOT NULL DEFAULT 'pending'")
    op.execute("ALTER TABLE omni_companies ADD COLUMN IF NOT EXISTS employee_count INT")
    op.execute("ALTER TABLE omni_companies ADD COLUMN IF NOT EXISTS people_discovered BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE omni_companies ADD COLUMN IF NOT EXISTS source_count INT NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE omni_companies ADD COLUMN IF NOT EXISTS lead_count INT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE omni_companies ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()")
    # Case-insensitive unique company name per workspace — the dedup anchor.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_omni_companies_ws_lower_name "
        "ON omni_companies(workspace_id, LOWER(name))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_omni_companies_screening ON omni_companies(workspace_id, screening_status)")

    # ── omni_company_aliases ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_company_aliases (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            company_id      UUID NOT NULL REFERENCES omni_companies(id) ON DELETE CASCADE,
            alias           TEXT NOT NULL,
            source          TEXT NOT NULL DEFAULT 'manual',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, alias)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_omni_company_aliases_lookup "
        "ON omni_company_aliases(workspace_id, LOWER(alias))"
    )

    # ── omni_people_cache (the KG people store) ─────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_people_cache (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            company_id      UUID NOT NULL REFERENCES omni_companies(id) ON DELETE CASCADE,
            linkedin_url    TEXT,
            name            TEXT NOT NULL,
            title           TEXT,
            source          TEXT NOT NULL DEFAULT 'unknown',
            confidence      INT NOT NULL DEFAULT 90,
            discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_verified   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, linkedin_url)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_omni_people_cache_company ON omni_people_cache(workspace_id, company_id)")

    # ── RLS on the two new tables (omni_companies already has it from 020) ──
    for table in ("omni_company_aliases", "omni_people_cache"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
            USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
            WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_people_cache CASCADE")
    op.execute("DROP TABLE IF EXISTS omni_company_aliases CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_omni_companies_ws_lower_name")
    op.execute("DROP INDEX IF EXISTS idx_omni_companies_screening")
    for col in ("screening_status", "employee_count", "people_discovered", "source_count", "lead_count", "last_seen"):
        op.execute(f"ALTER TABLE omni_companies DROP COLUMN IF EXISTS {col}")
