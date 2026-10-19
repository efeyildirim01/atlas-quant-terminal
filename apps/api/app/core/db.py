"""SQLAlchemy 2 engine/session setup, portable between PostgreSQL (production) and SQLite (dev/tests)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData, Numeric, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC in Python. Stored as timestamptz on PostgreSQL, naive UTC on SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; pass an aware UTC datetime")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# Decimal-safe money/price type. 24 digits, 8 decimals covers TRY prices, NAVs and fund sizes.
Money = Numeric(24, 8, asdecimal=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_engine(url: str) -> Engine:
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores FKs unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.sessionmaker = sessionmaker(bind=self.engine, expire_on_commit=False, autoflush=False)

    def session(self) -> Iterator[Session]:
        with self.sessionmaker() as s:
            yield s
