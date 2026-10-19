"""Equity research computations. Routers call these, and they call analytics. No formulas live in routers or UI."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics import metrics as m
from app.analytics import technical as ta
from app.services.series_ops import arr, dates, num, resample_ohlcv

INSUFFICIENT_SIGNAL = {
    "classification": "insufficient_evidence",
    "reason": "No signal model has passed out-of-sample calibration. Readings are descriptive, not recommendations.",
}


def quote_summary(df: pd.DataFrame) -> dict:
    """Latest session summary from usable daily bars."""
    if df.empty:
        return {"available": False}
    c = df["close"]
    last, prev = c.iloc[-1], (c.iloc[-2] if len(c) > 1 else np.nan)
    year = df.loc[df.index[-1] - pd.DateOffset(years=1):]
    hi_date, lo_date = year["high"].idxmax(), year["low"].idxmin()
    turnover = (df["close"] * df["volume"]).iloc[-20:]
    return {
        "available": True, "as_of": df.index[-1].date().isoformat(), "close": num(last), "previous_close": num(prev),
        "change": num(last - prev), "change_pct": num(last / prev - 1), "volume": num(df["volume"].iloc[-1]),
        "high_52w": {"value": num(year["high"].max()), "date": hi_date.date().isoformat()},
        "low_52w": {"value": num(year["low"].min()), "date": lo_date.date().isoformat()},
        "avg_turnover_20d": num(turnover.mean()),
        "market_cap": None, "market_cap_note": "Unavailable: no licensed shares-outstanding source",
    }


def price_payload(df: pd.DataFrame, interval: str) -> dict:
    bars = resample_ohlcv(df, interval)
    return {"interval": interval, "dates": dates(bars.index), **{k: arr(bars[k], 4) for k in ["open", "high", "low", "close"]},
            "volume": arr(bars["volume"], 0)}


PERIODS_PER_YEAR = {"1d": 252, "1w": 52, "1mo": 12}


def _indicators(bars: pd.DataFrame, periods_per_year: int) -> pd.DataFrame:
    h, l, c, v = bars["high"], bars["low"], bars["close"], bars["volume"]
    out = pd.DataFrame({
        "sma_20": ta.sma(c, 20), "sma_50": ta.sma(c, 50), "sma_200": ta.sma(c, 200), "ema_20": ta.ema(c, 20),
        "rsi_14": ta.rsi(c, 14), "atr_14": ta.atr(h, l, c, 14), "obv": ta.obv(c, v),
        "hv_20": ta.historical_volatility(c, 20, periods_per_year), "rvol_20": ta.relative_volume(v, 20),
    })
    out = out.join(ta.macd(c).add_prefix("macd_")).join(ta.bollinger(c).add_prefix("bb_"))
    out = out.join(ta.adx(h, l, c).rename(columns=lambda x: f"dmi_{x}")).join(ta.donchian(h, l, 20).add_prefix("dc20_"))
    return out.join(ta.donchian(h, l, 55).add_prefix("dc55_"))


def technicals(full: pd.DataFrame, start: pd.Timestamp | None, interval: str) -> dict:
    """Chart series on the requested interval (computed on full history for correct warm-up, then trimmed).

    Research readings always use DAILY bars, so they do not change meaning with the chart interval
    (e.g. a weekly HV must annualise with sqrt(52), and "63d" must mean 63 sessions).
    """
    bars = resample_ohlcv(full, interval)
    out = _indicators(bars, PERIODS_PER_YEAR[interval])
    view = out.loc[start:] if start is not None else out
    anchor = view.index[0] if len(view) else None
    h, l, c, v = bars["high"], bars["low"], bars["close"], bars["volume"]
    vwap = ta.anchored_vwap(h, l, c, v, anchor).loc[view.index] if anchor is not None else pd.Series(dtype=float)
    series = {k: arr(view[k], 4) for k in view.columns}
    series["avwap"] = arr(vwap, 4)
    daily_ind = out if interval == "1d" else _indicators(full, PERIODS_PER_YEAR["1d"])
    return {"interval": interval, "periods_per_year": PERIODS_PER_YEAR[interval], "dates": dates(view.index), "series": series,
            "research": _research(full, daily_ind), "research_basis": "daily bars", "signal": INSUFFICIENT_SIGNAL}


def _trend(close: float, ma: float | None) -> str | None:
    if ma is None or not np.isfinite(ma):
        return None
    return "above" if close > ma else "below"


def _research(daily: pd.DataFrame, ind: pd.DataFrame) -> dict:
    """Descriptive, objectively defined readings. No composite score."""
    last = ind.iloc[-1]
    close = float(daily["close"].iloc[-1])
    weekly = resample_ohlcv(daily, "1w") if len(daily) > 260 else None
    w_sma20 = ta.sma(weekly["close"], 20).iloc[-1] if weekly is not None else np.nan
    d_dir, w_dir = _trend(close, last["sma_50"]), _trend(close, w_sma20)
    hv = ind["hv_20"].dropna()
    hv_pct = float((hv.iloc[-756:] < hv.iloc[-1]).mean()) if len(hv) > 60 else None
    return {
        "trend": {"close_vs_sma50": d_dir, "close_vs_sma200": _trend(close, last["sma_200"]),
                  "adx_14": num(last["dmi_adx"]), "plus_di": num(last["dmi_plus_di"]), "minus_di": num(last["dmi_minus_di"]),
                  "definition": "Close relative to moving averages; ADX > 25 conventionally read as a trending market"},
        "momentum": {"rsi_14": num(last["rsi_14"]), "macd_hist": num(last["macd_hist"]),
                     "roc_63": num(close / daily["close"].iloc[-64] - 1) if len(daily) > 63 else None},
        "volatility": {"atr_pct": num(last["atr_14"] / close), "hv_20": num(last["hv_20"]), "hv_20_percentile_3y": hv_pct,
                       "bb_bandwidth": num(last["bb_bandwidth"])},
        "volume": {"relative_volume_20": num(last["rvol_20"]), "obv_change_20": num(ind["obv"].iloc[-1] - ind["obv"].iloc[-21]) if len(ind) > 21 else None},
        "levels": {"donchian20_high": num(last["dc20_upper"]), "donchian20_low": num(last["dc20_lower"]),
                   "donchian55_high": num(last["dc55_upper"]), "donchian55_low": num(last["dc55_lower"]),
                   "definition": "Objective support/resistance research: rolling 20/55-session high/low (Donchian)"},
        "multi_timeframe": {"daily_close_vs_sma50": d_dir, "weekly_close_vs_sma20w": w_dir,
                            "alignment": None if not (d_dir and w_dir) else ("aligned_up" if d_dir == w_dir == "above" else "aligned_down" if d_dir == w_dir == "below" else "mixed")},
    }


def return_distribution(prices: pd.Series, bins: int = 40) -> dict:
    r = m.calculate_simple_returns(prices)
    if len(r) < 20:
        return {"available": False}
    counts, edges = np.histogram(r, bins=bins)
    return {"available": True, "edges": [float(e) for e in edges], "counts": [int(c) for c in counts], "n_obs": int(len(r)),
            "mean": float(r.mean()), "std": float(r.std(ddof=1))}


def liquidity(df: pd.DataFrame) -> dict:
    turnover = df["close"] * df["volume"]
    r = df["close"].pct_change(fill_method=None).abs()
    amihud = (r / turnover.replace(0, np.nan)).iloc[-252:].mean() * 1e9
    return {
        "avg_turnover_20d": num(turnover.iloc[-20:].mean()), "avg_turnover_60d": num(turnover.iloc[-60:].mean()),
        "median_volume_60d": num(df["volume"].iloc[-60:].median()),
        "zero_volume_days_1y": int((df["volume"].iloc[-252:] == 0).sum()),
        "amihud_illiquidity_1y": num(amihud),
        "definitions": {"turnover": "close × volume (TRY)", "amihud": "mean(|r| / turnover) × 1e9 over the last 252 sessions"},
    }


def relative_performance(p: pd.Series, b: pd.Series) -> dict:
    pa, ba = m.align(p, b)
    if len(pa) < 2:
        return {"available": False}
    rp, rb = pa.iloc[-1] / pa.iloc[0] - 1, ba.iloc[-1] / ba.iloc[0] - 1
    return {"available": True, "return": num(rp), "benchmark_return": num(rb), "excess_return": num(rp - rb),
            "start": pa.index[0].date().isoformat(), "end": pa.index[-1].date().isoformat()}
