"""Portfolios, transactions and portfolio analytics.

Isolation: every query is scoped to the authenticated user. A portfolio belonging to someone else returns 404
(not 403), so its existence is not disclosed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.portfolio import LedgerError
from app.api.v1.common import RF_NOTE, envelope, settings_of
from app.auth.deps import audit, current_user, get_db
from app.models import Instrument, Portfolio, Transaction, User
from app.schemas.accounts import PortfolioIn, PortfolioOut, TransactionIn, TransactionOut
from app.services import portfolio_service as ps
from app.services.provenance import istanbul_today
from app.services.series_ops import resolve

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


def owned(db: Session, user: User, portfolio_id: str) -> Portfolio:
    p = db.scalar(select(Portfolio).where(Portfolio.portfolio_id == portfolio_id, Portfolio.user_id == user.user_id))
    if p is None:
        raise HTTPException(404, "Portfolio not found")
    return p


@router.get("", response_model=list[PortfolioOut])
def list_portfolios(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Portfolio).where(Portfolio.user_id == user.user_id).order_by(Portfolio.created_at)))


@router.post("", response_model=PortfolioOut, status_code=201)
def create_portfolio(body: PortfolioIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = Portfolio(user_id=user.user_id, name=body.name, base_currency=body.base_currency)
    db.add(p)
    db.flush()
    audit(db, request, "portfolio.create", user.user_id, p.portfolio_id)
    db.commit()
    return p


@router.get("/{portfolio_id}", response_model=PortfolioOut)
def get_portfolio(portfolio_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned(db, user, portfolio_id)


@router.delete("/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = owned(db, user, portfolio_id)
    db.delete(p)
    audit(db, request, "portfolio.delete", user.user_id, portfolio_id)
    db.commit()


# ── Transactions & analytics (Milestone 5) ────────────────────────────────────────────────────────
def _symbols(db: Session, rows: list[Transaction]) -> dict[int, str]:
    ids = {t.instrument_id for t in rows if t.instrument_id}
    return {i.instrument_id: i.symbol for i in db.scalars(select(Instrument).where(Instrument.instrument_id.in_(ids)))} if ids else {}


def _out(t: Transaction, symbols: dict[int, str]) -> TransactionOut:
    f = lambda x: float(x) if x is not None else None  # noqa: E731
    return TransactionOut(transaction_id=t.transaction_id, transaction_type=t.transaction_type, transaction_date=t.transaction_date,
                          symbol=symbols.get(t.instrument_id), quantity=f(t.quantity), price=f(t.price),
                          commission=float(t.commission or 0), amount=f(t.amount), settlement_date=t.settlement_date)


@router.get("/{portfolio_id}/transactions", response_model=list[TransactionOut])
def list_transactions(portfolio_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = owned(db, user, portfolio_id)
    rows = sorted(p.transactions, key=lambda t: (t.transaction_date, t.transaction_id))
    sym = _symbols(db, rows)
    return [_out(t, sym) for t in rows]


@router.post("/{portfolio_id}/transactions", response_model=TransactionOut, status_code=201)
def add_transaction(portfolio_id: str, body: TransactionIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    p = owned(db, user, portfolio_id)
    if body.transaction_date > istanbul_today():
        raise HTTPException(422, "transaction_date cannot be in the future")
    inst = None
    if body.symbol:
        inst = resolve(db, body.symbol.strip().upper(), ("equity", "fund"))
    t = Transaction(portfolio_id=p.portfolio_id, instrument_id=inst.instrument_id if inst else None,
                    transaction_type=body.transaction_type, quantity=body.quantity, price=body.price, commission=body.commission,
                    amount=body.amount, transaction_date=body.transaction_date, settlement_date=body.settlement_date)
    t.transaction_id = 2**62  # provisional id: sorts after existing same-day rows of the same type during validation
    try:
        ps.check_ledger(db, p, extra=[t])
    except LedgerError as exc:
        raise HTTPException(422, f"Rejected: {exc}") from exc
    t.transaction_id = None
    db.add(t)
    db.flush()
    audit(db, request, "portfolio.transaction.add", user.user_id, f"{p.portfolio_id}/{t.transaction_id}",
          {"type": t.transaction_type, "symbol": body.symbol})
    db.commit()
    return _out(t, {inst.instrument_id: inst.symbol} if inst else {})


@router.delete("/{portfolio_id}/transactions/{transaction_id}", status_code=204)
def delete_transaction(portfolio_id: str, transaction_id: int, request: Request, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    p = owned(db, user, portfolio_id)
    t = next((x for x in p.transactions if x.transaction_id == transaction_id), None)
    if t is None:
        raise HTTPException(404, "Transaction not found")
    try:
        ps.check_ledger(db, p, drop_id=transaction_id)
    except LedgerError as exc:
        raise HTTPException(422, f"Cannot delete: the remaining ledger would be invalid ({exc})") from exc
    db.delete(t)
    audit(db, request, "portfolio.transaction.delete", user.user_id, f"{p.portfolio_id}/{transaction_id}")
    db.commit()


@router.get("/{portfolio_id}/analytics")
def portfolio_analytics(portfolio_id: str, request: Request, benchmark: str | None = "D-IDX",
                        rf: float = Query(0.0, ge=-0.5, le=5.0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = owned(db, user, portfolio_id)
    bm = None
    if benchmark:
        bm = db.scalar(select(Instrument).where(Instrument.symbol == benchmark, Instrument.instrument_type.in_(("index", "equity", "fund"))))
        if bm is None:
            raise HTTPException(404, f"Unknown benchmark: {benchmark}")
    try:
        data, bundles = ps.analytics(db, p, bm, rf)
    except LedgerError as exc:
        raise HTTPException(422, f"Ledger invalid: {exc}") from exc
    return envelope(db, settings_of(request), data, bundles, units={"money": p.base_currency, "returns": "fraction"},
                    methodology={
                        "twr": "daily sub-periods r_t = (V_t − F_t)/V_{t−1} − 1, external flows at end of day, chained",
                        "mwr": "XIRR of deposits/withdrawals and ending value, Actual/365",
                        "cost_basis": "FIFO; commissions capitalised on buys, deducted from proceeds on sells",
                        "valuation": "last stored close/NAV on or before each day; marks older than 5 business days flagged",
                        "risk_decomposition": "last 252 common daily returns of current holdings; cash contributes zero",
                        "rf": RF_NOTE, "taxes": "not modelled",
                    })
