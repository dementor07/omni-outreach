"""Campaign Objective — the goal a workflow pursues.

A "campaign" (omni_workflows) was just a graph + status + send-window; it had no
notion of WHAT it is for or whether it is winning. This table makes intent
first-class: a workflow gains one objective (metric + target + audience + bounds)
that the objective_controller measures against and pursues — re-running sourcing
(via the existing /run seed-and-fire) until the target is reached or the bounds
envelope (max_iterations / max_spend / deadline) is exhausted.

See ADR campaign-objective-controller. Slice 1 of 4 (Intent).

  metric  ∈ contacts | meetings_booked | replies | companies | qualified_leads
  status  ∈ pursuing | reached | exhausted | paused
  audience  jsonb — the spec that parameterises the source/screen node configs
  bounds    jsonb — {max_iterations, max_spend_usd?, deadline?}
  progress  jsonb — {current, iterations_used, spend_usd, last_action, blockers[]}

One objective per workflow (UNIQUE workspace_id, workflow_id). Workspace-scoped,
RLS-isolated. Chains off 035.
"""

from __future__ import annotations

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_campaign_objectives (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            workflow_id     UUID NOT NULL REFERENCES omni_workflows(id) ON DELETE CASCADE,
            metric          TEXT NOT NULL CHECK (metric IN
                              ('contacts','meetings_booked','replies','companies','qualified_leads')),
            target          INTEGER NOT NULL CHECK (target > 0),
            audience        JSONB NOT NULL DEFAULT '{}'::jsonb,
            bounds          JSONB NOT NULL DEFAULT '{}'::jsonb,
            progress        JSONB NOT NULL DEFAULT '{}'::jsonb,
            status          TEXT NOT NULL DEFAULT 'pursuing' CHECK (status IN
                              ('pursuing','reached','exhausted','paused')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, workflow_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_objectives_workflow "
        "ON omni_campaign_objectives(workspace_id, workflow_id)"
    )
    op.execute("ALTER TABLE omni_campaign_objectives ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_campaign_objectives FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_campaign_objectives_workspace_isolation ON omni_campaign_objectives
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_campaign_objectives")
