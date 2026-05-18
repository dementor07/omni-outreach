"""Canvas primitives: companies, lead timezone, iteration counter, agent runs,
reply-classifier confidence column, race tracking.

Revision ID: 013
Revises: 012
Create Date: 2026-05-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Gap 5: companies table for cross-lead state (ABM / company-locking) ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            normalized_domain TEXT UNIQUE NOT NULL,
            display_name TEXT,
            last_contacted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES companies(id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_company_id ON leads(company_id)")

    # --- Gap 7: lead timezone for send-window enforcement ---
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS timezone TEXT")

    # --- Gap 8: iteration counter for graph loops ---
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS iteration_count INTEGER NOT NULL DEFAULT 0")

    # --- Gap 9: agent_runs for the hand-rolled Option C agent runtime ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            node_id UUID,
            goal TEXT NOT NULL,
            toolset JSONB NOT NULL DEFAULT '[]'::jsonb,
            max_turns INTEGER NOT NULL DEFAULT 10,
            max_tokens INTEGER NOT NULL DEFAULT 10000,
            status TEXT NOT NULL DEFAULT 'running',
            outcome TEXT,
            turns_used INTEGER NOT NULL DEFAULT 0,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            trace JSONB NOT NULL DEFAULT '[]'::jsonb,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_lead_id ON agent_runs(lead_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status)")

    # --- Gap 10: race tracking — record which sibling won so we can cancel others ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS race_winners (
            lead_id UUID NOT NULL,
            race_node_id UUID NOT NULL,
            winning_branch TEXT NOT NULL,
            decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (lead_id, race_node_id)
        )
        """
    )

    # --- Gap 3: reply classifier confidence (so we can prefer LLM verdicts over keywords) ---
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_reply_confidence REAL")


def downgrade() -> None:
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS last_reply_confidence")
    op.execute("DROP TABLE IF EXISTS race_winners")
    op.execute("DROP TABLE IF EXISTS agent_runs")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS iteration_count")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS timezone")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS company_id")
    op.execute("DROP TABLE IF EXISTS companies")
