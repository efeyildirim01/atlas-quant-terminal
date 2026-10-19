"""Indicator correctness against hand-computed values and naive reference implementations."""

import math

import numpy as np
import pandas as pd
import pytest

from app.analytics import technical as ta

IDX = pd.bdate_range("2024-01-01", periods=10)


def s(vals):
    return pd.Series(vals, index=IDX[: len(vals)], dtype=float)


def test_sma_known_values():
    out = ta.sma(s([1, 2, 3, 4, 5]), 3)
    assert out.isna().tolist() == [True, True, False, False, False]
    assert out.iloc[2:].tolist() == [2.0, 3.0, 4.0]


def test_ema_seeded_with_sma_then_recursive():
    out = ta.ema(s([1, 2, 3, 4, 5]), 3)  # alpha = 0.5
    assert math.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)  # seed = mean(1,2,3)
    assert out.iloc[3] == pytest.approx(3.0)  # 2 + .5*(4-2)
    assert out.iloc[4] == pytest.approx(4.0)


def naive_wilder_rsi(close: list[float], n: int) -> list[float]:
    d = np.diff(close)
    g, l = np.maximum(d, 0), np.maximum(-d, 0)
    ag, al = g[:n].mean(), l[:n].mean()
    out = [100 - 100 / (1 + ag / al)]
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + l[i]) / n
        out.append(100 - 100 / (1 + ag / al))
    return out


def test_rsi_matches_naive_wilder(random_walk):
    got = ta.rsi(random_walk, 14).dropna().to_numpy()
    want = naive_wilder_rsi(random_walk.tolist(), 14)
    np.testing.assert_allclose(got, want, rtol=1e-10)
    assert ta.rsi(random_walk, 14).first_valid_index() == random_walk.index[14]


def test_rsi_edge_cases():
    assert ta.rsi(s(range(1, 10)), 3).dropna().eq(100).all()  # only gains
    assert ta.rsi(s([5] * 8), 3).dropna().eq(50).all()  # flat
    assert ta.rsi(s(range(10, 1, -1)), 3).dropna().eq(0).all()  # only losses


def test_macd_identity(random_walk):
    m = ta.macd(random_walk)
    np.testing.assert_allclose((m["macd"] - m["signal"]).dropna(), m["hist"].dropna())
    assert m["macd"].first_valid_index() == random_walk.index[25]
    assert m["signal"].first_valid_index() == random_walk.index[25 + 8]


def test_bollinger_population_std():
    close = s([1, 2, 3, 4, 5])
    bb = ta.bollinger(close, 5, 2.0)
    sd = np.std([1, 2, 3, 4, 5])  # ddof=0
    assert bb["upper"].iloc[-1] == pytest.approx(3 + 2 * sd)
    assert bb["percent_b"].iloc[-1] == pytest.approx((5 - (3 - 2 * sd)) / (4 * sd))


def test_true_range_and_atr():
    h, l, c = s([10, 12, 11]), s([8, 9, 7]), s([9, 11, 8])
    tr = ta.true_range(h, l, c)
    assert tr.tolist() == [2, 3, 4]  # 10-8 ; max(3, |12-9|, |9-9|) ; max(4, 0, |7-11|)
    a = ta.atr(h, l, c, 2)
    assert a.iloc[1] == pytest.approx(2.5)
    assert a.iloc[2] == pytest.approx(2.5 + 0.5 * (4 - 2.5))


def test_adx_bounds_and_trend(bars):
    d = ta.adx(bars["high"], bars["low"], bars["close"], 14).dropna()
    assert ((d >= 0) & (d <= 100)).all().all()
    # Strict uptrend: +DI dominates and ADX is high.
    up = pd.Series(np.arange(100, 160, dtype=float), index=pd.bdate_range("2024-01-01", periods=60))
    t = ta.adx(up + 1, up - 1, up, 14).iloc[-1]
    assert t["plus_di"] > t["minus_di"] and t["adx"] > 50


def test_obv():
    out = ta.obv(s([10, 11, 11, 10]), s([100, 200, 300, 400]))
    assert out.tolist() == [0, 200, 200, -200]


def test_donchian_and_rvol():
    dc = ta.donchian(s([1, 3, 2, 5]), s([0, 1, 1, 2]), 2)
    assert dc["upper"].tolist()[1:] == [3, 3, 5]
    rv = ta.relative_volume(s([10, 10, 10, 20]), 3)
    assert rv.iloc[-1] == pytest.approx(2.0)


def test_anchored_vwap():
    h, l, c, v = s([3, 6, 9]), s([1, 4, 7]), s([2, 5, 8]), s([1, 1, 2])
    out = ta.anchored_vwap(h, l, c, v, IDX[1])
    assert math.isnan(out.iloc[0])
    assert out.iloc[2] == pytest.approx((5 * 1 + 8 * 2) / 3)


def test_historical_volatility_scaling():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2020-01-01", periods=5000)
    p = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx)
    hv = ta.historical_volatility(p, 4999).iloc[-1]
    assert hv == pytest.approx(0.01 * math.sqrt(252), rel=0.03)


def test_interior_nan_is_rejected():
    with pytest.raises(ValueError):
        ta.ema(s([1, 2, np.nan, 4, 5, 6]), 2)
