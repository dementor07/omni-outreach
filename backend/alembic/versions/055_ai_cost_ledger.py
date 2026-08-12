"""AI-COST-001 — exact per-call AI cost ledger + per-campaign / workspace budgets.

A runaway objective loop screened ~9k people in a day (one Anthropic call each)
and silently drained the workspace's credit balance — no record of what was spent
where, and nothing to stop it. This makes AI spend EXACT and BOUNDED:

  - ``omni_ai_usage``          one row per Anthropic call (screen/compose/score/…)
                               carrying the REAL token counts from the API response
                               and the priced ``cost_usd``. This is the ledger the
                               cost panels read (spend per campaign / model / day).
  - ``omni_workflows`` budgets a per-campaign cap (``ai_budget_usd``), a guard mode
                               (``ai_budget_mode``: alert | warn_stop | hard_stop),
                               and a running total (``ai_spend_usd``) the dispatch
                               guard reads cheaply (a single-row read, not a SUM)
                               to block further paid calls the moment the cap is hit.
  - ``omni_ai_workspace_budget`` the workspace ceiling — a final backstop across
                               every campaign, same shape.

All additive. The ledger + workspace-budget tables get the standard system-aware
RLS policy (writes happen under system_scope in background workers, which bypass
RLS; the cost API reads under the request workspace). The omni_workflows columns
are nullable / default-0 → an instant metadata-only change, a no-op for every
existing campaign until an operator sets a budget.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── The exact-cost ledger: one row per Anthropic call ──────────────────────
    op.execute(
        """
        CREATE TABLE omni_ai_usage (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id          UUID NOT NULL,
            workflow_id           UUID,          -- campaign; NULL for ad-hoc Studio jobs
            lead_id               UUID,
            kind                  TEXT NOT NULL,  -- screen | compose | score | classify | reply
            model                 TEXT NOT NULL,
            input_tokens          INTEGER NOT NULL DEFAULT 0,
            output_tokens         INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
            cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd              NUMERIC(12,6) NOT NULL DEFAULT 0,
            occurred_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_omni_ai_usage_ws_time ON omni_ai_usage(workspace_id, occurred_at DESC)")
    op.execute(
        "CREATE INDEX idx_omni_ai_usage_wf_time ON omni_ai_usage(workflow_id, occurred_at DESC) "
        "WHERE workflow_id IS NOT NULL"
    )

    # ── Workspace ceiling (final backstop across all campaigns) ────────────────
    op.execute(
        """
        CREATE TABLE omni_ai_workspace_budget (
            workspace_id  UUID PRIMARY KEY,
            budget_usd    NUMERIC(12,4),   -- NULL = no ceiling
            mode          TEXT,            -- alert | warn_stop | hard_stop (NULL => warn_stop)
            spend_usd     NUMERIC(12,6) NOT NULL DEFAULT 0,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    for table in ("omni_ai_usage", "omni_ai_workspace_budget"):
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

    # ── Per-campaign budget + running total (the dispatch guard reads these) ────
    op.add_column("omni_workflows", sa.Column("ai_budget_usd", sa.Numeric(12, 4), nullable=True))
    op.add_column("omni_workflows", sa.Column("ai_budget_mode", sa.Text(), nullable=True))
    op.add_column(
        "omni_workflows",
        sa.Column("ai_spend_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("omni_workflows", "ai_spend_usd")
    op.drop_column("omni_workflows", "ai_budget_mode")
    op.drop_column("omni_workflows", "ai_budget_usd")
    op.execute("DROP TABLE IF EXISTS omni_ai_workspace_budget CASCADE")
    op.execute("DROP TABLE IF EXISTS omni_ai_usage CASCADE")
