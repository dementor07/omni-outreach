"""Send-outcome ledger — make every outbound send's result durable + queryable.

OBSERVABILITY-001. The send path was the one stage with NO durable per-result
record: `_emit_sender_delivery_result` fired only for channel.email and keyed to
the sending_account (transport health), so a LinkedIn invite/DM outcome — and
crucially its failure REASON (e.g. "403 subscription_required") — evaporated.
Enrichment already records per-lead `enrichment_history`; sends had no symmetric
trail. This table is the cross-lead queryable sibling (one row per send attempt),
maintained by the projector from a `send.outcome` event the worker emits for
EVERY outbound channel.

  channel  ∈ email|linkedin|sms|voice|whatsapp|instagram|telegram|slack|webhook_out
  mode     LinkedIn sub-action (invite|dm|inmail|profile_view) or NULL
  status   ∈ queued|sent|failed|skipped
  provider_ids  JSONB — {chat_id, invitation_id, message_id, provider_id} as available

Idempotent on (workspace_id, command_id, attempt) so a Kafka redelivery of the
result doesn't double-record. Workspace-scoped, RLS-isolated, FORCE'd. Chains 044.
"""

from __future__ import annotations

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_send_outcomes (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id         UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            lead_id              UUID,
            contact_id           UUID,
            workflow_id          UUID,
            node_id              UUID,
            channel              TEXT NOT NULL,
            mode                 TEXT,
            sending_account_id   UUID,
            command_id           TEXT NOT NULL,
            attempt              INTEGER NOT NULL DEFAULT 0,
            status               TEXT NOT NULL CHECK (status IN ('queued','sent','failed','skipped')),
            provider             TEXT,
            provider_status_code INTEGER,
            error_code           TEXT,
            error_detail         TEXT,
            provider_ids         JSONB NOT NULL DEFAULT '{}'::jsonb,
            retriable            BOOLEAN NOT NULL DEFAULT FALSE,
            occurred_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, command_id, attempt)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_send_outcomes_lead "
        "ON omni_send_outcomes(workspace_id, lead_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_send_outcomes_status "
        "ON omni_send_outcomes(workspace_id, status, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_send_outcomes_account "
        "ON omni_send_outcomes(workspace_id, sending_account_id, occurred_at DESC)"
    )
    op.execute("ALTER TABLE omni_send_outcomes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE omni_send_outcomes FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY omni_send_outcomes_workspace_isolation ON omni_send_outcomes
            USING (workspace_id = current_setting('app.workspace_id', true)::uuid)
            WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)
        """
    )
    # Explicit grant: the app connects as the non-owner omni_app_role. 043's
    # ALTER DEFAULT PRIVILEGES should cover owner-created tables, but grant
    # explicitly so a new table is never invisible to the app (RLS still applies).
    op.execute("GRANT ALL PRIVILEGES ON omni_send_outcomes TO omni_app_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_send_outcomes")
