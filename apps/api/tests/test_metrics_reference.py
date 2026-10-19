"""Reference tests: expected values derived by hand (shown in comments), independent of the implementation."""

import math

import numpy as np
import pandas as pd
import pytest

from app.analytics import metrics as m


def s(vals, start="2024-01-01", freq="B"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq=freq), dtype=float)


# Prices 100 → 110 → 99 → 108.9 give simple returns +10%, -10%, +10%.
P = s([100, 110, 99, 108.9])


def test_simple_and_log_returns():
    np.testing.assert_allclose(m.calculate_simple_returns(P).to_numpy(), [0.1, -0.1, 0.1])
    np.testing.assert_allclose(m.calculate_log_returns(P).to_numpy(), [math.log(1.1), math.log(0.9), math.log(1.1)])


def test_sharpe_hand_computed():
    # mean = 0.1/3 = 0.033333; deviations +0.066667, -0.133333, +0.066667
    # sample var = (0.004444 + 0.017778 + 0.004444) / 2 = 0.013333 → sd = 0.115470
    # daily Sharpe = 0.288675; annualised × sqrt(252) = 4.582576
    r = m.calculate_sharpe_ratio(P, rf_annual=0.0, min_obs=3)
    assert r.status == "ok" and r.n_obs == 3
    assert r.value == pytest.approx(4.582576, rel=1e-6)


def test_sharpe_with_rf_uses_geometric_daily_rate():
    rf = 0.40
    d = 1.4 ** (1 / 252) - 1  # 0.0013362...
    ex = np.array([0.1, -0.1, 0.1]) - d
    want = ex.mean() / ex.std(ddof=1) * math.sqrt(252)
    assert m.calculate_sharpe_ratio(P, rf, min_obs=3).value == pytest.approx(want)
    assert m.calculate_sharpe_ratio(P, rf, min_obs=3).methodology["rf_per_period"] == pytest.approx(d)


def test_downside_deviation_and_sortino_hand_computed():
    # Only -0.1 is below target 0: sqrt((0 + 0.01 + 0)/3) = 0.057735 → × sqrt(252) = 0.916515
    dd = m.calculate_downside_deviation(P, min_obs=3)
    assert dd.value == pytest.approx(0.916515, rel=1e-6)
    # Sortino = mean × 252 / dd = 0.033333 × 252 / 0.916515 = 9.165151
    assert m.calculate_sortino_ratio(P, min_obs=3).value == pytest.approx(9.165151, rel=1e-6)


def test_max_drawdown_hand_computed():
    prices = s([100, 120, 90, 60, 80, 121, 110])
    r = m.calculate_max_drawdown(prices)
    assert r.value == pytest.approx(60 / 120 - 1)  # -0.5
    assert r.detail["peak_date"] == prices.index[1].date().isoformat()
    assert r.detail["trough_date"] == prices.index[3].date().isoformat()
    assert r.detail["recovery_date"] == prices.index[5].date().isoformat()


def test_cagr_calendar_time():
    p = pd.Series([100.0, 121.0], index=pd.to_datetime(["2020-01-01", "2022-01-01"]))  # 731 days
    assert m.calculate_cagr(p).value == pytest.approx(1.21 ** (365.25 / 731) - 1)


def test_calmar():
    p = pd.Series([100.0, 50.0, 121.0], index=pd.to_datetime(["2020-01-01", "2021-01-01", "2022-01-01"]))
    want = (1.21 ** (365.25 / 731) - 1) / 0.5
    assert m.calculate_calmar_ratio(p, min_obs=3).value == pytest.approx(want)


def test_var_and_es_on_known_distribution():
    # 100 returns: -10%, -9%, ..., +89% (step 1%). Build prices from them.
    rets = np.arange(-10, 90) / 100.0
    prices = s(np.concatenate([[100.0], 100.0 * np.cumprod(1 + rets)]))
    var = m.calculate_historical_var(prices, 0.95)
    # Sorted r[0..5] = -0.10, -0.09, -0.08, -0.07, -0.06, -0.05. numpy linear quantile at position 0.05*99 = 4.95:
    # r[4] + 0.95*(r[5]-r[4]) = -0.06 + 0.0095 = -0.0505 → VaR 0.0505
    assert var.value == pytest.approx(0.0505)
    es = m.calculate_expected_shortfall(prices, 0.95)
    # Returns <= -0.0505: -0.10, -0.09, -0.08, -0.07, -0.06 → mean -0.08
    assert es.value == pytest.approx(0.08)


def test_beta_tracking_error_information_ratio():
    b = s([100, 102, 100.98, 103.0, 101.97])  # returns +2%, -1%, +2%, -1% (approx)
    rb = b.pct_change().dropna()
    p = (1 + 2 * rb).cumprod() * 50  # exactly 2x the benchmark returns
    p = pd.concat([pd.Series([50.0], index=[b.index[0]]), p])
    beta = m.calculate_beta(p, b, min_obs=4)
    assert beta.value == pytest.approx(2.0)
    active = 2 * rb - rb  # = rb
    te = m.calculate_tracking_error(p, b, min_obs=4)
    assert te.value == pytest.approx(rb.std(ddof=1) * math.sqrt(252))
    ir = m.calculate_information_ratio(p, b, min_obs=4)
    assert ir.value == pytest.approx(active.mean() * 252 / te.value)


def test_capture_ratios_of_levered_series():
    rng = np.random.default_rng(3)
    b = s(100 * np.cumprod(1 + rng.normal(0, 0.01, 300)))
    rb = b.pct_change().fillna(0)
    p = 100 * (1 + 1.5 * rb).cumprod()
    cap = m.calculate_capture_ratios(p, b)
    assert cap.detail["upside_capture"] == pytest.approx(1.5) and cap.detail["downside_capture"] == pytest.approx(1.5)


def test_rolling_returns_and_correlation():
    p = s([100, 110, 121, 133.1])
    np.testing.assert_allclose(m.calculate_rolling_returns(p, 2).dropna().to_numpy(), [0.21, 0.21])
    q = s([100, 110, 99, 108.9, 120, 114])
    corr = m.calculate_rolling_correlation(q, q * 3, window=3).dropna()
    assert len(corr) == 3 and np.allclose(corr, 1.0)
    anti = m.calculate_rolling_correlation(q, 1 / q, window=3).dropna()
    assert (anti < -0.99).all()


# ── Edge cases ────────────────────────────────────────────────────────────────────────────────────
def test_constant_prices_give_undefined_not_zero():
    flat = s([100.0] * 30)
    r = m.calculate_sharpe_ratio(flat)
    assert r.status == "undefined" and r.value is None
    assert m.calculate_sortino_ratio(flat).value is None
    assert m.calculate_max_drawdown(flat).value == 0.0  # mathematically defined


def test_insufficient_samples_flagged():
    r = m.calculate_annualized_volatility(s([1, 2, 3]))
    assert r.status == "insufficient_data" and r.value is None and r.n_obs == 2
    assert m.calculate_historical_var(s(np.linspace(1, 2, 50)), 0.99).status == "insufficient_data"  # needs >= 500


def test_missing_values_dropped_and_reported():
    p = s([100, np.nan, 110, 121] + list(np.linspace(121, 140, 30)))
    r = m.calculate_annualized_volatility(p)
    assert r.methodology["dropped_missing"] == 1 and r.status == "ok"


def test_relative_metrics_use_common_dates_only():
    a = s(np.linspace(100, 130, 60))
    b = a.iloc[10:] * 2
    assert m.calculate_beta(a, b).n_obs == len(b) - 1


def test_risk_report_shape():
    rep = m.risk_report(s(100 * np.cumprod(1 + np.random.default_rng(1).normal(0, 0.01, 600))), rf_annual=0.3)
    assert {"sharpe_ratio", "max_drawdown", "var_95", "expected_shortfall_99"} <= set(rep)
    assert all({"value", "status", "n_obs", "methodology"} <= set(v) for v in rep.values())
