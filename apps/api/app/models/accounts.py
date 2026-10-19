"""Users, sessions, portfolios, transactions, research reports, audit log."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, Money, UTCDateTime, utcnow
from app.models.market import BigId


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the opaque cookie token
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship(lazy="joined")


class Portfolio(Base):
    __tablename__ = "portfolios"

    portfolio_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    base_currency: Mapped[str] = mapped_column(String(3), default="TRY")
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)

    transactions: Mapped[list[Transaction]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_portfolio_date", "portfolio_id", "transaction_date"),)

    transaction_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id", ondelete="CASCADE"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.instrument_id"))  # NULL for cash flows
    transaction_type: Mapped[str] = mapped_column(String(12))
    quantity: Mapped[Decimal | None] = mapped_column(Money)
    price: Mapped[Decimal | None] = mapped_column(Money)
    commission: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    amount: Mapped[Decimal | None] = mapped_column(Money)  # cash amount for deposits/withdrawals/dividends/fees
    transaction_date: Mapped[dt.date] = mapped_column(Date)
    settlement_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")


class ResearchReport(Base):
    __tablename__ = "research_reports"

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.instrument_id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    report_type: Mapped[str] = mapped_column(String(40))
    generated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    data_snapshot_id: Mapped[str] = mapped_column(String(64))  # hash of inputs (sources + as-of + params)
    methodology_version: Mapped[str] = mapped_column(String(20))
    content: Mapped[dict] = mapped_column(JSON)
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified")


class AuditLog(Base):
    __tablename__ = "audit_log"

    audit_id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60))
    resource: Mapped[str | None] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[str] = mapped_column(Text, default="ok")


class SavedScreen(Base):
    __tablename__ = "saved_screens"

    screen_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    universe: Mapped[str] = mapped_column(String(20))  # equities | funds
    definition: Mapped[dict] = mapped_column(JSON)  # {filter, sort, columns}
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ResearchQuery(Base):
    """Every copilot answer with the exact evidence it was given and its verification outcome (audit + reproducibility)."""

    __tablename__ = "research_queries"

    query_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    verification: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(60))
    served_by: Mapped[str | None] = mapped_column(String(60))
    stop_reason: Mapped[str] = mapped_column(String(30))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
