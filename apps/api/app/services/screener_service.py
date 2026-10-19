"""Screener: field catalog, point-in-time snapshots, presets.

A snapshot is one row per instrument with every screenable field, computed only from stored, quality-filtered
data up to `as_of` (inclusive). Historical screens are therefore reproducible on the data we hold.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.analytics import funds as fa
from app.analytics import metrics as m
from app.analytics import technical as ta
from app.models import Instrument
from app.repositories.series import SeriesBundle, load_nav, load_prices


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    group: str
    type: str  # number | category | boolean
    unit: str | None  # fraction | ratio | TRY | count | index | years | None
    description: str
    available: bool = True
    reason: str | None = None


def _f(*a, **k) -> Field:
    return Field(*a, **k)


UNAVAILABLE_FUND = "Requires financial statements and shares outstanding from a licensed KAP source"
EQUITY_FIELDS: list[Field] = [
    _f("sector", "Sector", "Profile", "category", None, "Sector classification"),
    _f("close", "Last close", "Price", "number", "TRY", "Last usable close on or before the screen date"),
    _f("chg_1d", "Return 1D", "Momentum", "number", "fraction", "Close-to-close, 1 session"),
    _f("chg_1m", "Return 1M", "Momentum", "number", "fraction", "21 sessions"),
    _f("chg_3m", "Return 3M", "Momentum", "number", "fraction", "63 sessions"),
    _f("chg_1y", "Return 1Y", "Momentum", "number", "fraction", "252 sessions"),
    _f("rel_strength_1y", "Relative strength 1Y", "Momentum", "number", "fraction", "1Y return minus the index's 1Y return over the same dates"),
    _f("vol_1y", "Volatility 1Y", "Risk", "number", "fraction", "Annualised std of daily log returns, last 252 sessions"),
    _f("hv_20", "Volatility 20D", "Risk", "number", "fraction", "Annualised 20-session close-to-close volatility"),
    _f("max_dd_1y", "Max drawdown 1Y", "Risk", "number", "fraction", "Deepest peak-to-trough decline in the last 252 sessions (negative)"),
    _f("sharpe_1y", "Sharpe 1Y (rf 0)", "Risk-adjusted", "number", "ratio", "Annualised, rf = 0. TRY rates make this optimistic"),
    _f("avg_turnover_20d", "Avg turnover 20D", "Liquidity", "number", "TRY", "Mean of close × volume, last 20 sessions"),
    _f("rsi_14", "RSI 14", "Technical", "number", "index", "Wilder RSI"),
    _f("adx_14", "ADX 14", "Technical", "number", "index", "Wilder ADX (trend strength)"),
    _f("above_sma50", "Close > SMA 50", "Technical", "boolean", None, "Close above its 50-session simple moving average"),
    _f("above_sma200", "Close > SMA 200", "Technical", "boolean", None, "Close above its 200-session simple moving average"),
    _f("market_cap", "Market cap", "Valuation", "number", "TRY", "", available=False, reason=UNAVAILABLE_FUND),
    _f("pe", "P/E", "Valuation", "number", "ratio", "", available=False, reason=UNAVAILABLE_FUND),
    _f("pb", "P/B", "Valuation", "number", "ratio", "", available=False, reason=UNAVAILABLE_FUND),
    _f("roe", "ROE", "Profitability", "number", "fraction", "", available=False, reason=UNAVAILABLE_FUND),
    _f("revenue_growth", "Revenue growth", "Growth", "number", "fraction", "", available=False, reason=UNAVAILABLE_FUND),
    _f("net_debt_ebitda", "Net debt / EBITDA", "Leverage", "number", "ratio", "", available=False, reason=UNAVAILABLE_FUND),
]

FUND_FIELDS: list[Field] = [
    _f("category", "Category", "Profile", "category", None, "Fund category"),
    _f("management_company", "Management company", "Profile", "category", None, "Portfolio management company"),
    _f("management_fee", "Management fee", "Costs", "number", "fraction", "Annual management fee"),
    _f("risk_classification", "Risk class", "Profile", "number", "index", "Disclosed risk class 1–7"),
    _f("total_assets", "Fund size", "Size", "number", "TRY", "Total assets at the last NAV"),
    _f("investor_count", "Investors", "Size", "number", "count", "Investor count at the last NAV"),
    _f("history_years", "History", "Profile", "number", "years", "Years of NAV history up to the screen date"),
    _f("ret_1m", "Return 1M", "Returns", "number", "fraction", "NAV-to-NAV, calendar month (same as fund pages)"),
    _f("ret_3m", "Return 3M", "Returns", "number", "fraction", "NAV-to-NAV, calendar 3 months"),
    _f("ret_1y", "Return 1Y", "Returns", "number", "fraction", "NAV-to-NAV, calendar year"),
    _f("ret_3y_ann", "Return 3Y (ann.)", "Returns", "number", "fraction", "Annualised; missing if history < 3Y"),
    _f("vol_3y", "Volatility 3Y", "Risk", "number", "fraction", "Missing if history < 3Y"),
    _f("max_dd_3y", "Max drawdown 3Y", "Risk", "number", "fraction", "Negative; missing if history < 3Y"),
    _f("sharpe_3y", "Sharpe 3Y (rf 0)", "Risk-adjusted", "number", "ratio", "rf = 0; missing if history < 3Y or volatility < 1%"),
    _f("excess_1y", "Excess vs benchmark 1Y", "Returns", "number", "fraction", "1Y return minus benchmark over the same dates; missing without a benchmark"),
    _f("holdings_equity_share", "Equity exposure", "Holdings", "number", "fraction", "", available=False,
       reason="Requires disclosed portfolio holdings (licensed TEFAS/KAP source)"),
]

CATALOG = {"equities": EQUITY_FIELDS, "funds": FUND_FIELDS}


def field_types(universe: str) -> dict[str, str]:
    return {f.id: f.type for f in CATALOG[universe] if f.available}


def catalog(universe: str) -> list[dict]:
    return [asdict(f) for f in CATALOG[universe]]


def _ret(s: pd.Series, n: int) -> float | None:
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None


def _pr(pr: dict, key: str) -> float | None:
    return pr[key]["return"] if pr.get(key) else None


def _val(r) -> float | None:
    return r.value if r.status == "ok" else None


def equity_snapshot(db: Session, as_of: date | None) -> tuple[pd.DataFrame, list[SeriesBundle]]:
    insts = list(db.scalars(select(Instrument).where(Instrument.instrument_type == "equity").order_by(Instrument.symbol)))
    index = db.scalar(select(Instrument).where(Instrument.instrument_type == "index").order_by(Instrument.symbol))
    bundles: list[SeriesBundle] = []
    idx_close = None
    if index is not None:
        ib = load_prices(db, index)
        bundles.append(ib)
        idx_close = ib.frame["close"].loc[: pd.Timestamp(as_of)] if as_of else ib.frame["close"]
    rows = []
    for inst in insts:
        b = load_prices(db, inst)
        bundles.append(b)
        df = b.frame.loc[: pd.Timestamp(as_of)] if as_of else b.frame
        row = {"symbol": inst.symbol, "name": inst.name, "sector": inst.sector, "data_as_of": df.index[-1].date().isoformat() if len(df) else None}
        if len(df) >= 2:
            c = df["close"]
            last_year = c.iloc[-253:]
            sma50, sma200 = ta.sma(c, 50).iloc[-1], ta.sma(c, 200).iloc[-1]
            row.update(
                close=float(c.iloc[-1]), chg_1d=_ret(c, 1), chg_1m=_ret(c, 21), chg_3m=_ret(c, 63), chg_1y=_ret(c, 252),
                vol_1y=_val(m.calculate_annualized_volatility(last_year)), hv_20=float(ta.historical_volatility(c).iloc[-1]) if len(c) > 21 else None,
                max_dd_1y=_val(m.calculate_max_drawdown(last_year)), sharpe_1y=_val(m.calculate_sharpe_ratio(last_year)),
                avg_turnover_20d=float((df["close"] * df["volume"]).iloc[-20:].mean()),
                rsi_14=float(ta.rsi(c).iloc[-1]) if len(c) > 15 else None,
                adx_14=float(ta.adx(df["high"], df["low"], c)["adx"].iloc[-1]) if len(c) > 30 else None,
                above_sma50=None if np.isnan(sma50) else bool(c.iloc[-1] > sma50),
                above_sma200=None if np.isnan(sma200) else bool(c.iloc[-1] > sma200),
            )
            if idx_close is not None and row["chg_1y"] is not None:
                a, bi = m.align(c, idx_close)
                if len(a) > 252:
                    row["rel_strength_1y"] = float(a.iloc[-1] / a.iloc[-253] - 1 - (bi.iloc[-1] / bi.iloc[-253] - 1))
        rows.append(row)
    return _frame(rows, EQUITY_FIELDS), bundles


def fund_snapshot(db: Session, as_of: date | None) -> tuple[pd.DataFrame, list[SeriesBundle]]:
    insts = list(db.scalars(select(Instrument).where(Instrument.instrument_type == "fund").options(selectinload(Instrument.fund)).order_by(Instrument.symbol)))
    bundles: list[SeriesBundle] = []
    bench_cache: dict[int, pd.Series] = {}
    rows = []
    for inst in insts:
        f = inst.fund
        b = load_nav(db, inst)
        bundles.append(b)
        df = b.frame.loc[: pd.Timestamp(as_of)] if as_of else b.frame
        row = {"symbol": inst.symbol, "name": f.fund_name, "category": f.category, "management_company": f.management_company,
               "management_fee": float(f.management_fee) if f.management_fee is not None else None,
               "risk_classification": f.risk_classification, "data_as_of": df.index[-1].date().isoformat() if len(df) else None}
        if len(df) >= 2:
            nav = df["nav"]
            end = nav.index[-1]
            has_3y = nav.index[0] <= end - pd.DateOffset(years=3)
            three = nav.loc[end - pd.DateOffset(years=3):]
            vol3 = _val(m.calculate_annualized_volatility(three)) if has_3y else None
            pr = fa.period_returns(nav)
            row.update(
                total_assets=float(df["total_assets"].iloc[-1]) if pd.notna(df["total_assets"].iloc[-1]) else None,
                investor_count=float(df["investor_count"].iloc[-1]) if pd.notna(df["investor_count"].iloc[-1]) else None,
                history_years=(end - nav.index[0]).days / 365.25,
                # Same calendar definition as the fund pages (NAV on/before the date N months/years earlier).
                ret_1m=_pr(pr, "1M"), ret_3m=_pr(pr, "3M"), ret_1y=_pr(pr, "1Y"),
                ret_3y_ann=pr["3Y"]["annualized"] if pr["3Y"] else None,
                vol_3y=vol3, max_dd_3y=_val(m.calculate_max_drawdown(three)) if has_3y else None,
                sharpe_3y=_val(m.calculate_sharpe_ratio(three)) if has_3y and vol3 is not None and vol3 >= 0.01 else None,
            )
            if inst.benchmark_instrument_id and row["ret_1y"] is not None:
                if inst.benchmark_instrument_id not in bench_cache:
                    bm = db.get(Instrument, inst.benchmark_instrument_id)
                    bb = load_prices(db, bm)
                    bundles.append(bb)
                    bench_cache[inst.benchmark_instrument_id] = bb.frame["close"]
                bs = bench_cache[inst.benchmark_instrument_id]
                a, bi = m.align(nav, bs.loc[: pd.Timestamp(as_of)] if as_of else bs)
                fa_1y, ba_1y = fa.period_returns(a)["1Y"], fa.period_returns(bi)["1Y"]
                if fa_1y and ba_1y:  # both on the common dates, same calendar window
                    row["excess_1y"] = float(fa_1y["return"] - ba_1y["return"])
        rows.append(row)
    return _frame(rows, FUND_FIELDS), bundles


def _frame(rows: list[dict], fields: list[Field]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for f in fields:
        if f.available and f.id not in df:
            df[f.id] = None
    for f in fields:
        if f.available and f.type == "number":
            df[f.id] = pd.to_numeric(df[f.id], errors="coerce")
    return df


def empty_frame(universe: str) -> pd.DataFrame:
    """Zero-row frame with the universe's columns, used to validate a screen definition without loading data."""
    return _frame([], CATALOG[universe]).assign(symbol=pd.Series(dtype=str))


SNAPSHOT = {"equities": equity_snapshot, "funds": fund_snapshot}


def snapshot_id(universe: str, definition: dict, data_version: tuple, as_of: date | None) -> str:
    """Stable identifier of (query, data version, as-of). The same id means the same inputs and the same rows."""
    blob = json.dumps({"u": universe, "d": definition, "v": [str(x) for x in data_version], "a": str(as_of)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


PRESETS: dict[str, list[dict]] = {
    "equities": [
        {"id": "liquid-momentum", "name": "Liquid momentum", "description": "Positive 3M and 1Y momentum, above SMA 200, meaningful turnover",
         "filter": {"op": "and", "conditions": [
             {"field": "chg_3m", "operator": "gt", "value": 0}, {"field": "chg_1y", "operator": "gt", "value": 0},
             {"field": "above_sma200", "operator": "is_true"}, {"field": "avg_turnover_20d", "operator": "gte", "value": 1e8}]},
         "sort": {"field": "chg_3m", "descending": True}},
        {"id": "low-volatility", "name": "Low volatility", "description": "1Y volatility below 45% and drawdown shallower than −30%",
         "filter": {"op": "and", "conditions": [
             {"field": "vol_1y", "operator": "lt", "value": 0.45}, {"field": "max_dd_1y", "operator": "gt", "value": -0.30}]},
         "sort": {"field": "vol_1y", "descending": False}},
        {"id": "trend-strength", "name": "Strong trend", "description": "ADX > 25 with close above SMA 50, or relative strength > 20%",
         "filter": {"op": "or", "conditions": [
             {"op": "and", "conditions": [{"field": "adx_14", "operator": "gt", "value": 25}, {"field": "above_sma50", "operator": "is_true"}]},
             {"field": "rel_strength_1y", "operator": "gt", "value": 0.20}]},
         "sort": {"field": "rel_strength_1y", "descending": True}},
    ],
    "funds": [
        {"id": "equity-3y-leaders", "name": "Equity funds with 3Y history", "description": "Equity-type categories, ≥ 3 years history, sorted by 3Y annualised return",
         "filter": {"op": "and", "conditions": [
             {"field": "category", "operator": "in", "value": ["Equity", "Participation", "Equity (Technology)"]},
             {"field": "history_years", "operator": "gte", "value": 3}]},
         "sort": {"field": "ret_3y_ann", "descending": True}},
        {"id": "low-fee", "name": "Low fee", "description": "Management fee ≤ 2%",
         "filter": {"op": "and", "conditions": [{"field": "management_fee", "operator": "lte", "value": 0.02}]},
         "sort": {"field": "management_fee", "descending": False}},
        {"id": "shallow-drawdown", "name": "Shallow drawdown", "description": "3Y max drawdown shallower than −20%",
         "filter": {"op": "and", "conditions": [{"field": "max_dd_3y", "operator": "gt", "value": -0.20}]},
         "sort": {"field": "max_dd_3y", "descending": True}},
    ],
}
