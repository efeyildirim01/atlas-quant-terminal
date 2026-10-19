"""Recursive smoothers shared by EMA, Wilder RSI/ATR/ADX.

Both are seeded with the simple mean of the first ``n`` valid observations (TA-Lib convention),
so the first output appears at index ``first_valid + n - 1`` and nothing earlier is fabricated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def seeded_recursive(x: pd.Series, n: int, alpha: float) -> pd.Series:
    if n < 1:
        raise ValueError("window must be >= 1")
    values = x.to_numpy(dtype=float)
    out = np.full(values.shape, np.nan)
    valid = np.flatnonzero(~np.isnan(values))
    if len(valid) < n:
        return pd.Series(out, index=x.index)
    start = valid[0]
    seed = start + n - 1
    if np.isnan(values[start : seed + 1]).any():
        raise ValueError("interior NaN in input; validate/clean the series first")
    out[seed] = values[start : seed + 1].mean()
    for i in range(seed + 1, len(values)):
        v = values[i]
        if np.isnan(v):
            raise ValueError("interior NaN in input; validate/clean the series first")
        out[i] = out[i - 1] + alpha * (v - out[i - 1])
    return pd.Series(out, index=x.index)


def ema_alpha(n: int) -> float:
    return 2.0 / (n + 1.0)


def wilder_alpha(n: int) -> float:
    return 1.0 / n
