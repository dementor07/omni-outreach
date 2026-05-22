"""users.google_sub for Google sign-in linking.

Revision ID: 018
Revises: 017
Create Date: 2026-05-22

When a user signs in with Google, we want to look them up by Google's stable
``sub`` (subject ID) rather than email, because:
  - email is what the user typed during registration; Google's email may
    differ (different casing, alias addresses) and we don't want to lock
    them out of their own account.
  - emails can be changed; Google's sub is forever.

Falls back to email match when sub is NULL (first time a password-registered
user signs in with Google we backfill the sub).

Also relax users.password_hash to NULLABLE because Google-only users have
no password.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub TEXT")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub "
        "ON users(google_sub) WHERE google_sub IS NOT NULL"
    )
    # Allow NULL password_hash for Google-only users. If the column was
    # already NOT NULL we relax it; existing rows are untouched.
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS idx_users_google_sub")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS google_sub")
