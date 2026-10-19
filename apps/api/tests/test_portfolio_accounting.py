"""Portfolio accounting: hand-derived reference cases, ledger rules and invariants."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.analytics.portfolio import (
    LedgerError, Txn, holdings_table, investor_flows, replay, risk_decomposition, twr_index, xirr,
)

D = [date(2024, 1, d) for d in (1, 2, 3, 4)]  # Mon..Thu
X = pd.Series([100.0, 110.0, 99.0, 108.9], index=pd.to_datetime(D))


def test_twr_with_external_flow_hand_computed():
    # d1: deposit 1000, buy 10 @100 → V1 = 1000
    # d2: V2 = 10·110 = 1100                               r2 = 1100/1000 − 1 = +0.10
    # d3: deposit 1000 → V3 = 10·99 + 1000 = 1990, F3=1000  r3 = (1990 − 1000)/1100 − 1 = −0.10
    # d4: V4 = 10·108.9 + 1000 = 2089                       r4 = 2089/1990 − 1 = +0.0497487
    # TWR = 1.1 · 0.9 · 1.0497487 − 1 = 0.0392513
    txns = [Txn(1, D[0], "deposit", amount=1000), Txn(2, D[0], "buy", "X", 10, 100), Txn(3, D[2], "deposit", amount=1000)]
    res = replay(txns, {"X": X}, D[3])
    assert res.daily["value"].tolist() == pytest.approx([1000, 1100, 1990, 2089])
    idx = twr_index(res.daily)
    assert idx.iloc[-1] - 1 == pytest.approx(1.1 * 0.9 * (2089 / 1990) - 1)
    # Simple return on contributions would be misleading here: (2089 − 2000)/2000 = 4.45% ≠ TWR.


def test_first_day_gain_from_buying_below_close_is_in_twr():
    # d1: deposit 1000, buy 10 @ 90 while X closes at 100 → V1 = 100 cash + 1000 = 1100 → r1 = 1100/1000 − 1 = +10%
    # d2: V2 = 100 + 10·110 = 1200 → r2 = 1200/1100 − 1.  TWR = 1200/1000 − 1 = +20% (no further flows).
    txns = [Txn(1, D[0], "deposit", amount=1000), Txn(2, D[0], "buy", "X", 10, 90)]
    res = replay(txns, {"X": X}, D[1])
    idx = twr_index(res.daily)
    assert idx.iloc[0] == pytest.approx(1.10)
    assert idx.iloc[-1] - 1 == pytest.approx(0.20)
    # With no intermediate flows, TWR must equal the simple return on the single deposit.
    assert idx.iloc[-1] - 1 == pytest.approx(res.daily["value"].iloc[-1] / 1000 - 1)


def test_trade_price_far_from_close_is_warned_not_blocked():
    res = replay([Txn(1, D[0], "deposit", amount=1000), Txn(2, D[0], "buy", "X", 1, 50)], {"X": X}, D[1])
    assert any("50% away from the stored close" in w for w in res.warnings)
    ok = replay([Txn(1, D[0], "deposit", amount=1000), Txn(2, D[0], "buy", "X", 1, 101)], {"X": X}, D[1])
    assert not any("away from" in w for w in ok.warnings)


def test_twr_restarts_after_full_withdrawal():
    txns = [Txn(1, D[0], "deposit", amount=1000), Txn(2, D[1], "withdrawal", amount=1000), Txn(3, D[2], "deposit", amount=500)]
    res = replay(txns, {"X": X}, D[3])
    assert twr_index(res.daily).iloc[-1] == pytest.approx(1.0)  # cash only: no investment return at any point


def test_fifo_realized_pnl_with_commissions():
    # Lot A: 10 @100 + 10 commission → unit cost 101. Lot B: 10 @120 → unit cost 120.
    # Sell 15 @130, commission 5 → proceeds 1945; FIFO cost = 10·101 + 5·120 = 1610; realised = 335.
    prices = {"X": pd.Series(130.0, index=pd.bdate_range("2024-01-01", "2024-01-10"))}
    txns = [Txn(1, D[0], "deposit", amount=5000), Txn(2, D[0], "buy", "X", 10, 100, commission=10),
            Txn(3, D[1], "buy", "X", 10, 120), Txn(4, D[2], "sell", "X", 15, 130, commission=5)]
    res = replay(txns, prices, date(2024, 1, 10))
    assert res.realized[0]["cost_basis"] == pytest.approx(1610)
    assert res.realized[0]["realized_pnl"] == pytest.approx(335)
    assert res.positions == {"X": pytest.approx(5)}
    h = holdings_table(res, prices, date(2024, 1, 10))[0]
    assert h["avg_cost"] == pytest.approx(120) and h["unrealized_pnl"] == pytest.approx(5 * (130 - 120))
    assert res.totals["commissions"] == pytest.approx(15)
    assert res.cash == pytest.approx(5000 - 1010 - 1200 + 1945)


def test_same_day_order_lets_sell_fund_a_buy():
    prices = {"X": X, "Y": X * 2}
    txns = [Txn(1, D[0], "deposit", amount=1000), Txn(2, D[0], "buy", "X", 10, 100),
            Txn(4, D[1], "buy", "Y", 5, 220), Txn(3, D[1], "sell", "X", 10, 110)]  # sell processed before buy
    res = replay(txns, prices, D[1])
    assert res.cash == pytest.approx(1100 - 1100)


@pytest.mark.parametrize(
    "txns, message",
    [
        ([Txn(1, D[0], "buy", "X", 1, 100)], "first transaction must be a deposit"),
        ([Txn(1, D[0], "deposit", amount=100), Txn(2, D[0], "buy", "X", 2, 100)], "exceeds cash"),
        ([Txn(1, D[0], "deposit", amount=1000), Txn(2, D[1], "sell", "X", 1, 100)], "no shorting"),
        ([Txn(1, D[0], "deposit", amount=100), Txn(2, D[1], "withdrawal", amount=200)], "exceeds cash"),
        ([Txn(1, D[0], "deposit", amount=100), Txn(2, D[1], "buy", "X", 1, 0)], "price > 0"),
        ([Txn(1, D[0], "deposit", amount=100), Txn(2, D[1], "buy", "ZZZ", 1, 1)], "no stored price history"),
        ([Txn(1, D[0], "deposit", amount=-5)], "amount > 0"),
        ([Txn(1, D[0], "transfer", amount=5)], "unknown transaction type"),
    ],
)
def test_ledger_rules(txns, message):
    with pytest.raises(LedgerError, match=message) as exc:
        replay(txns, {"X": X}, D[3])
    assert exc.value.index is not None or "first" not in message


def test_xirr_reference_cases():
    # 1000 in, 1100 out exactly 365 days later → 10% (Actual/365).
    assert xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 1100)]) == pytest.approx(0.10, abs=1e-8)
    flows = [(date(2023, 1, 1), -1000), (date(2023, 7, 2), -1000), (date(2024, 1, 1), 2200)]
    r = xirr(flows)
    npv = sum(cf / (1 + r) ** ((d - flows[0][0]).days / 365) for d, cf in flows)
    assert abs(npv) < 1e-6 and 0.10 < r < 0.20
    assert xirr([(date(2023, 1, 1), 1000)]) is None  # no sign change → undefined, not 0


def test_investor_flows_signs():
    txns = [Txn(1, D[0], "deposit", amount=1000), Txn(2, D[2], "withdrawal", amount=100), Txn(3, D[1], "dividend", amount=5)]
    assert investor_flows(txns, D[3], 950) == [(D[0], -1000), (D[2], 100), (D[3], 950)]  # dividends are internal


def test_stale_marks_and_unpriced_days_are_flagged():
    sparse = pd.Series([100.0], index=pd.to_datetime([date(2024, 1, 1)]))
    res = replay([Txn(1, D[0], "deposit", amount=1000), Txn(2, D[0], "buy", "X", 1, 100)], {"X": sparse}, date(2024, 1, 15))
    assert res.daily["stale_marks"].iloc[-1] == 1
    assert any("older than" in w for w in res.warnings)


def test_risk_contributions_sum_to_one():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2023-01-02", periods=300)
    a = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 300)), index=idx)
    b = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.02, 300)), index=idx)
    out = risk_decomposition({"A": 0.4, "B": 0.4}, {"A": a, "B": b})  # 20% cash
    assert sum(r["contribution"] for r in out["risk_contribution"]) == pytest.approx(1.0)
    rc = {r["symbol"]: r["contribution"] for r in out["risk_contribution"]}
    assert rc["B"] > rc["A"]  # same weight, higher volatility → larger share of risk
    assert out["correlation"][0][0] == pytest.approx(1.0)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.floats(min_value=-0.08, max_value=0.08, allow_nan=False), min_size=5, max_size=60),
       st.lists(st.floats(min_value=100, max_value=10_000), min_size=1, max_size=4))
def test_twr_equals_asset_return_when_fully_invested(rets, deposits):
    """Invariant: if every deposit is immediately invested at the close (no commission), TWR = the asset's return,
    no matter how large or when the deposits are."""
    idx = pd.bdate_range("2024-01-01", periods=len(rets) + 1)
    px = pd.Series(100 * np.cumprod(np.concatenate([[1.0], 1 + np.array(rets)])), index=idx)
    txns, tid = [], 0
    for k, amount in enumerate(deposits):
        day = idx[min(k * 3, len(idx) - 1)]
        price = float(px.loc[day])
        tid += 1
        txns.append(Txn(tid, day.date(), "deposit", amount=amount))
        tid += 1
        txns.append(Txn(tid, day.date(), "buy", "X", amount / price, price))
    res = replay(txns, {"X": px}, idx[-1].date())
    assert twr_index(res.daily).iloc[-1] == pytest.approx(px.iloc[-1] / px.iloc[0], rel=1e-9)
