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
    pass


def downgrade() -> None:
    pass
