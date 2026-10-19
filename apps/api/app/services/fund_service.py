"""Fund research computations on stored NAV series."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics import funds as fa
from app.analytics import metrics as m
from app.services.series_ops import arr, dates, num

MAX_COMPARE = 10


def profile(inst) -> dict:
    f = inst.fund
    return {
        "fund_code": f.fund_code, "fund_name": f.fund_name, "management_company": f.management_company,
        "category": f.category, "benchmark": f.benchmark, "currency": f.currency,
        "inception_date": f.inception_date.isoformat() if f.inception_date else None,
        "management_fee": num(f.management_fee), "risk_classification": f.risk_classification, "status": f.status,
        "holdings": None, "holdings_note": "Unavailable: portfolio disclosures need a licensed KAP/TEFAS source",
    }


def snapshot(nav: pd.DataFrame) -> dict:
    if nav.empty:
        return {"available": False}
    s = nav["nav"]
    pr = fa.period_returns(s)
    three = s.loc[s.index[-1] - pd.DateOffset(years=3):]
    has_3y = s.index[0] <= s.index[-1] - pd.DateOffset(years=3)
    vol = m.calculate_annualized_volatility(three)
    return {
        "available": True, "as_of": s.index[-1].date().isoformat(), "nav": num(s.iloc[-1]),
        "total_assets": num(nav["total_assets"].iloc[-1]), "investor_count": num(nav["investor_count"].iloc[-1]),
        "ret_1m": pr["1M"]["return"] if pr["1M"] else None, "ret_ytd": pr["YTD"]["return"] if pr["YTD"] else None,
        "ret_1y": pr["1Y"]["return"] if pr["1Y"] else None, "ret_3y_ann": pr["3Y"]["annualized"] if pr["3Y"] else None,
        # Risk over a full 3Y window only; shorter histories are not ranked on 3Y metrics.
        "vol_3y": vol.value if has_3y else None,
        "max_dd_3y": m.calculate_max_drawdown(three).value if has_3y else None,
        "history_start": s.index[0].date().isoformat(),
    }


def performance(nav: pd.Series, bench: pd.Series | None) -> dict:
    out = {
        "dates": dates(nav.index), "nav": arr(nav, 6), "rebased": arr(nav / nav.iloc[0] * 100, 4),
        "drawdown": arr(m.drawdown_series(nav), 6), "rolling_1y": arr(m.calculate_rolling_returns(nav, 252), 6),
        "period_returns": fa.period_returns(nav), "calendar_returns": fa.calendar_year_returns(nav),
        "since_inception": {"start": nav.index[0].date().isoformat(), "return": num(nav.iloc[-1] / nav.iloc[0] - 1),
                            "annualized": m.calculate_cagr(nav).value},
    }
    if bench is not None:
        f_al, b_al = m.align(nav, bench)
        out["benchmark"] = {"dates": dates(b_al.index), "rebased": arr(b_al / b_al.iloc[0] * 100, 4),
                            "period_returns": fa.period_returns(b_al),
                            "consistency_1y": fa.rolling_consistency(nav, bench, 252),
                            "alignment": "common valuation dates only"}
    return out


def compare(navs: dict[str, pd.Series]) -> dict:
    """Comparison on the *common* date range so no fund is judged over a period it did not exist."""
    start = max(s.index[0] for s in navs.values())
    end = min(s.index[-1] for s in navs.values())
    if start >= end:
        return {"available": False, "reason": "No overlapping history"}
    joined = pd.concat({k: v.loc[start:end] for k, v in navs.items()}, axis=1, join="inner").dropna()
    rows = {}
    for code in joined.columns:
        s = joined[code]
        rep = m.risk_report(s)
        rows[code] = {"total_return": num(s.iloc[-1] / s.iloc[0] - 1), **{k: rep[k]["value"] for k in
                      ("cagr", "annualized_volatility", "sharpe_ratio", "sortino_ratio", "max_drawdown", "calmar_ratio")}}
    return {
        "available": True, "start": joined.index[0].date().isoformat(), "end": joined.index[-1].date().isoformat(),
        "n_obs": int(len(joined)), "dates": dates(joined.index),
        "rebased": {c: arr(joined[c] / joined[c].iloc[0] * 100, 4) for c in joined.columns},
        "drawdown": {c: arr(m.drawdown_series(joined[c]), 6) for c in joined.columns},
        "metrics": rows,
    }


# ── Rankings ──────────────────────────────────────────────────────────────────────────────────────
HORIZONS = {"1Y": 1, "3Y": 3, "5Y": 5}
# metric → (higher_is_better, unit). max_drawdown is negative, so "higher" means shallower.
RANK_METRICS: dict[str, tuple[bool, str]] = {
    "total_return": (True, "fraction"),
    "cagr": (True, "annualized_fraction"),
    "sharpe_ratio": (True, "ratio"),
    "sortino_ratio": (True, "ratio"),
    "calmar_ratio": (True, "ratio"),
    "annualized_volatility": (False, "annualized_fraction"),
    "max_drawdown": (True, "fraction"),
    "management_fee": (False, "fraction"),
}
STALE_TOLERANCE_BDAYS = 5
# Below this annualised volatility, risk-adjusted ratios are dominated by a near-zero denominator (e.g. money
# market funds) and would top any ranking without saying anything about skill.
MIN_VOL_FOR_RATIOS = 0.01
VOL_RATIOS = {"sharpe_ratio", "sortino_ratio"}


def _competition_ranks(values: list[float], higher_is_better: bool) -> list[int]:
    """Standard competition ranking (1, 2, 2, 4): ties share a rank, nothing is broken arbitrarily."""
    return [1 + sum(1 for w in values if (w > v if higher_is_better else w < v)) for v in values]


def rank_funds(navs: dict[str, pd.Series], fees: dict[str, float | None], horizon: str, metric: str,
               rf_annual: float = 0.0) -> dict:
    """Rank funds on one metric over ONE common window.

    Eligibility (each failure is reported, never silently dropped):
    1. Not stale: the last NAV is within STALE_TOLERANCE_BDAYS business days of the most recent NAV in the set.
    2. Full history: the fund has a NAV on or before the window start (no partial-period comparisons).
    3. The metric is defined for the fund over the window (e.g. Sharpe is undefined at zero volatility).
    4. For Sharpe/Sortino: annualised volatility ≥ MIN_VOL_FOR_RATIOS, otherwise the ratio is not meaningful.
    """
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {list(HORIZONS)}")
    if metric not in RANK_METRICS:
        raise ValueError(f"metric must be one of {list(RANK_METRICS)}")
    higher, unit = RANK_METRICS[metric]
    navs = {k: v.dropna() for k, v in navs.items() if len(v.dropna())}
    excluded: list[dict] = []
    if not navs:
        return {"available": False, "reason": "No NAV history", "rows": [], "excluded": []}

    latest = max(s.index[-1] for s in navs.values())
    fresh = {}
    for code, s in navs.items():
        lag = int(np.busday_count(s.index[-1].date(), latest.date()))
        if lag > STALE_TOLERANCE_BDAYS:
            excluded.append({"symbol": code, "reason": f"stale: last NAV {s.index[-1].date()} ({lag} business days behind)"})
        else:
            fresh[code] = s
    if not fresh:
        return {"available": False, "reason": "All funds stale", "rows": [], "excluded": excluded}

    window_end = min(s.index[-1] for s in fresh.values())
    window_start = window_end - pd.DateOffset(years=HORIZONS[horizon])
    rows = []
    for code, s in fresh.items():
        if s.index[0] > window_start:
            excluded.append({"symbol": code, "reason": f"insufficient history: starts {s.index[0].date()}, window needs ≤ {window_start.date()}"})
            continue
        start_obs = s.loc[:window_start].index[-1]
        w = s.loc[start_obs:window_end]
        if metric == "management_fee":
            value, status, n = fees.get(code), "ok" if fees.get(code) is not None else "undefined", len(w)
        elif metric == "total_return":
            value, status, n = float(w.iloc[-1] / w.iloc[0] - 1), "ok", len(w) - 1
        else:
            report = m.risk_report(w, rf_annual=rf_annual)
            vol = report["annualized_volatility"]["value"]
            if metric in VOL_RATIOS and vol is not None and vol < MIN_VOL_FOR_RATIOS:
                excluded.append({"symbol": code, "reason": f"volatility {vol:.2%} < {MIN_VOL_FOR_RATIOS:.0%}: {metric} not meaningful"})
                continue
            r = report[metric]
            value, status, n = r["value"], r["status"], r["n_obs"]
        if value is None:
            excluded.append({"symbol": code, "reason": f"{metric} {status} over the window"})
            continue
        rows.append({"symbol": code, "value": float(value), "n_obs": n})
    ranks = _competition_ranks([r["value"] for r in rows], higher)
    for r, k in zip(rows, ranks):
        r["rank"] = k
    rows.sort(key=lambda r: (r["rank"], r["symbol"]))
    return {
        "available": bool(rows), "horizon": horizon, "metric": metric, "unit": unit,
        "direction": "higher is better" if higher else "lower is better",
        "window": {"start": window_start.date().isoformat(), "end": window_end.date().isoformat()},
        "rf_annual": rf_annual if metric in ("sharpe_ratio", "sortino_ratio") else None,
        "n_candidates": len(navs), "n_ranked": len(rows), "rows": rows,
        "excluded": sorted(excluded, key=lambda e: e["symbol"]),
    }
