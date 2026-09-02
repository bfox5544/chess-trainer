import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from tests.conftest import ROOT

pytestmark = pytest.mark.integration

SCHEMA = "migration_roundtrip"


def test_migrations_downgrade_cleanly(db_engine: Engine) -> None:
    """Every migration must be reversible. Runs in a scratch schema so the
    tables the other tests use are left alone."""
    with db_engine.begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    url = db_engine.url.render_as_string(hide_password=False)
    config = Config(str(ROOT / "alembic.ini"))
    # "%%": Alembic's config file format treats a single "%" as interpolation.
    config.set_main_option("sqlalchemy.url", f"{url}?options=-csearch_path%%3D{SCHEMA}")
    config.attributes["configure_logging"] = False
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "base")
    finally:
        with db_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
