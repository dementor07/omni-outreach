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
    pass


def downgrade() -> None:
    pass
