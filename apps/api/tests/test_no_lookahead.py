"""Appending future bars must not change any historical indicator value.

This is the primary guard against look-ahead bias in everything downstream (signals, backtests).
"""

import numpy as np
import pandas as pd
import pytest

from app.analytics import technical as ta

CUT = 600


def _cases():
    return {
        "sma": lambda d: ta.sma(d["close"], 20),
        "ema": lambda d: ta.ema(d["close"], 20),
        "rsi": lambda d: ta.rsi(d["close"], 14),
        "macd": lambda d: ta.macd(d["close"]),
        "bollinger": lambda d: ta.bollinger(d["close"]),
        "atr": lambda d: ta.atr(d["high"], d["low"], d["close"]),
        "adx": lambda d: ta.adx(d["high"], d["low"], d["close"]),
        "obv": lambda d: ta.obv(d["close"], d["volume"]),
        "donchian": lambda d: ta.donchian(d["high"], d["low"]),
        "hv": lambda d: ta.historical_volatility(d["close"]),
        "rvol": lambda d: ta.relative_volume(d["volume"]),
        "avwap": lambda d: ta.anchored_vwap(d["high"], d["low"], d["close"], d["volume"], d.index[100]),
    }


@pytest.mark.parametrize("name", list(_cases()))
def test_indicator_is_causal(bars, name):
    f = _cases()[name]
    full = f(bars)
    truncated = f(bars.iloc[:CUT])
    pd.testing.assert_frame_equal(
        pd.DataFrame(full).iloc[:CUT], pd.DataFrame(truncated), check_exact=False, rtol=1e-12
    )


@pytest.mark.parametrize("name", list(_cases()))
def test_future_shock_does_not_leak(bars, name):
    shocked = bars.copy()
    shocked.iloc[CUT:, :4] *= 3.0  # massive change after the cut
    a = pd.DataFrame(_cases()[name](bars)).iloc[:CUT]
    b = pd.DataFrame(_cases()[name](shocked)).iloc[:CUT]
    assert np.allclose(a.to_numpy(), b.to_numpy(), equal_nan=True)
