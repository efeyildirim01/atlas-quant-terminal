"""Quantitative analytics library. Pure, deterministic, documented.

Conventions (docs/financial-methodology/METRICS.md):
- Inputs are price/NAV levels indexed by date. NaNs are dropped (never filled). The count is reported.
- Simple returns r_t = P_t / P_{t-1} - 1; log returns l_t = ln(P_t / P_{t-1}).
- Annualisation uses ``periods_per_year`` (252 for BIST/TEFAS daily). Volatility scales by sqrt(periods).
- The risk-free rate is an explicit *annual* decimal, converted per period geometrically: (1+rf)^(1/k) - 1.
- Undefined results (zero denominators) return ``value=None`` with status "undefined", never 0.
- Too few observations return ``value=None`` with status "insufficient_data".
- VaR / expected shortfall are historical, one-period, reported as positive loss fractions.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

TRADING_DAYS = 252
MIN_OBS = 20

Status = Literal["ok", "insufficient_data", "undefined"]


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: float | None
    status: Status
    n_obs: int
    unit: str
    start: str | None = None
    end: str | None = None
    methodology: dict = field(default_factory=dict)
    detail: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(prices: pd.Series) -> tuple[pd.Series, int]:
    s = prices.astype(float)
    n_missing = int(s.isna().sum())
    return s.dropna().sort_index(), n_missing


def _span(s: pd.Series) -> tuple[str | None, str | None]:
    if s.empty:
        return None, None
    return pd.Timestamp(s.index[0]).date().isoformat(), pd.Timestamp(s.index[-1]).date().isoformat()


def _result(name: str, value: float | None, n: int, unit: str, s: pd.Series, method: dict, *, min_obs: int,
            detail: dict | None = None, n_missing: int = 0) -> MetricResult:
    start, end = _span(s)
    m = {**method, "min_obs": min_obs, "dropped_missing": n_missing}
    if n < min_obs:
        return MetricResult(name, None, "insufficient_data", n, unit, start, end, m, detail)
    if value is None or not math.isfinite(value):
        return MetricResult(name, None, "undefined", n, unit, start, end, m, detail)
    return MetricResult(name, float(value), "ok", n, unit, start, end, m, detail)


def per_period_rf(rf_annual: float, periods_per_year: int = TRADING_DAYS) -> float:
    return (1.0 + rf_annual) ** (1.0 / periods_per_year) - 1.0


# ── Return series ─────────────────────────────────────────────────────────────────────────────────
def calculate_simple_returns(prices: pd.Series) -> pd.Series:
    """r_t = P_t/P_{t-1} - 1 on consecutive *available* observations (missing levels are dropped, not filled)."""
    s, _ = _clean(prices)
    return s.pct_change(fill_method=None).dropna()


def calculate_log_returns(prices: pd.Series) -> pd.Series:
    s, _ = _clean(prices)
    return np.log(s / s.shift(1)).dropna()


def calculate_rolling_returns(prices: pd.Series, window: int) -> pd.Series:
    """Trailing ``window``-observation return; NaN until ``window`` prior observations exist."""
    s, _ = _clean(prices)
    return s / s.shift(window) - 1.0


def calculate_rolling_correlation(a: pd.Series, b: pd.Series, window: int = 60) -> pd.Series:
    """Pearson correlation of simple returns over a trailing window, on common dates only."""
    ra, rb = _aligned_returns(a, b)
    return ra.rolling(window, min_periods=window).corr(rb)


# ── Scalar metrics ────────────────────────────────────────────────────────────────────────────────
def calculate_cagr(prices: pd.Series, min_obs: int = 2) -> MetricResult:
    s, miss = _clean(prices)
    method = {"formula": "(P_end/P_start)^(1/years) - 1", "years": "calendar days / 365.25"}
    if len(s) < 2:
        return _result("cagr", None, len(s), "annualized_fraction", s, method, min_obs=min_obs, n_missing=miss)
    years = (s.index[-1] - s.index[0]).days / 365.25
    value = (s.iloc[-1] / s.iloc[0]) ** (1.0 / years) - 1.0 if years > 0 and s.iloc[0] > 0 else None
    return _result("cagr", value, len(s), "annualized_fraction", s, method, min_obs=min_obs, n_missing=miss)


def calculate_annualized_volatility(prices: pd.Series, periods_per_year: int = TRADING_DAYS, min_obs: int = MIN_OBS) -> MetricResult:
    s, miss = _clean(prices)
    r = np.log(s / s.shift(1)).dropna()
    value = float(r.std(ddof=1) * math.sqrt(periods_per_year)) if len(r) > 1 else None
    method = {"returns": "log", "estimator": "sample std (ddof=1)", "annualization": f"sqrt({periods_per_year})"}
    return _result("annualized_volatility", value, len(r), "annualized_fraction", s, method, min_obs=min_obs, n_missing=miss)


def _excess(prices: pd.Series, rf_annual: float, periods_per_year: int) -> tuple[pd.Series, pd.Series, int]:
    s, miss = _clean(prices)
    return s, s.pct_change(fill_method=None).dropna() - per_period_rf(rf_annual, periods_per_year), miss


def calculate_sharpe_ratio(prices: pd.Series, rf_annual: float = 0.0, periods_per_year: int = TRADING_DAYS,
                           min_obs: int = MIN_OBS) -> MetricResult:
    s, ex, miss = _excess(prices, rf_annual, periods_per_year)
    sd = ex.std(ddof=1) if len(ex) > 1 else float("nan")
    value = float(ex.mean() / sd * math.sqrt(periods_per_year)) if sd and np.isfinite(sd) and sd > 0 else None
    method = {"formula": "mean(r - rf_p) / std(r - rf_p) * sqrt(k)", "returns": "simple", "rf_annual": rf_annual,
              "rf_per_period": per_period_rf(rf_annual, periods_per_year), "k": periods_per_year}
    return _result("sharpe_ratio", value, len(ex), "ratio", s, method, min_obs=min_obs, n_missing=miss)


def calculate_downside_deviation(prices: pd.Series, rf_annual: float = 0.0, periods_per_year: int = TRADING_DAYS,
                                 min_obs: int = MIN_OBS) -> MetricResult:
    s, ex, miss = _excess(prices, rf_annual, periods_per_year)
    value = float(np.sqrt((np.minimum(ex, 0.0) ** 2).mean()) * math.sqrt(periods_per_year)) if len(ex) else None
    method = {"formula": "sqrt(mean(min(r - rf_p, 0)^2)) * sqrt(k)", "target": "rf", "denominator": "all observations"}
    return _result("downside_deviation", value, len(ex), "annualized_fraction", s, method, min_obs=min_obs, n_missing=miss)


def calculate_sortino_ratio(prices: pd.Series, rf_annual: float = 0.0, periods_per_year: int = TRADING_DAYS,
                            min_obs: int = MIN_OBS) -> MetricResult:
    s, ex, miss = _excess(prices, rf_annual, periods_per_year)
    dd = calculate_downside_deviation(prices, rf_annual, periods_per_year, min_obs).value
    value = float(ex.mean() * periods_per_year / dd) if dd else None
    method = {"formula": "mean(r - rf_p) * k / downside_deviation", "rf_annual": rf_annual}
    return _result("sortino_ratio", value, len(ex), "ratio", s, method, min_obs=min_obs, n_missing=miss)


def calculate_max_drawdown(prices: pd.Series, min_obs: int = 2) -> MetricResult:
    s, miss = _clean(prices)
    method = {"formula": "min(P_t / max_{u<=t} P_u - 1)", "recovery": "first date the prior peak is regained"}
    if len(s) < min_obs:
        return _result("max_drawdown", None, len(s), "fraction", s, method, min_obs=min_obs, n_missing=miss)
    dd = s / s.cummax() - 1.0
    trough = dd.idxmin()
    depth = float(dd.loc[trough])
    if depth == 0:
        return _result("max_drawdown", 0.0, len(s), "fraction", s, method, min_obs=min_obs, n_missing=miss,
                       detail={"peak_date": None, "trough_date": None, "recovery_date": None, "recovery_days": None})
    peak = s.loc[:trough].idxmax()
    after = s.loc[trough:]
    recovered = after[after >= s.loc[peak]]
    rec = recovered.index[0] if len(recovered) else None
    iso = lambda d: pd.Timestamp(d).date().isoformat()  # noqa: E731
    detail = {"peak_date": iso(peak), "trough_date": iso(trough), "recovery_date": iso(rec) if rec is not None else None,
              "recovery_days": (rec - peak).days if rec is not None else None,
              "days_since_peak_if_unrecovered": None if rec is not None else (s.index[-1] - peak).days}
    return _result("max_drawdown", depth, len(s), "fraction", s, method, min_obs=min_obs, n_missing=miss, detail=detail)


def calculate_calmar_ratio(prices: pd.Series, min_obs: int = MIN_OBS) -> MetricResult:
    s, miss = _clean(prices)
    c, m = calculate_cagr(prices).value, calculate_max_drawdown(prices).value
    value = c / abs(m) if c is not None and m not in (None, 0.0) else None
    return _result("calmar_ratio", value, len(s), "ratio", s, {"formula": "CAGR / |max drawdown|", "window": "full sample"},
                   min_obs=min_obs, n_missing=miss)


def _aligned_returns(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Simple returns of both series computed on their *common* dates (no stale-price returns)."""
    sa, _ = _clean(a)
    sb, _ = _clean(b)
    joined = pd.concat([sa, sb], axis=1, join="inner")
    ra, rb = joined.iloc[:, 0].pct_change(fill_method=None), joined.iloc[:, 1].pct_change(fill_method=None)
    ok = ra.notna() & rb.notna()
    return ra[ok], rb[ok]


_REL_METHOD = {"returns": "simple, on common dates only", "alignment": "inner join of observation dates"}


# Below this per-period return std a series is numerically flat: prices differ only by floating-point rounding, so a
# ratio of (co)variances would be noise. Real quoted prices move by >= 1e-6; this floor is far below that.
MIN_RETURN_STD = 1e-10


def calculate_beta(prices: pd.Series, benchmark: pd.Series, min_obs: int = MIN_OBS) -> MetricResult:
    ra, rb = _aligned_returns(prices, benchmark)
    sd_b = rb.std(ddof=1) if len(rb) > 1 else float("nan")
    value = float(ra.cov(rb) / sd_b**2) if np.isfinite(sd_b) and sd_b > MIN_RETURN_STD else None
    corr = float(ra.corr(rb)) if len(ra) > 1 and ra.std() > MIN_RETURN_STD and sd_b > MIN_RETURN_STD else None
    return _result("beta", value, len(ra), "ratio", ra, {**_REL_METHOD, "formula": "cov(r, r_b) / var(r_b)"},
                   min_obs=min_obs, detail={"correlation": corr})


def calculate_tracking_error(prices: pd.Series, benchmark: pd.Series, periods_per_year: int = TRADING_DAYS,
                             min_obs: int = MIN_OBS) -> MetricResult:
    ra, rb = _aligned_returns(prices, benchmark)
    active = ra - rb
    value = float(active.std(ddof=1) * math.sqrt(periods_per_year)) if len(active) > 1 else None
    return _result("tracking_error", value, len(active), "annualized_fraction", active,
                   {**_REL_METHOD, "formula": "std(r - r_b) * sqrt(k)"}, min_obs=min_obs)


def calculate_information_ratio(prices: pd.Series, benchmark: pd.Series, periods_per_year: int = TRADING_DAYS,
                                min_obs: int = MIN_OBS) -> MetricResult:
    ra, rb = _aligned_returns(prices, benchmark)
    active = ra - rb
    te = active.std(ddof=1) * math.sqrt(periods_per_year) if len(active) > 1 else float("nan")
    value = float(active.mean() * periods_per_year / te) if np.isfinite(te) and te > 0 else None
    return _result("information_ratio", value, len(active), "ratio", active,
                   {**_REL_METHOD, "formula": "mean(r - r_b) * k / tracking_error"}, min_obs=min_obs)


def calculate_capture_ratios(prices: pd.Series, benchmark: pd.Series, min_obs: int = MIN_OBS) -> MetricResult:
    """Upside/downside capture on common dates: mean(r | r_b > 0) / mean(r_b | r_b > 0), likewise for r_b < 0.

    Arithmetic per-period means (not the geometric Morningstar variant); stated in the methodology.
    """
    ra, rb = _aligned_returns(prices, benchmark)
    up, down = rb > 0, rb < 0
    upside = float(ra[up].mean() / rb[up].mean()) if up.sum() >= 5 else None
    downside = float(ra[down].mean() / rb[down].mean()) if down.sum() >= 5 else None
    method = {**_REL_METHOD, "formula": "mean(r | r_b>0)/mean(r_b | r_b>0); downside analogous", "averaging": "arithmetic"}
    return _result("capture_ratios", upside, len(ra), "ratio", ra, method, min_obs=min_obs,
                   detail={"upside_capture": upside, "downside_capture": downside,
                           "n_up_periods": int(up.sum()), "n_down_periods": int(down.sum())})


def _tail_min_obs(level: float) -> int:
    return int(math.ceil(5.0 / (1.0 - level)))  # need >= 5 observations in the tail


def calculate_historical_var(prices: pd.Series, level: float = 0.95, min_obs: int | None = None) -> MetricResult:
    s, miss = _clean(prices)
    r = s.pct_change(fill_method=None).dropna()
    mo = min_obs if min_obs is not None else _tail_min_obs(level)
    value = float(-np.quantile(r, 1.0 - level)) if len(r) else None
    method = {"method": "historical", "horizon": "1 period", "level": level, "quantile": "numpy linear interpolation",
              "sign": "positive = loss"}
    return _result(f"var_{int(level * 100)}", value, len(r), "fraction", s, method, min_obs=mo, n_missing=miss)


def calculate_expected_shortfall(prices: pd.Series, level: float = 0.95, min_obs: int | None = None) -> MetricResult:
    s, miss = _clean(prices)
    r = s.pct_change(fill_method=None).dropna()
    mo = min_obs if min_obs is not None else _tail_min_obs(level)
    value = None
    if len(r):
        q = np.quantile(r, 1.0 - level)
        value = float(-r[r <= q].mean())
    method = {"method": "historical", "formula": "-mean(r | r <= VaR quantile)", "level": level, "sign": "positive = loss"}
    return _result(f"expected_shortfall_{int(level * 100)}", value, len(r), "fraction", s, method, min_obs=mo, n_missing=miss)


def calculate_distribution_moments(prices: pd.Series, min_obs: int = MIN_OBS) -> MetricResult:
    s, miss = _clean(prices)
    r = np.log(s / s.shift(1)).dropna()
    detail = {"skewness": float(r.skew()) if len(r) > 2 else None, "excess_kurtosis": float(r.kurt()) if len(r) > 3 else None}
    return _result("distribution_moments", detail["skewness"], len(r), "ratio", s,
                   {"returns": "log", "estimators": "pandas bias-corrected skew/kurtosis"}, min_obs=min_obs, n_missing=miss, detail=detail)


def risk_report(prices: pd.Series, benchmark: pd.Series | None = None, rf_annual: float = 0.0,
                periods_per_year: int = TRADING_DAYS) -> dict[str, dict]:
    metrics = [
        calculate_cagr(prices),
        calculate_annualized_volatility(prices, periods_per_year),
        calculate_sharpe_ratio(prices, rf_annual, periods_per_year),
        calculate_sortino_ratio(prices, rf_annual, periods_per_year),
        calculate_downside_deviation(prices, rf_annual, periods_per_year),
        calculate_max_drawdown(prices),
        calculate_calmar_ratio(prices),
        calculate_historical_var(prices, 0.95),
        calculate_expected_shortfall(prices, 0.95),
        calculate_historical_var(prices, 0.99),
        calculate_expected_shortfall(prices, 0.99),
        calculate_distribution_moments(prices),
    ]
    if benchmark is not None:
        metrics += [
            calculate_beta(prices, benchmark),
            calculate_tracking_error(prices, benchmark, periods_per_year),
            calculate_information_ratio(prices, benchmark, periods_per_year),
            calculate_capture_ratios(prices, benchmark),
        ]
    return {m.name: m.to_dict() for m in metrics}


def drawdown_series(prices: pd.Series) -> pd.Series:
    s, _ = _clean(prices)
    return s / s.cummax() - 1.0


def align(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    joined = pd.concat([a, b], axis=1, join="inner").dropna()
    return joined.iloc[:, 0], joined.iloc[:, 1]
