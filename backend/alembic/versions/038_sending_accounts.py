"""Sending accounts + per-campaign send controls — the rate-limit spine.

A "connection" (omni_connections) was one encrypted credential blob per
(provider, name); a channel node picked a sender by a free-text connection_name
string. There was no notion of an INDIVIDUAL sender (a mailbox, a LinkedIn seat,
a phone number) with its own send limits or health — and the rate_limited()
vocabulary in the Rust muscle was never enforced. A campaign could fire 500
LinkedIn invites in a minute and get the account banned.

This migration makes the sender first-class:

  omni_sending_accounts          — one row per individual sender, OWNED by a
                                    connection (one Unipile API key → many
                                    LinkedIn seats; one Twilio account → many
                                    numbers). Each carries daily/hourly caps,
                                    lazy-reset counters, status (active/paused/
                                    warming/banned), warmup ramp, and health.
  omni_campaign_sending_accounts — pool join table: which accounts a campaign
                                    may send from (LRU rotation). A join table,
                                    not a JSONB array, so deleting an account
                                    cascades it out of every campaign cleanly.

Plus per-campaign send controls on omni_workflows: a recurring business-hours
window (earliest/latest hour + days_of_week, evaluated in the workflow tz) and
a campaign-level daily cap with a lazy-reset counter. Caps enforce at BOTH the
account (safety floor, always applies) and the campaign (optional throttle) —
a send needs both to clear. Enforced in transition_worker._gate_send next to
the existing B6 schedule gate; incremented on CONFIRMED send (not dispatch).

Cap semantics: 0 = UNLIMITED (an unset cap must not silently block all sends).
LinkedIn-safe non-zero defaults are applied at account-creation time in the API,
not in the schema. Workspace-scoped + RLS-isolated like every projection table.

Chains off 037.
"""

from __future__ import annotations

from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── individual sending accounts under a connection ───────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_sending_accounts (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connection_id     UUID NOT NULL REFERENCES omni_connections(id) ON DELETE CASCADE,
            provider          TEXT NOT NULL,
            channel_kind      TEXT NOT NULL CHECK (channel_kind IN
                                ('email','linkedin','sms','voice','whatsapp','instagram','telegram')),
            external_identity TEXT NOT NULL,
            display_name      TEXT,
            daily_cap         INTEGER NOT NULL DEFAULT 0 CHECK (daily_cap >= 0),
            hourly_cap        INTEGER NOT NULL DEFAULT 0 CHECK (hourly_cap >= 0),
            sends_today       INTEGER NOT NULL DEFAULT 0,
            sends_this_hour   INTEGER NOT NULL DEFAULT 0,
            day_anchor        DATE,
            hour_anchor       TIMESTAMPTZ,
            status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN
                                ('active','paused','warming','banned')),
            warmup_target     INTEGER,
            last_used_at      TIMESTAMPTZ,
            health            JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, connection_id, external_identity)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sending_accounts_connection "
        "ON omni_sending_accounts(workspace_id, connection_id)"
    )
    # Selection-hot index: the LRU pick query filters channel_kind + status and
    # orders by last_used_at.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sending_accounts_pick "
        "ON omni_sending_accounts(workspace_id, channel_kind, status, last_used_at)"
    )
    op.execute("ALTER TABLE omni_sending_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_sending_accounts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_sending_accounts_workspace_isolation ON omni_sending_accounts
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )

    # ── campaign → sending-account pool (LRU rotation membership) ─────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_campaign_sending_accounts (
            workspace_id       UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            workflow_id        UUID NOT NULL REFERENCES omni_workflows(id) ON DELETE CASCADE,
            sending_account_id UUID NOT NULL REFERENCES omni_sending_accounts(id) ON DELETE CASCADE,
            weight             INTEGER NOT NULL DEFAULT 1 CHECK (weight > 0),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (workflow_id, sending_account_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_sending_accounts_account "
        "ON omni_campaign_sending_accounts(workspace_id, sending_account_id)"
    )
    op.execute("ALTER TABLE omni_campaign_sending_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_campaign_sending_accounts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_campaign_sending_accounts_workspace_isolation
            ON omni_campaign_sending_accounts
        USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )

    # ── per-campaign send controls (business hours + daily cap) ──────────────
    # days_of_week uses Monday=0 … Sunday=6 (the flow.wait_until convention).
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS daily_cap INTEGER")
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS earliest_hour SMALLINT")
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS latest_hour SMALLINT")
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS days_of_week JSONB")
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS sends_today INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE omni_workflows ADD COLUMN IF NOT EXISTS day_anchor DATE")


def downgrade() -> None:
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS day_anchor")
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS sends_today")
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS days_of_week")
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS latest_hour")
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS earliest_hour")
    op.execute("ALTER TABLE omni_workflows DROP COLUMN IF EXISTS daily_cap")
    op.execute("DROP TABLE IF EXISTS omni_campaign_sending_accounts")
    op.execute("DROP TABLE IF EXISTS omni_sending_accounts")
