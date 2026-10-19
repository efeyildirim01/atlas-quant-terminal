from datetime import date

import numpy as np
import pandas as pd

from app.models.enums import QualityStatus
from app.services.data_quality import check_nav, check_prices, check_source_conflict, series_freshness


def frame(rows, dates):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=pd.to_datetime(dates))


def codes(rep):
    return {i.code for i in rep.issues}


def test_clean_fixture_bars_are_validated(bars):
    rep = check_prices(bars)
    assert not rep.has_errors and rep.excluded == 0
    assert set(rep.row_status) == {QualityStatus.VALIDATED.value}


def test_hard_failures_mark_rows_partial_without_repair():
    df = frame(
        [[10, 9, 8, 9, 100],  # high < open → inconsistent
         [10, 11, 9, 10, -5],  # negative volume
         [10, 11, 9, np.nan, 100],  # missing close
         [0, 1, 0, 1, 100],  # non-positive
         [10, 11, 9, 10, 100]],
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"],
    )
    original = df.copy()
    rep = check_prices(df)
    assert {"ohlc_inconsistent", "negative_volume", "missing_values", "non_positive_price"} <= codes(rep)
    assert rep.row_status.tolist()[:4] == [QualityStatus.PARTIAL.value] * 4
    assert rep.row_status.iloc[4] == QualityStatus.VALIDATED.value
    pd.testing.assert_frame_equal(df, original)  # never repaired in place


def test_duplicates_all_copies_excluded():
    df = frame([[10, 11, 9, 10, 1]] * 3, ["2024-01-02", "2024-01-02", "2024-01-03"])
    rep = check_prices(df)
    assert rep.row_status.tolist() == ["PARTIAL", "PARTIAL", "VALIDATED"]


def test_soft_findings_keep_rows_usable():
    n = 30
    idx = pd.bdate_range("2024-01-01", periods=n)
    close = np.full(n, 10.0)
    close[25] = 14.0  # +40% jump
    vol = np.full(n, 1000.0)
    vol[27] = 50_000  # 50x spike
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": vol}, index=idx)
    rep = check_prices(df)
    assert {"large_move", "volume_spike"} <= codes(rep)
    assert rep.excluded == 0
    assert "large_move" in rep.row_flags.iloc[25]


def test_gap_and_currency_mismatch():
    df = frame([[10, 11, 9, 10, 1], [10, 11, 9, 10, 1]], ["2024-01-02", "2024-02-15"])
    assert "gap" in codes(check_prices(df))
    rep = check_prices(df, instrument_currency="TRY", row_currency="USD")
    assert "currency_mismatch" in codes(rep) and rep.excluded == 2


def test_nav_checks():
    df = pd.DataFrame({"nav": [1.0, 1.01, -1.0, 1.5]}, index=pd.bdate_range("2024-01-01", periods=4))
    rep = check_nav(df)
    assert {"non_positive_nav", "nav_jump", "missing_publication_timestamp"} <= codes(rep)
    assert rep.row_status.iloc[2] == "PARTIAL"


def test_source_conflict_detection():
    idx = pd.bdate_range("2024-01-01", periods=5)
    a = pd.Series([10, 10, 10, 10, 10.0], index=idx)
    b = pd.Series([10, 10.01, 10.2, 10, 10.0], index=idx)
    assert list(check_source_conflict(a, b, 0.005)) == [idx[2]]


def test_freshness_policy():
    assert series_freshness(date(2026, 10, 15), date(2026, 10, 16), 3) == ("FRESH", 1)
    assert series_freshness(date(2026, 10, 1), date(2026, 10, 16), 3)[0] == "STALE"
    assert series_freshness(None, date(2026, 10, 16), 3) == ("UNAVAILABLE", None)
    # Weekend does not count: Fri → Mon is 1 business day
    assert series_freshness(date(2026, 10, 16), date(2026, 10, 19), 3) == ("FRESH", 1)
