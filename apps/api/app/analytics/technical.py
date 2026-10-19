"""Technical indicators as pure functions of past data.

Contract: the value at index ``t`` depends only on observations at ``<= t`` (enforced by
``tests/test_no_lookahead.py``). Warm-up periods are NaN, never back-filled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics._smoothing import ema_alpha, seeded_recursive, wilder_alpha


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n, min_periods=n).mean()


def ema(close: pd.Series, n: int) -> pd.Series:
    return seeded_recursive(close, n, ema_alpha(n))


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI. 100 when there were no losses in the window, 50 when the price was flat."""
    delta = close.diff()
    avg_gain = seeded_recursive(delta.clip(lower=0), n, wilder_alpha(n))
    avg_loss = seeded_recursive(-delta.clip(upper=0), n, wilder_alpha(n))
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = seeded_recursive(line, signal, ema_alpha(signal))
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands with population standard deviation (Bollinger's definition)."""
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    width = upper - lower
    return pd.DataFrame(
        {
            "mid": mid,
            "upper": upper,
            "lower": lower,
            "percent_b": (close - lower) / width.replace(0, np.nan),
            "bandwidth": width / mid,
        }
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return seeded_recursive(true_range(high, low, close), n, wilder_alpha(n))


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.DataFrame:
    """Wilder ADX / DMI. Directional movement is undefined on the first bar, so it is dropped there."""
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)
    tr = true_range(high, low, close)
    plus_dm.iloc[0] = minus_dm.iloc[0] = tr.iloc[0] = np.nan

    a = wilder_alpha(n)
    s_tr = seeded_recursive(tr, n, a)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * seeded_recursive(plus_dm, n, a) / s_tr
        minus_di = 100.0 * seeded_recursive(minus_dm, n, a) / s_tr
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    dx = dx.where((plus_di + minus_di) != 0, 0.0).where(plus_di.notna())
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": seeded_recursive(dx, n, a)})


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume).cumsum()


def donchian(high: pd.Series, low: pd.Series, n: int = 20) -> pd.DataFrame:
    """Channel *including* the current bar. For breakout tests, compare close[t] to upper.shift(1)."""
    upper = high.rolling(n, min_periods=n).max()
    lower = low.rolling(n, min_periods=n).min()
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": (upper + lower) / 2})


def historical_volatility(close: pd.Series, n: int = 20, periods_per_year: int = 252) -> pd.Series:
    """Annualised close-to-close volatility of log returns (sample std)."""
    r = np.log(close / close.shift(1))
    return r.rolling(n, min_periods=n).std(ddof=1) * np.sqrt(periods_per_year)


def anchored_vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, anchor: pd.Timestamp
) -> pd.Series:
    """VWAP of the typical price, cumulative from ``anchor`` (inclusive). NaN before the anchor."""
    typical = (high + low + close) / 3.0
    mask = typical.index >= anchor
    pv = (typical * volume).where(mask).cumsum()
    vol = volume.where(mask).cumsum()
    return (pv / vol.replace(0, np.nan)).where(mask)


def relative_volume(volume: pd.Series, n: int = 20) -> pd.Series:
    """Today's volume divided by the mean of the *previous* n sessions."""
    return volume / volume.shift(1).rolling(n, min_periods=n).mean()
