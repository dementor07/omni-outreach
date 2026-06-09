"""Person↔company history + confidence decay — the knowledge-graph moat.

Phase 4 of the lead-intelligence plan (omni_outreach_v3 plan.md): "the graph is
not a cache, it is the product. Apollo's actual moat is historical relationships,
not scraping." A person discovered once is never re-discovered; when a known
person resurfaces at a company we already mapped, discovery is skipped entirely
(zero search/AI cost). The graph gets cheaper as it grows.

Two pieces on top of omni_people_cache (migration 027):

  - omni_person_company_history: tracks a person across companies over time
    (title at the time, started/ended). When a known person appears at a new
    company, no discovery is required — we already know them. ended_at NULL =
    current. This is the compounding relationship asset.

  - confidence decay: people_cache.confidence already exists (default 90). People
    change jobs; a CEO found in January may be elsewhere by June. Decay is
    computed at READ time from last_verified (−5/month, floor 10) so we never
    store a stale value, and a `decayed < 50` row signals "re-verify on next run".
    Add an index on (workspace_id, last_verified) so the re-verification sweep is
    cheap.

Workspace-scoped + RLS (migration 020 pattern). Chains off 029.
"""

from __future__ import annotations

from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── omni_person_company_history (the relationship graph over time) ───────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_person_company_history (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            person_id       UUID NOT NULL REFERENCES omni_people_cache(id) ON DELETE CASCADE,
            company_id      UUID NOT NULL REFERENCES omni_companies(id) ON DELETE CASCADE,
            title           TEXT,
            source          TEXT NOT NULL DEFAULT 'unknown',
            started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at        TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            -- One open (current) stint per person+company; re-discovering the
            -- same pairing updates the existing row instead of duplicating.
            UNIQUE (workspace_id, person_id, company_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_omni_pch_person ON omni_person_company_history(workspace_id, person_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_omni_pch_company ON omni_person_company_history(workspace_id, company_id)"
    )

    # ── confidence-decay support: cheap re-verification sweep ───────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_omni_people_cache_verified "
        "ON omni_people_cache(workspace_id, last_verified)"
    )

    # ── RLS ──────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE omni_person_company_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_person_company_history FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_person_company_history_workspace_isolation ON omni_person_company_history
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_person_company_history CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_omni_people_cache_verified")
