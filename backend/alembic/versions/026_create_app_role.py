"""create app role

Revision ID: 026
Revises: 025
Create Date: 2026-06-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Use execute to run raw SQL
    conn = op.get_bind()
    
    # Check if role exists
    res = conn.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'omni_app_role'")).fetchone()
    
    if not res:
        # Create role. We can't do this inside a transaction block easily in some PG versions, 
        # but alembic allows it if we just execute it.
        # Actually, CREATE ROLE cannot be executed inside a transaction block, so we might need to set autocommit.
        conn.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa.text("CREATE ROLE omni_app_role WITH LOGIN PASSWORD 'omni_app_password'")
        )

    # Grant privileges
    op.execute("GRANT CONNECT ON DATABASE outreach TO omni_app_role")
    op.execute("GRANT USAGE ON SCHEMA public TO omni_app_role")
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO omni_app_role")
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO omni_app_role")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO omni_app_role")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO omni_app_role")


def downgrade() -> None:
    pass
