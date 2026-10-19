"""Shared series operations: windows, resampling, JSON-safe arrays, instrument resolution."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Instrument

WINDOWS = {"1M": pd.DateOffset(months=1), "3M": pd.DateOffset(months=3), "6M": pd.DateOffset(months=6),
           "1Y": pd.DateOffset(years=1), "3Y": pd.DateOffset(years=3), "5Y": pd.DateOffset(years=5)}
INTERVALS = {"1d": None, "1w": "W-FRI", "1mo": "ME"}
MAX_POINTS = 5000


def resolve(db: Session, symbol: str, types: tuple[str, ...], exchange: str | None = None) -> Instrument:
    q = select(Instrument).where(Instrument.symbol == symbol, Instrument.instrument_type.in_(types))
    if exchange:
        q = q.where(Instrument.exchange == exchange)
    found = list(db.scalars(q))
    if not found:
        raise HTTPException(404, f"Unknown {'/'.join(types)}: {symbol}")
    if len(found) > 1:
        raise HTTPException(409, {"message": "Symbol is ambiguous; pass ?exchange=", "candidates": [
            {"symbol": i.symbol, "exchange": i.exchange, "type": i.instrument_type} for i in found]})
    return found[0]


def window_start(last: pd.Timestamp, window: str | None, explicit: date | None = None) -> pd.Timestamp | None:
    if explicit:
        return pd.Timestamp(explicit)
    if not window or window == "MAX":
        return None
    if window == "YTD":
        return pd.Timestamp(year=last.year, month=1, day=1)
    if window not in WINDOWS:
        raise HTTPException(422, f"window must be one of {['YTD', 'MAX', *WINDOWS]}")
    return last - WINDOWS[window]


def resample_ohlcv(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval not in INTERVALS:
        raise HTTPException(422, f"interval must be one of {list(INTERVALS)}")
    rule = INTERVALS[interval]
    if rule is None:
        return df
    agg = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    # Label each bar with its last actual session date (not the calendar period end), so no bar is dated in the future.
    last_session = df["close"].resample(rule).apply(lambda s: s.index[-1] if len(s) else pd.NaT).dropna()
    agg.index = pd.DatetimeIndex(last_session.loc[agg.index].values)
    return agg


def arr(s: pd.Series, digits: int = 6) -> list[float | None]:
    a = s.to_numpy(dtype=float)
    return [None if not np.isfinite(v) else round(float(v), digits) for v in a]


def dates(idx: pd.Index) -> list[str]:
    return [pd.Timestamp(d).strftime("%Y-%m-%d") for d in idx]


def num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None
