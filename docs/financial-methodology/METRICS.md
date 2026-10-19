# Financial Methodology: Metrics

Implementation: `apps/api/app/analytics/metrics.py` (risk/return), `technical.py` (indicators), `funds.py`.
Every API metric is a `MetricResult` with `value`, `status` (`ok | insufficient_data | undefined`), `n_obs`,
`unit`, `start`, `end` and a `methodology` dict.

## Conventions
| Topic | Convention |
|---|---|
| Missing data | Dropped, never filled. The dropped count is reported in `methodology.dropped_missing`. |
| Returns | Simple `P_t/P_{t-1}−1` for Sharpe, Sortino, VaR, ES, beta and capture. Log returns for volatility, skewness and kurtosis. |
| Annualisation | 252 periods/yr for daily bars and NAVs, 52 weekly, 12 monthly. Volatility ×√k. CAGR uses calendar days / 365.25. |
| Risk-free rate | Explicit annual decimal. Per period: `(1+rf)^(1/k) − 1`. The API echoes the rate used. |
| Zero denominators | `value = null`, `status = "undefined"`. Never 0. |
| Minimum samples | 20 returns by default. VaR/ES need ≥ 5 tail observations (95% → 100, 99% → 500). |
| Relative metrics | Computed on the **inner join** of observation dates. No stale-price returns are created by forward fills. |
| Timestamps | Daily bars are stamped at 18:00 Europe/Istanbul (15:00 UTC). UTC+3 fixed, no DST since 2016. |
| Prices | **Unadjusted**: no licensed corporate-action feed yet. A 20% one-day move is flagged `large_move`. |

## Formulas
| Function | Definition |
|---|---|
| `calculate_sharpe_ratio` | mean(r − rf_p) / std(r − rf_p, ddof=1) × √k |
| `calculate_downside_deviation` | √(mean(min(r − rf_p, 0)²)) × √k, denominator = all observations |
| `calculate_sortino_ratio` | mean(r − rf_p) × k / downside deviation |
| `calculate_max_drawdown` | min(P_t / max_{u≤t} P_u − 1), with peak, trough, recovery dates |
| `calculate_calmar_ratio` | CAGR / \|max drawdown\| over the same sample |
| `calculate_beta` | cov(r, r_b) / var(r_b), plus correlation. Undefined when the benchmark return std is ≤ 1e-10 (numerically flat) |
| `calculate_tracking_error` | std(r − r_b, ddof=1) × √k |
| `calculate_information_ratio` | mean(r − r_b) × k / tracking error |
| `calculate_historical_var` | −quantile(r, 1−level), numpy linear interpolation, 1 period |
| `calculate_expected_shortfall` | −mean(r \| r ≤ quantile(r, 1−level)) |
| `calculate_capture_ratios` | mean(r \| r_b>0) / mean(r_b \| r_b>0), and the downside analogue. Arithmetic means. |
| `calculate_rolling_returns` | P_t / P_{t−w} − 1 |
| `calculate_rolling_correlation` | Pearson correlation of simple returns over a trailing window |

## Indicators
Wilder smoothing (α = 1/n) for RSI, ATR and ADX. EMA uses α = 2/(n+1). Both are seeded with the SMA of
the first n values, so warm-up values are null and are never back-filled. Bollinger uses the population
standard deviation. Indicator series are computed on full history and then trimmed to the requested
window. **Research readings always use daily bars** (`research_basis: "daily bars"`) whatever the chart interval.

## Verification
- Reference tests with hand-derived expected values (`tests/test_metrics_reference.py`).
- Property-based tests (Hypothesis): drawdown ∈ (−1, 0], scale invariance, ES ≥ VaR, β of a k-levered path = k,
  sign(Sharpe) = sign(mean excess), downside deviation ≤ RMS (`tests/test_metrics_properties.py`).
- No-look-ahead tests: appending or shocking future bars must not change past indicator values (`tests/test_no_lookahead.py`).
