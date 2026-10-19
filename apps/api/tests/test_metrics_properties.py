"""Property-based tests (Hypothesis): invariants that must hold for any valid price path."""

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from app.analytics import metrics as m

returns = st.lists(st.floats(min_value=-0.2, max_value=0.2, allow_nan=False), min_size=30, max_size=300)


def path(rs, start=100.0):
    idx = pd.bdate_range("2021-01-01", periods=len(rs) + 1)
    return pd.Series(start * np.cumprod(np.concatenate([[1.0], 1 + np.array(rs)])), index=idx)


@settings(max_examples=80, deadline=None)
@given(returns)
def test_max_drawdown_bounded(rs):
    v = m.calculate_max_drawdown(path(rs)).value
    assert -1.0 < v <= 0.0


@settings(max_examples=80, deadline=None)
@given(returns, st.floats(min_value=0.01, max_value=1000))
def test_scale_invariance(rs, k):
    p = path(rs)
    a, b = m.risk_report(p), m.risk_report(p * k)
    for name in ("annualized_volatility", "sharpe_ratio", "max_drawdown", "var_95"):
        va, vb = a[name]["value"], b[name]["value"]
        assert (va is None and vb is None) or np.isclose(va, vb, rtol=1e-9, atol=1e-12)


@settings(max_examples=80, deadline=None)
@given(returns)
def test_expected_shortfall_not_below_var(rs):
    p = path(rs)
    var, es = m.calculate_historical_var(p, 0.95, min_obs=1), m.calculate_expected_shortfall(p, 0.95, min_obs=1)
    assert es.value >= var.value - 1e-12


@settings(max_examples=60, deadline=None)
@given(returns, st.floats(min_value=0.1, max_value=3.0))
def test_beta_of_levered_path(rs, lev):
    b = path(rs)
    rb = b.pct_change().fillna(0)
    p = 100 * (1 + lev * rb).cumprod()
    if (p <= 0).any() or rb.iloc[1:].std() <= m.MIN_RETURN_STD:
        return
    assert np.isclose(m.calculate_beta(p, b).value, lev, rtol=1e-6)


def test_beta_undefined_for_numerically_flat_benchmark():
    # Found by Hypothesis: one 2e-14 return in an otherwise flat benchmark gave beta 0.49 (rounding noise) for a 0.5x path.
    b = path([0.0] * 29 + [2.0539621576142494e-14])
    p = 100 * (1 + 0.5 * b.pct_change().fillna(0)).cumprod()
    r = m.calculate_beta(p, b)
    assert r.value is None and r.detail["correlation"] is None


@settings(max_examples=60, deadline=None)
@given(returns)
def test_sharpe_sign_matches_mean_excess(rs):
    p = path(rs)
    r = m.calculate_sharpe_ratio(p)
    mean = p.pct_change().dropna().mean()
    if r.value is not None and abs(mean) > 1e-12:
        assert np.sign(r.value) == np.sign(mean)


@settings(max_examples=60, deadline=None)
@given(returns)
def test_volatility_non_negative_and_downside_le_rms(rs):
    p = path(rs)
    vol = m.calculate_annualized_volatility(p).value
    dd = m.calculate_downside_deviation(p).value
    rms = float(np.sqrt((p.pct_change().dropna() ** 2).mean()) * np.sqrt(252))
    assert vol >= 0 and dd <= rms + 1e-12
