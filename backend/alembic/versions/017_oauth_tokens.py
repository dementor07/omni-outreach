"""Generic oauth_tokens table for per-operator OAuth integrations.

Revision ID: 017
Revises: 016
Create Date: 2026-05-22

Single table keyed on (provider, user_id) so any provider's OAuth flow can
store/retrieve credentials uniformly. Tokens are Fernet-encrypted via
``app.services.encryption``.

Why a fresh table instead of extending google_oauth_tokens:
  - google_oauth_tokens predates the general OAuth refactor and uses
    google-specific column names (google_email, scopes). Keep it for Google
    backwards-compat; new providers (ProductHunt today, others later) land
    here. A follow-up migration can fold Google into this table once Sheets
    is migrated.

Fields:
  provider          — slug (e.g. "producthunt")
  user_id           — FK to users(id) so each operator has their own auth
  remote_user_id    — provider's user identifier (PH numeric id, GitHub login, …)
  remote_username   — human display name from the provider (for the connect UI)
  access_token_enc  — encrypted access_token
  refresh_token_enc — encrypted refresh_token (NULL when provider doesn't issue one)
  scope             — space-delimited scope string returned by the provider
  expires_at        — when the access_token stops working; refresher checks this
  connected_at      — when the user first authorized this provider
  last_refresh_at   — when we last successfully refreshed (NULL if never refreshed)
"""

from collections.abc import Sequence

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
