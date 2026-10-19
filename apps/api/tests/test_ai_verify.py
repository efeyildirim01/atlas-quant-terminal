"""Numeric-claim verifier: the safety net against invented figures."""

from app.ai.verify import verify_answer

EV = {
    "E1": {"data": {"metrics": {"cagr": {"value": 0.389698}, "max_drawdown": {"value": -0.3797}, "sharpe_ratio": {"value": 1.3766}},
                    "quote": {"close": 31.61, "avg_turnover_20d": 4727510646.79}}},
    "E2": {"data": {"funds": {"D-GLD": {"cagr": 0.331, "annualized_volatility": 0.1683}}}},
}


def statuses(answer):
    return [(c.text, c.status) for c in verify_answer(answer, EV).claims]


def test_verified_with_rounding_percent_and_sign():
    rep = verify_answer("D-EQF compounded at 38.97% a year with a drawdown of 38% [E1]. Its Sharpe was 1.38 [E1].", EV)
    assert [c.status for c in rep.claims] == ["verified", "verified", "verified"]
    assert rep.status == "verified" and rep.cited_ids == ["E1"]


def test_turkish_formats():
    rep = verify_answer("Yıllık getiri %39,0 oldu [E1]. Son kapanış 31,61 TL [E1]. Ortalama işlem hacmi 4,7 milyar TL [E1].", EV)
    assert [c.status for c in rep.claims] == ["verified", "verified", "verified"]


def test_mismatch_unsupported_and_uncited():
    assert statuses("CAGR was 45.2% [E1].") == [("45.2%", "mismatch")]
    assert statuses("The fund returned 77.7% last year.") == [("77.7%", "unsupported")]
    assert statuses("Gold compounded at 33.1% a year.") == [("33.1%", "uncited")]
    assert verify_answer("Gold compounded at 33.1% [E2].", EV).status == "verified"


def test_citation_must_be_to_the_right_evidence():
    # The value exists in E2 but the sentence cites E1 → mismatch, not verified.
    assert statuses("Volatility was 16.8% [E1].") == [("16.8%", "mismatch")]


def test_invalid_citation_ids_flagged():
    rep = verify_answer("Sharpe 1.38 [E1, E9].", EV)
    assert rep.invalid_citations == ["E9"] and rep.status == "unverified_claims"


def test_dates_years_counts_and_labels_skipped():
    rep = verify_answer("Between 2019-01-02 and 2026-10-15, across 3 funds and 2032 sessions, the 3Y window in 2024 [E2].", EV)
    assert rep.claims == []  # 4-digit integers in 1900–2100 read as years (documented trade-off)
    rep = verify_answer("Turnover averaged 4,727,510,646.79 TRY [E1] over 4500 sessions.", EV)
    assert [c.status for c in rep.claims] == ["verified", "mismatch"]  # same sentence cites E1, which has no 4500


def test_no_numbers():
    assert verify_answer("There is insufficient evidence to answer this.", EV).status == "no_numeric_claims"
