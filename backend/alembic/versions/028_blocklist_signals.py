"""Editable company blocklist + company signal scoring.

Absorbs the screening-efficiency layer from omni_outreach_v3 (company_blocklist,
company_signals) into v2:

- omni_company_blocklist: workspace-editable name patterns (enterprise/gov) so
  operators add exclusions without a code deploy. Seeded with the same default
  enterprise list as the parallel implementation.
- omni_company_signals: per-company hiring signals (hiring_sdr, multiple_roles,
  high-growth, …) with scores; the signal gate skips people-discovery for
  low-signal companies, cutting discovery cost.

Workspace-scoped + RLS. Chains off 027.
"""

from __future__ import annotations

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None

_DEFAULT_BLOCKLIST = [
    "amazon", "google", "meta", "microsoft", "apple", "ibm", "oracle", "sap",
    "salesforce", "adobe", "cisco", "intel", "accenture", "deloitte", "mckinsey",
    "tcs", "tata consultancy", "infosys", "wipro", "hcl", "tech mahindra",
    "cognizant", "capgemini", "adani", "reliance", "hdfc", "icici", "axis bank",
    "sbi", "bajaj", "mahindra", "birla", "larsen", "swiggy", "zomato", "paytm",
    "razorpay", "byju", "flipkart", "meesho", "zepto", "ola", "uber", "airbnb",
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_company_blocklist (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            pattern      TEXT NOT NULL,
            reason       TEXT NOT NULL DEFAULT 'blocklisted',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, pattern)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_omni_company_blocklist_ws ON omni_company_blocklist(workspace_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_company_signals (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            company_id   UUID NOT NULL REFERENCES omni_companies(id) ON DELETE CASCADE,
            signal       TEXT NOT NULL,
            score        INT NOT NULL DEFAULT 0,
            source       TEXT NOT NULL DEFAULT 'job',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, company_id, signal)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_omni_company_signals_company ON omni_company_signals(workspace_id, company_id)")

    for table in ("omni_company_blocklist", "omni_company_signals"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
            USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
            WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
            """
        )

    # Seed the default enterprise blocklist for EVERY existing workspace so the
    # filter works out of the box (parity with the parallel impl's seed).
    values = ", ".join(f"('{p}')" for p in _DEFAULT_BLOCKLIST)
    op.execute(
        f"""
        INSERT INTO omni_company_blocklist (workspace_id, pattern, reason)
        SELECT w.id, p.pattern, 'Enterprise'
        FROM workspaces w
        CROSS JOIN (VALUES {values}) AS p(pattern)
        ON CONFLICT (workspace_id, pattern) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_company_signals CASCADE")
    op.execute("DROP TABLE IF EXISTS omni_company_blocklist CASCADE")
