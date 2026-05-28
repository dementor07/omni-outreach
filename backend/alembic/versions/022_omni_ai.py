"""Omni v2 AI projections — lead scores + AI job runs.

Revision ID: 022
Revises: 021
Create Date: 2026-05-27

Adds the projection tables behind the AI/CRM features (lead scoring +
AI Studio). Both are maintained by the projector worker from ``omni.events``,
same as every other projection — AI results are just more events.

What this creates
-----------------

  - ``omni_lead_scores`` — latest ICP/fit score per lead. One row per lead
    (PK = lead_id). Fed by ``ai.score.completed`` events. Surfaces as the
    score badge + tier + reasons on Leads/Contacts rows (HubSpot "ICP Tier"
    / Einstein lead-score convention).
  - ``omni_ai_jobs`` — the AI Studio run log. One row per AI job (score /
    compose / enrich / classify), tracking status, input, output, model,
    and cost. Fed by ``ai.*.queued`` (insert) and ``ai.*.completed`` /
    ``ai.*.failed`` (update). This is the Breeze/Agentforce "agent runs"
    convention.

Redpanda stays the log of record; these are projections only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AI_OWNED_TABLES: list[str] = [
    "omni_lead_scores",
    "omni_ai_jobs",
]


def upgrade() -> None:
    # ── Lead scores (one per lead; latest score wins) ──────────────────────
    op.execute(
        """
        CREATE TABLE omni_lead_scores (
            lead_id         UUID PRIMARY KEY,
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            contact_id      UUID,
            score           INTEGER NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
            tier            TEXT NOT NULL DEFAULT 'cold'
                              CHECK (tier IN ('hot','warm','cold')),
            reasons         JSONB NOT NULL DEFAULT '[]'::jsonb,
            model           TEXT,
            correlation_id  UUID,
            scored_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_lead_scores_workspace ON omni_lead_scores(workspace_id, score DESC)")
    op.execute("CREATE INDEX idx_omni_lead_scores_contact ON omni_lead_scores(workspace_id, contact_id)")

    # ── AI jobs (the AI Studio run log) ────────────────────────────────────
    op.execute(
        """
        CREATE TABLE omni_ai_jobs (
            id              UUID PRIMARY KEY,
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            kind            TEXT NOT NULL
                              CHECK (kind IN ('score','compose','enrich','classify')),
            status          TEXT NOT NULL DEFAULT 'queued'
                              CHECK (status IN ('queued','running','done','failed')),
            entity_type     TEXT,
            entity_id       UUID,
            input           JSONB NOT NULL DEFAULT '{}'::jsonb,
            output          JSONB NOT NULL DEFAULT '{}'::jsonb,
            model           TEXT,
            cost_usd        NUMERIC(10,4),
            error           TEXT,
            correlation_id  UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at    TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_ai_jobs_workspace_created ON omni_ai_jobs(workspace_id, created_at DESC)")
    op.execute("CREATE INDEX idx_omni_ai_jobs_status ON omni_ai_jobs(workspace_id, status)")
    op.execute("CREATE INDEX idx_omni_ai_jobs_correlation ON omni_ai_jobs(correlation_id) WHERE correlation_id IS NOT NULL")

    # ── RLS on every workspace-owned AI table ──────────────────────────────
    for table in AI_OWNED_TABLES:
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
            CREATE POLICY {table}_tenant_isolation ON {table}
              USING (workspace_id = app_current_workspace() OR app_is_system())
              WITH CHECK (workspace_id = app_current_workspace() OR app_is_system());
            """
        )


def downgrade() -> None:
    for table in reversed(AI_OWNED_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
