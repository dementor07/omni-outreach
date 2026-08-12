"""drop missed legacy tables

Revision ID: 044
Revises: 043
Create Date: 2026-06-25 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = '044'
down_revision = '043'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute('DROP TABLE IF EXISTS "email_accounts" CASCADE')
    op.execute('DROP TABLE IF EXISTS "instagram_accounts" CASCADE')

def downgrade() -> None:
    pass
