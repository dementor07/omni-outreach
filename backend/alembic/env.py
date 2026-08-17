import os
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine

from alembic import context

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_url() -> str:
    """Build sync DSN from env vars (Alembic needs sync driver)."""
    db_password = os.environ.get("DB_PASSWORD", "")
    alembic_database_url = os.environ.get("ALEMBIC_DATABASE_URL", "")
    database_url = os.environ.get("DATABASE_URL", "")

    url_to_use = alembic_database_url or database_url
    if url_to_use:
        url = url_to_use.replace("postgresql+asyncpg://", "postgresql://")
        return url
    return f"postgresql://outreach:{db_password}@db/outreach"


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url())
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
