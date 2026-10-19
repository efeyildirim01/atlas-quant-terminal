"""Portfolio accounting: ledger replay, FIFO cost basis, daily valuation, TWR, MWR (XIRR), risk decomposition.

Pure functions (no I/O, no clock). Conventions, also in docs/financial-methodology/PORTFOLIO.md:
- Cash flows: deposit (+cash, external), withdrawal (−cash, external), dividend (+cash, income),
  fee (−cash, cost), buy (−qty·price − commission), sell (+qty·price − commission).
- Same-day order: deposits & dividends → sells → buys → withdrawals & fees, then the day is valued at close.
- Constraints: quantities never negative (no shorting), cash never negative (no margin). A violating
  transaction is rejected with its position in the ledger.
- Cost basis: FIFO lots. Commission is capitalised into the lot on buys and deducted from proceeds on sells.
- Valuation: last available close (NAV for funds) on or before each day. Marks older than STALE_BDAYS are flagged.
  Transaction prices are never used as marks and are never invented.
- TWR: r_t = (V_t − F_t) / V_{t−1} − 1, F_t = external flow on day t (flows at end of day). Chained geometrically.
  With nothing invested the day before, r_t = V_t / F_t − 1 (fresh capital measured from the amount deposited).
- MWR: XIRR of investor cash flows (deposits negative, withdrawals positive, ending value positive), Actual/365.
- Taxes (stopaj) are not modelled.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

CASH_IN = ("deposit", "dividend")
CASH_OUT = ("withdrawal", "fee")
TRADES = ("buy", "sell")
TYPES = (*CASH_IN, *TRADES, *CASH_OUT)
SAME_DAY_ORDER = {"deposit": 0, "dividend": 0, "sell": 1, "buy": 2, "withdrawal": 3, "fee": 3}
STALE_BDAYS = 5
PRICE_DEVIATION_WARN = 0.10  # trade price vs stored close on the trade date
EPS = 1e-9


class LedgerError(ValueError):
    def __init__(self, message: str, index: int | None = None):
        super().__init__(message)
        self.index = index


@dataclass(frozen=True)
class Txn:
    """One ledger entry. `id` gives a stable order within a day and lets errors point at the offending row."""

    id: int
    date: date
    type: str
    symbol: str | None = None
    quantity: float | None = None
    price: float | None = None
    commission: float = 0.0
    amount: float | None = None


@dataclass
class Lot:
    qty: float
    unit_cost: float  # includes capitalised commission
    opened: date


@dataclass
class LedgerResult:
    daily: pd.DataFrame  # index: day; columns: value, cash, holdings_value, external_flow, stale_marks, unpriced
    positions: dict[str, float]
    lots: dict[str, list[Lot]]
    realized: list[dict]
    cash: float
    totals: dict[str, float]
    holdings_by_day: pd.DataFrame  # qty per symbol per day
    warnings: list[str] = field(default_factory=list)


def validate_txn(t: Txn) -> None:
    if t.type not in TYPES:
        raise LedgerError(f"unknown transaction type '{t.type}'", t.id)
    if t.type in TRADES:
        if not t.symbol:
            raise LedgerError(f"{t.type} requires an instrument", t.id)
        if t.quantity is None or not t.quantity > 0:
            raise LedgerError(f"{t.type} requires quantity > 0", t.id)
        if t.price is None or not t.price > 0:
            raise LedgerError(f"{t.type} requires price > 0 (prices are never inferred)", t.id)
        if t.commission < 0:
            raise LedgerError("commission cannot be negative", t.id)
    else:
        if t.amount is None or not t.amount > 0:
            raise LedgerError(f"{t.type} requires amount > 0", t.id)


def _sorted(txns: list[Txn]) -> list[Txn]:
    return sorted(txns, key=lambda t: (t.date, SAME_DAY_ORDER.get(t.type, 9), t.id))


def replay(txns: list[Txn], prices: dict[str, pd.Series], end: date) -> LedgerResult:
    """Replay the ledger day by day from the first transaction to `end` and value it at each close."""
    if not txns:
        raise LedgerError("portfolio has no transactions")
    for t in txns:
        validate_txn(t)
    ordered = _sorted(txns)
    if ordered[0].type != "deposit":
        raise LedgerError("the first transaction must be a deposit (cash must exist before it is used)", ordered[0].id)
    start = ordered[0].date
    if end < ordered[-1].date:
        raise LedgerError(f"valuation date {end} is before the last transaction {ordered[-1].date}")

    days = pd.DatetimeIndex(sorted(set(pd.bdate_range(start, end)) | {pd.Timestamp(t.date) for t in ordered}))
    by_day: dict[pd.Timestamp, list[Txn]] = {}
    for t in ordered:
        by_day.setdefault(pd.Timestamp(t.date), []).append(t)

    lots: dict[str, deque[Lot]] = {}
    realized: list[dict] = []
    cash = 0.0
    totals = {"deposits": 0.0, "withdrawals": 0.0, "dividends": 0.0, "fees": 0.0, "commissions": 0.0, "realized_pnl": 0.0}
    clean_prices = {s: p.dropna().sort_index() for s, p in prices.items()}
    rows, holdings_rows = [], []
    warnings: list[str] = []
    for t in ordered:  # non-blocking plausibility check: a large gap is usually a typo or an unadjusted corporate action
        if t.type in TRADES and t.symbol in clean_prices:
            close = clean_prices[t.symbol].get(pd.Timestamp(t.date))
            if close and abs(t.price / close - 1) > PRICE_DEVIATION_WARN:
                warnings.append(f"{t.type} of {t.symbol} on {t.date} at {t.price:,.4g} is {abs(t.price / close - 1):.0%} away from the "
                                f"stored close {close:,.4g}; check for a typo")

    for day in days:
        flow = 0.0
        for t in by_day.get(day, []):
            if t.type == "deposit":
                cash += t.amount
                flow += t.amount
                totals["deposits"] += t.amount
            elif t.type == "withdrawal":
                if t.amount > cash + EPS:
                    raise LedgerError(f"withdrawal of {t.amount:,.2f} exceeds cash {cash:,.2f} on {t.date}", t.id)
                cash -= t.amount
                flow -= t.amount
                totals["withdrawals"] += t.amount
            elif t.type == "dividend":
                cash += t.amount
                totals["dividends"] += t.amount
            elif t.type == "fee":
                if t.amount > cash + EPS:
                    raise LedgerError(f"fee of {t.amount:,.2f} exceeds cash {cash:,.2f} on {t.date}", t.id)
                cash -= t.amount
                totals["fees"] += t.amount
            elif t.type == "buy":
                if t.symbol not in clean_prices:
                    raise LedgerError(f"no stored price history for {t.symbol}", t.id)
                cost = t.quantity * t.price + t.commission
                if cost > cash + EPS:
                    raise LedgerError(f"buy of {cost:,.2f} exceeds cash {cash:,.2f} on {t.date} (no margin)", t.id)
                cash -= cost
                totals["commissions"] += t.commission
                lots.setdefault(t.symbol, deque()).append(Lot(t.quantity, cost / t.quantity, t.date))
            elif t.type == "sell":
                held = sum(l.qty for l in lots.get(t.symbol, ()))
                if t.quantity > held + EPS:
                    raise LedgerError(f"sell of {t.quantity:g} {t.symbol} exceeds holding {held:g} on {t.date} (no shorting)", t.id)
                proceeds = t.quantity * t.price - t.commission
                remaining, cost_basis = t.quantity, 0.0
                q = lots[t.symbol]
                while remaining > EPS:
                    lot = q[0]
                    take = min(lot.qty, remaining)
                    cost_basis += take * lot.unit_cost
                    lot.qty -= take
                    remaining -= take
                    if lot.qty <= EPS:
                        q.popleft()
                cash += proceeds
                pnl = proceeds - cost_basis
                totals["commissions"] += t.commission
                totals["realized_pnl"] += pnl
                realized.append({"id": t.id, "date": t.date.isoformat(), "symbol": t.symbol, "quantity": t.quantity,
                                 "proceeds": proceeds, "cost_basis": cost_basis, "realized_pnl": pnl})

        holdings_value, stale, unpriced = 0.0, 0, 0
        qty_today: dict[str, float] = {}
        for sym, q in lots.items():
            qty = sum(l.qty for l in q)
            if qty <= EPS:
                continue
            qty_today[sym] = qty
            hist = clean_prices[sym].loc[:day]
            if hist.empty:
                unpriced += 1
                continue
            if np.busday_count(hist.index[-1].date(), day.date()) > STALE_BDAYS:
                stale += 1
            holdings_value += qty * float(hist.iloc[-1])
        value = cash + holdings_value if unpriced == 0 else math.nan
        rows.append({"day": day, "value": value, "cash": cash, "holdings_value": holdings_value, "external_flow": flow,
                     "stale_marks": stale, "unpriced": unpriced})
        holdings_rows.append({"day": day, **qty_today})

    daily = pd.DataFrame(rows).set_index("day")
    if (daily["unpriced"] > 0).any():
        warnings.append(f"{int((daily['unpriced'] > 0).sum())} day(s) have holdings without any price yet; those days are not valued")
    if (daily["stale_marks"] > 0).any():
        warnings.append(f"{int((daily['stale_marks'] > 0).sum())} day(s) use a mark older than {STALE_BDAYS} business days")
    holdings_by_day = pd.DataFrame(holdings_rows).set_index("day").fillna(0.0)
    positions = {s: sum(l.qty for l in q) for s, q in lots.items() if sum(l.qty for l in q) > EPS}
    return LedgerResult(daily, positions, {s: list(q) for s, q in lots.items() if s in positions}, realized, cash, totals,
                        holdings_by_day, warnings)


def twr_index(daily: pd.DataFrame) -> pd.Series:
    """Time-weighted return index after each day's close (1.0 = start of the first day).

    - Invested yesterday (V_{t-1} > 0): r_t = (V_t − F_t) / V_{t−1} − 1, external flows at end of day.
    - Nothing invested yesterday (start, or after a full withdrawal) and money arrives: r_t = V_t / F_t − 1, so fresh
      capital is measured from the amount deposited. A buy below the day's close is a real first-day gain and counts.
    - Unvalued days (missing marks) contribute 0 and are reported as warnings by `replay`.
    """
    v = daily["value"]
    f = daily["external_flow"]
    prev = v.shift(1)
    invested = prev.gt(EPS) & v.notna()
    fresh = ~prev.fillna(0.0).gt(EPS) & f.gt(EPS) & v.notna()
    r = pd.Series(0.0, index=v.index)
    r[invested] = ((v - f) / prev - 1.0)[invested]
    r[fresh] = (v / f - 1.0)[fresh]
    first = v.first_valid_index()
    return (1.0 + r.loc[first:]).cumprod()


def xirr(flows: list[tuple[date, float]], lo: float = -0.9999, hi: float = 100.0, tol: float = 1e-10) -> float | None:
    """Money-weighted return (annual) by bisection on NPV, Actual/365. None when no sign change exists in [lo, hi]."""
    if not flows or all(cf >= 0 for _, cf in flows) or all(cf <= 0 for _, cf in flows):
        return None
    d0 = min(d for d, _ in flows)

    def npv(rate: float) -> float:
        return sum(cf / (1.0 + rate) ** ((d - d0).days / 365.0) for d, cf in flows)

    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def investor_flows(txns: list[Txn], end: date, end_value: float) -> list[tuple[date, float]]:
    flows = [(t.date, -t.amount) for t in txns if t.type == "deposit"] + [(t.date, t.amount) for t in txns if t.type == "withdrawal"]
    return flows + [(end, end_value)]


def holdings_table(result: LedgerResult, prices: dict[str, pd.Series], end: date) -> list[dict]:
    total = float(result.daily["value"].iloc[-1])
    rows = []
    for sym, qty in sorted(result.positions.items()):
        hist = prices[sym].dropna().loc[: pd.Timestamp(end)]
        mark = float(hist.iloc[-1]) if len(hist) else math.nan
        cost = sum(l.qty * l.unit_cost for l in result.lots[sym])
        mv = qty * mark
        rows.append({
            "symbol": sym, "quantity": qty, "avg_cost": cost / qty, "cost_basis": cost, "price": mark,
            "price_date": hist.index[-1].date().isoformat() if len(hist) else None,
            "market_value": mv, "unrealized_pnl": mv - cost, "unrealized_pct": mv / cost - 1 if cost else None,
            "weight": mv / total if total > 0 else None,
        })
    return rows


def risk_decomposition(weights: dict[str, float], prices: dict[str, pd.Series], window: int = 252) -> dict:
    """Correlation matrix and contribution to variance over the last `window` common observations.

    RC_i = w_i (Σw)_i / (wᵀΣw). Contributions sum to 1. Cash has zero variance, so it contributes 0 and is omitted.
    """
    syms = [s for s, w in weights.items() if w and s in prices]
    if not syms:
        return {"available": False, "reason": "no priced holdings"}
    rets = pd.concat({s: prices[s].dropna().pct_change(fill_method=None) for s in syms}, axis=1, join="inner").dropna().iloc[-window:]
    if len(rets) < 20:
        return {"available": False, "reason": f"only {len(rets)} common return observations (need ≥ 20)"}
    cov = rets.cov().to_numpy() * 252
    w = np.array([weights[s] for s in syms])
    var = float(w @ cov @ w)
    corr = rets.corr().to_numpy()
    out = {"available": True, "symbols": syms, "n_obs": int(len(rets)), "start": rets.index[0].date().isoformat(),
           "end": rets.index[-1].date().isoformat(),
           "correlation": [[None if not np.isfinite(x) else float(x) for x in row] for row in corr],
           "portfolio_volatility_ex_ante": math.sqrt(var) if var > 0 else 0.0}
    out["risk_contribution"] = [
        {"symbol": s, "weight": float(w[i]), "contribution": float(w[i] * (cov @ w)[i] / var) if var > 0 else None}
        for i, s in enumerate(syms)
    ]
    return out
