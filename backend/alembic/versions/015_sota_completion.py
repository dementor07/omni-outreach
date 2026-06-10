"""SOTA completion: credential_refs + processed_commands indexes + muscle cutover.

Revision ID: 015
Revises: 014
Create Date: 2026-05-19

Adds:
- credential_refs   — one-shot opaque tokens the muscle redeems via
                      GET /internal/credentials/{ref}. Bundles are stored
                      encrypted (Fernet via app.services.encryption). Each
                      row is single-use; the release endpoint deletes it.
- processed_commands indexes — per-channel cutover dashboards.
- leads.email_account_id, leads.voice_agent_id — denormalized hints so
  the sequencer doesn't need a JOIN to build payloads (already populated
  by the existing dispatcher for some channels; this just adds the columns).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS credential_refs (
            ref           TEXT PRIMARY KEY,
            channel       TEXT NOT NULL,
            bundle_encrypted TEXT NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at    TIMESTAMPTZ NOT NULL,
            redeemed_at   TIMESTAMPTZ,
            released_at   TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_credential_refs_expires ON credential_refs(expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_processed_commands_channel "
        "ON processed_commands(channel, processed_at DESC)"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_account_id UUID REFERENCES email_accounts(id)"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS voice_agent_id UUID REFERENCES voice_agents(id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS voice_agent_id")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS email_account_id")
    op.execute("DROP INDEX IF EXISTS idx_processed_commands_channel")
    op.execute("DROP INDEX IF EXISTS idx_credential_refs_expires")
    op.execute("DROP TABLE IF EXISTS credential_refs")
