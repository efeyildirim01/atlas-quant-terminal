"""Portfolio analytics: DB rows → ledger replay → valuation, performance, risk. Formulas live in analytics/portfolio.py."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import metrics as m
from app.analytics import portfolio as pa
from app.models import Instrument, Portfolio, Transaction
from app.repositories.series import SeriesBundle, load_nav, load_prices
from app.services.series_ops import arr, dates, num


def to_txn(t: Transaction, symbols: dict[int, str]) -> pa.Txn:
    f = lambda x: float(x) if x is not None else None  # noqa: E731
    return pa.Txn(id=t.transaction_id, date=t.transaction_date, type=t.transaction_type,
                  symbol=symbols.get(t.instrument_id) if t.instrument_id else None,
                  quantity=f(t.quantity), price=f(t.price), commission=f(t.commission) or 0.0, amount=f(t.amount))


def load_series(db: Session, inst: Instrument) -> SeriesBundle:
    return load_nav(db, inst) if inst.instrument_type == "fund" else load_prices(db, inst)


def price_series(bundle: SeriesBundle) -> pd.Series:
    col = "nav" if bundle.dataset == "fund_nav" else "close"
    return bundle.frame[col] if col in bundle.frame else pd.Series(dtype=float)


def ledger_inputs(db: Session, portfolio: Portfolio, extra: list[Transaction] | None = None, drop_id: int | None = None):
    rows = [t for t in portfolio.transactions if t.transaction_id != drop_id] + (extra or [])
    inst_ids = {t.instrument_id for t in rows if t.instrument_id}
    insts = {i.instrument_id: i for i in db.scalars(select(Instrument).where(Instrument.instrument_id.in_(inst_ids)))} if inst_ids else {}
    symbols = {iid: i.symbol for iid, i in insts.items()}
    bundles = {i.symbol: load_series(db, i) for i in insts.values()}
    txns = [to_txn(t, symbols) for t in rows]
    return txns, bundles, insts


def valuation_end(txns: list[pa.Txn], bundles: dict[str, SeriesBundle]) -> date:
    """Latest date for which every held instrument has a stored mark, but never before the last transaction."""
    lasts = [b.as_of for b in bundles.values() if b.as_of]
    end = max(lasts) if lasts else max(t.date for t in txns)
    return max(end, max(t.date for t in txns))


def check_ledger(db: Session, portfolio: Portfolio, extra: list[Transaction] | None = None, drop_id: int | None = None) -> None:
    """Raises LedgerError if the ledger (with `extra` added / `drop_id` removed) violates an accounting rule."""
    txns, bundles, _ = ledger_inputs(db, portfolio, extra, drop_id)
    if not txns:
        return
    pa.replay(txns, {s: price_series(b) for s, b in bundles.items()}, valuation_end(txns, bundles))


def analytics(db: Session, portfolio: Portfolio, benchmark: Instrument | None, rf_annual: float) -> tuple[dict, list[SeriesBundle]]:
    txns, bundles, insts = ledger_inputs(db, portfolio)
    if not txns:
        return {"available": False, "reason": "No transactions yet. Start with a deposit."}, []
    prices = {s: price_series(b) for s, b in bundles.items()}
    end = valuation_end(txns, bundles)
    res = pa.replay(txns, prices, end)
    daily = res.daily
    idx = pa.twr_index(daily)
    value_end = float(daily["value"].iloc[-1])
    holdings = pa.holdings_table(res, prices, end)
    by_symbol = {i.symbol: i for i in insts.values()}
    for h in holdings:
        inst = by_symbol[h["symbol"]]
        h.update(name=inst.name, instrument_type=inst.instrument_type, sector=inst.sector or (inst.fund.category if inst.fund else None),
                 currency=inst.currency)

    net_contrib = res.totals["deposits"] - res.totals["withdrawals"]
    unrealized = sum(h["unrealized_pnl"] for h in holdings)
    span_years = (end - txns[0].date).days / 365.25 if txns else 0
    twr_total = float(idx.iloc[-1] - 1)
    mwr = pa.xirr(pa.investor_flows(txns, end, value_end))

    allocation: dict[str, dict[str, float]] = {"asset_class": {}, "sector": {}, "currency": {}}
    for h in holdings:
        for key, label in (("asset_class", h["instrument_type"]), ("sector", h["sector"] or "Other"), ("currency", h["currency"])):
            allocation[key][label] = allocation[key].get(label, 0.0) + (h["weight"] or 0.0)
    cash_w = res.cash / value_end if value_end > 0 else 0.0
    if cash_w > 0:
        allocation["asset_class"]["cash"] = cash_w
        allocation["sector"]["Cash"] = cash_w
        cur = portfolio.base_currency  # cash is held in the base currency
        allocation["currency"][cur] = allocation["currency"].get(cur, 0.0) + cash_w
    allocation = {k: [{"label": lab, "weight": w} for lab, w in sorted(v.items(), key=lambda kv: -kv[1])] for k, v in allocation.items()}

    level = idx * 100.0
    bundles_out = list(bundles.values())
    perf: dict = {"dates": dates(idx.index), "twr_index": arr(level, 4), "drawdown": arr(m.drawdown_series(level), 6),
                  "value": arr(daily["value"].loc[idx.index], 2),
                  "net_contributions": arr(daily["external_flow"].cumsum().loc[idx.index], 2)}
    bench_level = None
    if benchmark is not None:
        bb = load_series(db, benchmark)
        bundles_out.append(bb)
        bs = price_series(bb).loc[idx.index[0]: idx.index[-1]]
        a, b = m.align(level, bs)
        if len(b) > 1:
            bench_level = b
            perf["benchmark"] = {"symbol": benchmark.symbol, "dates": dates(b.index), "index": arr(b / b.iloc[0] * 100, 4),
                                 "return": num(b.iloc[-1] / b.iloc[0] - 1), "portfolio_return_same_dates": num(a.iloc[-1] / a.iloc[0] - 1)}
    weights = {h["symbol"]: h["weight"] for h in holdings if h["weight"]}
    data = {
        "available": True,
        "as_of": end.isoformat(), "inception": txns[0].date.isoformat() if txns else None, "base_currency": portfolio.base_currency,
        "summary": {
            "value": value_end, "cash": res.cash, "holdings_value": float(daily["holdings_value"].iloc[-1]),
            "net_contributions": net_contrib, "total_pnl": value_end - net_contrib,
            "realized_pnl": res.totals["realized_pnl"], "unrealized_pnl": unrealized,
            "dividends": res.totals["dividends"], "fees": res.totals["fees"], "commissions": res.totals["commissions"],
            "twr": twr_total,
            "twr_annualized": (1 + twr_total) ** (1 / span_years) - 1 if span_years >= 1 else None,
            "mwr_annualized": mwr,
            "period_years": span_years,
            "notes": [n for n in (
                None if span_years >= 1 else "Period under one year: annualised TWR is not shown; annualised MWR can be extreme.",
                "Taxes (withholding) are not modelled.",
            ) if n],
        },
        "holdings": holdings,
        "allocation": allocation,
        "performance": perf,
        "risk": {"metrics": m.risk_report(level, bench_level, rf_annual=rf_annual) if len(level) >= 2 else {},
                 "decomposition": pa.risk_decomposition(weights, prices)},
        "realized": res.realized,
        "warnings": res.warnings,
    }
    return data, bundles_out
