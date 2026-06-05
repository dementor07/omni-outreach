"""Per-run pipeline metrics + cost tracking.

Absorbs the operational cost/usage layer from omni_outreach_v3 (pipeline_metrics):
per source-run counts (companies/people/leads), API call counts, token usage,
and estimated $ cost. Fed by ``pipeline.metric`` events the source pipeline emits;
surfaced read-only via /projections and the control-plane DB viz.

Workspace-scoped + RLS. Chains off 028.
"""

from __future__ import annotations

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_pipeline_metrics (
            run_id               UUID PRIMARY KEY,
            workspace_id         UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            collector_source     TEXT,
            correlation_id       UUID,
            started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at         TIMESTAMPTZ,
            companies_collected  INT NOT NULL DEFAULT 0,
            companies_qualified  INT NOT NULL DEFAULT 0,
            companies_rejected   INT NOT NULL DEFAULT 0,
            people_found         INT NOT NULL DEFAULT 0,
            people_verified      INT NOT NULL DEFAULT 0,
            leads_created        INT NOT NULL DEFAULT 0,
            serper_calls         INT NOT NULL DEFAULT 0,
            claude_calls         INT NOT NULL DEFAULT 0,
            claude_input_tokens  INT NOT NULL DEFAULT 0,
            claude_output_tokens INT NOT NULL DEFAULT 0,
            total_cost           NUMERIC(12, 6) NOT NULL DEFAULT 0,
            metadata             JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_omni_pipeline_metrics_ws_started "
        "ON omni_pipeline_metrics(workspace_id, started_at DESC)"
    )
    op.execute("ALTER TABLE omni_pipeline_metrics ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_pipeline_metrics FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_pipeline_metrics_workspace_isolation ON omni_pipeline_metrics
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_pipeline_metrics CASCADE")
