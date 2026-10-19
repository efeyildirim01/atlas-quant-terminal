"""Market-data quality engine.

Policy (docs/financial-methodology/DATA_QUALITY_POLICY.md):
- Hard check failure  → the row is stored as PARTIAL and excluded from analytics. Nothing is repaired.
- Soft check finding  → the row stays VALIDATED and carries a flag. The issue is reported.
- VERIFIED is reserved for licensed/official data that passes every hard check AND agrees with an
  independent second source (``check_source_conflict``). Single-source and fixture data top out at VALIDATED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.models.enums import QualityStatus

PRICE_COLS = ["open", "high", "low", "close", "volume"]


@dataclass
class Issue:
    severity: str  # info | warning | error
    code: str
    message: str
    count: int = 1
    examples: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    issues: list[Issue]
    row_status: pd.Series  # QualityStatus per row (index aligned with the input)
    row_flags: pd.Series  # list[str] per row

    @property
    def excluded(self) -> int:
        return int((self.row_status != QualityStatus.VALIDATED).sum())

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


def _ex(idx: pd.Index, k: int = 3) -> list[str]:
    return [pd.Timestamp(i).date().isoformat() if not isinstance(i, str) else i for i in list(idx[:k])]


class _Builder:
    def __init__(self, index: pd.Index):
        self.issues: list[Issue] = []
        self.hard = pd.Series(False, index=range(len(index)))
        self.flags: list[list[str]] = [[] for _ in range(len(index))]
        self.index = index

    def hard_fail(self, mask: np.ndarray, code: str, msg: str) -> None:
        if mask.any():
            self.hard |= mask
            for i in np.flatnonzero(mask):
                self.flags[i].append(code)
            self.issues.append(Issue("error", code, msg, int(mask.sum()), _ex(self.index[mask])))

    def soft(self, mask: np.ndarray, code: str, msg: str, severity: str = "warning") -> None:
        if mask.any():
            for i in np.flatnonzero(mask):
                self.flags[i].append(code)
            self.issues.append(Issue(severity, code, msg, int(mask.sum()), _ex(self.index[mask])))

    def report(self) -> QualityReport:
        status = np.where(self.hard.to_numpy(), QualityStatus.PARTIAL.value, QualityStatus.VALIDATED.value)
        return QualityReport(self.issues, pd.Series(status, index=self.index), pd.Series(self.flags, index=self.index, dtype=object))


def _gaps(index: pd.Index, max_gap_bdays: int) -> np.ndarray:
    out = np.zeros(len(index), dtype=bool)
    if len(index) > 1:
        d = index.values.astype("datetime64[D]")
        out[1:] = np.busday_count(d[:-1], d[1:]) > max_gap_bdays
    return out


def check_prices(
    df: pd.DataFrame,
    *,
    instrument_currency: str | None = None,
    row_currency: str | None = None,
    jump: float = 0.20,
    volume_spike: float = 10.0,
    max_gap_bdays: int = 5,
) -> QualityReport:
    missing = [c for c in PRICE_COLS if c not in df.columns]
    if missing:
        b = _Builder(df.index)
        b.hard_fail(np.ones(len(df), dtype=bool), "missing_columns", f"Missing columns: {missing}")
        return b.report()
    b = _Builder(df.index)
    if not df.index.is_monotonic_increasing:
        b.issues.append(Issue("info", "unsorted", "Input was not sorted by time; it was evaluated in time order"))
    b.hard_fail(df.index.duplicated(keep=False), "duplicate_timestamp", "Duplicate timestamps (all copies excluded)")
    b.hard_fail(df[PRICE_COLS].isna().any(axis=1).to_numpy(), "missing_values", "Missing OHLCV values")
    b.hard_fail((df[["open", "high", "low", "close"]] <= 0).any(axis=1).to_numpy(), "non_positive_price", "Non-positive price")
    bad_ohlc = (df["high"] < df[["open", "close", "low"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))
    b.hard_fail(bad_ohlc.to_numpy(), "ohlc_inconsistent", "High/low do not bound open/close")
    b.hard_fail((df["volume"] < 0).to_numpy(), "negative_volume", "Negative volume")
    if instrument_currency and row_currency and instrument_currency != row_currency:
        b.hard_fail(np.ones(len(df), dtype=bool), "currency_mismatch", f"Rows in {row_currency}, instrument in {instrument_currency}")

    ret = df["close"].pct_change(fill_method=None).abs()
    b.soft((ret > jump).to_numpy(), "large_move", f"One-day move > {jump:.0%}: possible unadjusted corporate action")
    trailing = df["volume"].shift(1).rolling(20, min_periods=20).median()  # past only
    b.soft((df["volume"] > volume_spike * trailing).to_numpy(), "volume_spike", f"Volume > {volume_spike:g}x trailing 20-session median", "info")
    b.soft(_gaps(df.index, max_gap_bdays), "gap", f"Gap > {max_gap_bdays} business days (holidays can explain some)")
    unchanged = df["close"].diff().eq(0) & df["volume"].eq(0)
    run = unchanged.groupby((~unchanged).cumsum()).transform("sum")
    b.soft((unchanged & (run >= 5)).to_numpy(), "stale_prices", "5+ consecutive unchanged closes with zero volume")
    return b.report()


def check_nav(df: pd.DataFrame, *, jump: float = 0.15, max_gap_bdays: int = 5) -> QualityReport:
    b = _Builder(df.index)
    if "nav" not in df.columns:
        b.hard_fail(np.ones(len(df), dtype=bool), "missing_columns", "Missing column: nav")
        return b.report()
    b.hard_fail(df.index.duplicated(keep=False), "duplicate_timestamp", "Duplicate valuation dates (all copies excluded)")
    b.hard_fail(df["nav"].isna().to_numpy(), "missing_values", "Missing NAV")
    b.hard_fail((df["nav"] <= 0).to_numpy(), "non_positive_nav", "Non-positive NAV")
    b.soft((df["nav"].pct_change(fill_method=None).abs() > jump).to_numpy(), "nav_jump", f"NAV change > {jump:.0%} in one day")
    b.soft(_gaps(df.index, max_gap_bdays), "gap", f"Gap > {max_gap_bdays} business days")
    if "publication_timestamp" not in df.columns or df["publication_timestamp"].isna().all():
        b.issues.append(Issue("warning", "missing_publication_timestamp", "Source does not provide publication timestamps; point-in-time use is limited"))
    return b.report()


def check_source_conflict(a: pd.Series, b: pd.Series, tolerance: float = 0.005) -> pd.Index:
    """Dates on which two sources' closes disagree by more than ``tolerance`` (relative)."""
    joined = pd.concat([a, b], axis=1, join="inner").dropna()
    rel = (joined.iloc[:, 0] - joined.iloc[:, 1]).abs() / joined.iloc[:, 1].abs()
    return joined.index[rel > tolerance]


def series_freshness(last: date | None, today: date, stale_after_bdays: int) -> tuple[str, int | None]:
    """Series-level freshness in business days (weekends only; exchange holidays not yet modelled)."""
    if last is None:
        return QualityStatus.UNAVAILABLE.value, None
    lag = int(np.busday_count(np.datetime64(last), np.datetime64(today)))
    return (QualityStatus.STALE.value if lag > stale_after_bdays else "FRESH"), lag
