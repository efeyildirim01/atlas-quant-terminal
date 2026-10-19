"""Migrations apply cleanly, round-trip, match the ORM, and render valid PostgreSQL DDL offline."""

import io
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.core.db import Base

API_DIR = Path(__file__).resolve().parents[1]


def cfg(url: str, buf=None) -> Config:
    c = Config(str(API_DIR / "alembic.ini"), output_buffer=buf)
    c.set_main_option("sqlalchemy.url", url)
    return c


def test_upgrade_downgrade_roundtrip_and_no_drift(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    command.upgrade(cfg(url), "head")
    eng = create_engine(url)
    assert "market_prices" in inspect(eng).get_table_names()
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"render_as_batch": True}), Base.metadata)
    assert diff == [], diff
    command.downgrade(cfg(url), "base")
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}


def test_postgres_ddl_renders_offline():
    buf = io.StringIO()
    command.upgrade(cfg("postgresql+psycopg://atlas@localhost/atlas", buf), "head", sql=True)
    sql = buf.getvalue()
    assert sql.count("CREATE TABLE") == 20  # 19 tables + alembic_version
    assert "TIMESTAMP WITH TIME ZONE" in sql and "NUMERIC(24, 8)" in sql


def test_sqlite_folder_is_created_on_a_fresh_checkout(tmp_path):
    from app.core.db import Database

    url = f"sqlite:///{(tmp_path / 'not' / 'yet' / 'there.db').as_posix()}"
    with Database(url).engine.connect() as c:
        assert c.exec_driver_sql("select 1").scalar() == 1
    assert (tmp_path / "not" / "yet" / "there.db").exists()
