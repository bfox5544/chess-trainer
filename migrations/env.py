"""Alembic environment.

The database URL comes from the application settings (DATABASE_URL) unless a
caller sets `sqlalchemy.url` explicitly, which the test suite does to point
migrations at the test database.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from chess_trainer.config import get_settings
from chess_trainer.db import models  # noqa: F401  (registers tables on Base.metadata)
from chess_trainer.db.base import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
