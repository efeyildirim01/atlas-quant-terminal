"""Fund performance analytics on NAV series (TEFAS-style, one NAV per business day)."""

from __future__ import annotations

import pandas as pd

from app.analytics.metrics import align

# (label, DateOffset, annualise?)
PERIODS: list[tuple[str, pd.DateOffset, bool]] = [
    ("1W", pd.DateOffset(weeks=1), False),
    ("1M", pd.DateOffset(months=1), False),
    ("3M", pd.DateOffset(months=3), False),
    ("6M", pd.DateOffset(months=6), False),
    ("1Y", pd.DateOffset(years=1), False),
    ("3Y", pd.DateOffset(years=3), True),
    ("5Y", pd.DateOffset(years=5), True),
]


def _value_on_or_before(nav: pd.Series, when: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    s = nav.loc[:when]
    return (s.index[-1], float(s.iloc[-1])) if len(s) else None


def period_returns(nav: pd.Series) -> dict[str, dict | None]:
    """Trailing returns ending at the last NAV. Start = last NAV on/before the target date.

    Returns None for a period when history does not reach back far enough. A short history is
    never silently passed off as a full-period return.
    """
    nav = nav.dropna()
    end_date, end_val = nav.index[-1], float(nav.iloc[-1])
    out: dict[str, dict | None] = {}
    for label, offset, annualise in PERIODS:
        target = end_date - offset
        if nav.index[0] > target:
            out[label] = None
            continue
        start_date, start_val = _value_on_or_before(nav, target)  # type: ignore[misc]
        r = end_val / start_val - 1.0
        entry = {"start": start_date.date().isoformat(), "return": r}
        if annualise:
            years = (end_date - start_date).days / 365.25
            entry["annualized"] = (1.0 + r) ** (1.0 / years) - 1.0
        out[label] = entry
    ytd_anchor = _value_on_or_before(nav, pd.Timestamp(year=end_date.year - 1, month=12, day=31))
    out["YTD"] = (
        {"start": ytd_anchor[0].date().isoformat(), "return": end_val / ytd_anchor[1] - 1.0} if ytd_anchor else None
    )
    return out


def calendar_year_returns(nav: pd.Series) -> dict[int, float]:
    """Year-end to year-end returns. The first year is reported only when a prior year-end NAV exists."""
    year_end = nav.groupby(nav.index.year).last()
    return {int(y): float(r) for y, r in year_end.pct_change(fill_method=None).dropna().items()}


def rolling_returns(nav: pd.Series, window: int = 252) -> pd.Series:
    return nav / nav.shift(window) - 1.0


def rolling_consistency(nav: pd.Series, benchmark: pd.Series, window: int = 252) -> dict:
    """Share of rolling windows in which the fund beat the benchmark (overlapping windows; not independent)."""
    f, b = align(nav, benchmark)
    rf, rb = rolling_returns(f, window), rolling_returns(b, window)
    both = pd.concat([rf, rb], axis=1).dropna()
    if both.empty:
        return {"window": window, "n_windows": 0, "hit_rate": None}
    wins = (both.iloc[:, 0] > both.iloc[:, 1]).mean()
    return {
        "window": window,
        "n_windows": int(len(both)),
        "hit_rate": float(wins),
        "note": "Overlapping windows are highly autocorrelated; this describes the past, not skill.",
    }
