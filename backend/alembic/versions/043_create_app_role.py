"""create app role

Revision ID: 043
Revises: 042
Create Date: 2026-06-25 00:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '043'
down_revision = '042'
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()

    # Check if role exists
    res = conn.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'omni_app_role'")).fetchone()

    if not res:
        # CREATE ROLE can't run inside a transaction in Postgres.
        # Commit the current Alembic transaction, create the role, then
        # let Alembic handle the rest.
        conn.execute(sa.text("COMMIT"))
        conn.execute(sa.text("CREATE ROLE omni_app_role WITH LOGIN PASSWORD 'omni_app_password'"))
        conn.execute(sa.text("BEGIN"))

    # Grant privileges (these work fine inside a transaction)
    op.execute("GRANT CONNECT ON DATABASE outreach TO omni_app_role")
    op.execute("GRANT USAGE ON SCHEMA public TO omni_app_role")
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO omni_app_role")
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO omni_app_role")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO omni_app_role")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO omni_app_role")


def downgrade() -> None:
    pass
