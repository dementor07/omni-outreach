"""N8N-001 — public API keys + outbound webhook subscriptions.

Three tables backing the bidirectional n8n integration's public surface:

  * ``omni_api_keys`` — sha256-hash-only API keys (Direction A/B auth). The raw
    key is shown once at creation and NEVER stored; lookup hashes the presented
    key and matches ``key_hash``. Lookup runs under system_scope() (it resolves
    WHICH workspace a request belongs to), so RLS must be app_is_system()-aware.
  * ``omni_webhook_subscriptions`` — per-workspace outbound webhook URLs the
    fan-out worker delivers domain events to (Direction A: omni -> n8n).
  * ``omni_webhook_deliveries`` — forensic log of each delivery attempt.

All three ENABLE + FORCE RLS with the migration-047 system-aware policy form
(``workspace_id = app_current_workspace() OR app_is_system()``) — NOT the raw
``current_setting`` form (RLS-SYSTEM-001).
"""

from __future__ import annotations

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None

_SYSTEM_AWARE = "workspace_id = app_current_workspace() OR app_is_system()"


def _rls(table: str) -> None:
    """ENABLE + FORCE RLS with the system-aware isolation policy + app-role grant."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    policy = f"{table}_workspace_isolation"
    op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    op.execute(
        f"""
        CREATE POLICY {policy} ON {table}
            USING ({_SYSTEM_AWARE})
            WITH CHECK ({_SYSTEM_AWARE})
        """
    )
    op.execute(f"GRANT ALL PRIVILEGES ON {table} TO omni_app_role")


def upgrade() -> None:
    # ── omni_api_keys ─────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_api_keys (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name          TEXT NOT NULL DEFAULT '',
            key_prefix    TEXT NOT NULL,
            key_hash      TEXT NOT NULL,
            scopes        JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_by    UUID,
            last_used_at  TIMESTAMPTZ,
            revoked_at    TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Lookup is by hash (unique across all workspaces — the hash IS the secret).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_hash ON omni_api_keys(key_hash)"
    )
    # Prefix index for the display/lookup fast-path.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_api_keys_prefix ON omni_api_keys(key_prefix)"
    )
    _rls("omni_api_keys")

    # ── omni_webhook_subscriptions ────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_webhook_subscriptions (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            url               TEXT NOT NULL,
            event_types       JSONB NOT NULL DEFAULT '[]'::jsonb,
            secret            TEXT NOT NULL,
            active            BOOLEAN NOT NULL DEFAULT TRUE,
            created_by        UUID,
            last_delivery_at  TIMESTAMPTZ,
            last_status       INTEGER,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_webhook_subs_ws_active "
        "ON omni_webhook_subscriptions(workspace_id, active)"
    )
    _rls("omni_webhook_subscriptions")

    # ── omni_webhook_deliveries (forensic log) ────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS omni_webhook_deliveries (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            subscription_id  UUID REFERENCES omni_webhook_subscriptions(id) ON DELETE CASCADE,
            event_type       TEXT NOT NULL,
            status_code      INTEGER,
            attempts         INTEGER NOT NULL DEFAULT 1,
            payload_digest   TEXT,
            error            TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_sub "
        "ON omni_webhook_deliveries(subscription_id, created_at DESC)"
    )
    _rls("omni_webhook_deliveries")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS omni_webhook_deliveries")
    op.execute("DROP TABLE IF EXISTS omni_webhook_subscriptions")
    op.execute("DROP TABLE IF EXISTS omni_api_keys")
