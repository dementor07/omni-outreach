"""Allow legacy email_accounts.resend_api_key to be omitted.

Revision ID: 011
Revises: 010
Create Date: 2026-05-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'email_accounts'
                  AND column_name = 'resend_api_key'
            ) THEN
                UPDATE email_accounts
                SET resend_api_key = ''
                WHERE resend_api_key IS NULL;

                ALTER TABLE email_accounts
                    ALTER COLUMN resend_api_key SET DEFAULT '',
                    ALTER COLUMN resend_api_key DROP NOT NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    pass
