"""Backtester: hand-computed fills and costs, no look-ahead for every strategy, cost monotonicity, API contract."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics import backtest as bt

DEFAULT_PARAMS = {"buy_and_hold": {}, "sma_cross": {"fast": 5, "slow": 20}, "rsi_reversion": {"period": 14, "entry": 35, "exit": 55},
                  "momentum": {"lookback": 20}, "donchian_breakout": {"window": 20}}


def bars_from(close, opens=None) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=len(close))
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({"open": close if opens is None else np.asarray(opens, dtype=float), "close": close}, index=idx)


def random_bars(n=400, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, n)))
    opens = close * np.exp(rng.normal(0, 0.005, n))
    return bars_from(close, opens)


def test_hand_computed_fills_and_costs():
    # Signal long after day 0's close, flat after day 2's close → buy at day 1 open, sell at day 3 open.
    bars = bars_from(close=[100, 110, 121, 130, 140], opens=[100, 105, 115, 125, 135])
    signal = pd.Series([1, 1, 0, 0, 0], index=bars.index, dtype=float)
    costs = bt.Costs(commission_bps=10, slippage_bps=20)
    res = bt.run_backtest(bars, "custom", {}, costs, capital=1000, signal=signal)

    buy_px = 105 * 1.002
    units = 1000 / (buy_px * 1.001)
    sell_px = 125 * 0.998
    cash = units * sell_px * (1 - 0.001)
    assert [t.side for t in res.trades] == ["buy", "sell"]
    assert res.trades[0].signal_date == "2024-01-01" and res.trades[0].date == "2024-01-02"
    assert res.trades[0].price == pytest.approx(buy_px) and res.trades[1].price == pytest.approx(sell_px)
    assert res.equity.iloc[0] == 1000  # nothing can happen before the first signal
    assert res.equity.iloc[1] == pytest.approx(units * 110)
    assert res.equity.iloc[2] == pytest.approx(units * 121)
    assert res.equity.iloc[3] == pytest.approx(cash) == res.equity.iloc[4]
    assert res.position.tolist() == [0, 1, 1, 0, 0]
    trip = bt.round_trips(res.trades)[0]
    assert trip["return"] == pytest.approx(cash / 1000 - 1)


@pytest.mark.parametrize("strategy", bt.STRATEGIES)
def test_no_look_ahead(strategy):
    """Changing every price after day k must not change anything up to and including day k."""
    bars = random_bars()
    params = DEFAULT_PARAMS[strategy]
    base = bt.run_backtest(bars, strategy, params)
    for k in (60, 150, 300):
        shocked = bars.copy()
        shocked.iloc[k + 1:] *= np.linspace(0.5, 2.0, len(bars) - k - 1)[:, None]
        alt = bt.run_backtest(shocked, strategy, params)
        pd.testing.assert_series_equal(base.equity.iloc[: k + 1], alt.equity.iloc[: k + 1])
        pd.testing.assert_series_equal(base.signal.iloc[: k + 1], alt.signal.iloc[: k + 1])


@pytest.mark.parametrize("strategy", ["sma_cross", "momentum", "donchian_breakout"])
def test_costs_only_ever_reduce_the_result(strategy):
    bars = random_bars(seed=11)
    finals = [bt.run_backtest(bars, strategy, DEFAULT_PARAMS[strategy], bt.Costs(bps, bps)).equity.iloc[-1] for bps in (0, 5, 25, 100)]
    assert finals == sorted(finals, reverse=True) and finals[0] > finals[-1]


def test_buy_and_hold_matches_closed_form():
    bars = random_bars(seed=5)
    costs = bt.Costs(10, 5)
    res = bt.run_backtest(bars, "buy_and_hold", {}, costs, capital=50_000)
    units = 50_000 / (bars["open"].iloc[1] * 1.0005 * 1.001)
    assert res.equity.iloc[-1] == pytest.approx(units * bars["close"].iloc[-1])
    assert len(res.trades) == 1 and bt.summarize(res)["exposure"] == pytest.approx((len(bars) - 1) / len(bars))


def test_signal_warm_up_and_state_machines():
    close = pd.Series(np.r_[np.linspace(100, 50, 40), np.linspace(50, 120, 60)], index=pd.bdate_range("2024-01-01", periods=100))
    sma = bt.signal_for("sma_cross", close, {"fast": 5, "slow": 20})
    assert (sma.iloc[:19] == 0).all()  # no signal until the slow average exists
    rsi = bt.signal_for("rsi_reversion", close, {"period": 14, "entry": 30, "exit": 55})
    first_long = rsi.idxmax()
    assert close.loc[:first_long].iloc[-1] < close.iloc[0]  # enters during the sell-off, not before
    assert rsi.iloc[-1] == 0  # exits once the rebound pushes RSI above 55
    don = bt.signal_for("donchian_breakout", close, {"window": 20})
    assert don.iloc[-1] == 1 and don.iloc[:45].sum() == 0  # long only after breaking the prior 20-day high


def test_summary_metrics_are_consistent():
    res = bt.run_backtest(random_bars(seed=8), "sma_cross", {"fast": 10, "slow": 40})
    s = bt.summarize(res, rf=0.0)
    assert s["total_return"] == pytest.approx(res.equity.iloc[-1] / res.equity.iloc[0] - 1)
    assert s["trades"] == len(res.trades) and s["round_trips"] == len(bt.round_trips(res.trades))
    assert 0 <= s["exposure"] <= 1 and s["max_drawdown"] <= 0 and s["total_costs"] > 0


# ── API ───────────────────────────────────────────────────────────────────────────────────────────
def test_backtest_endpoint(client):
    body = {"symbol": "D-BNK1", "strategy": {"type": "sma_cross", "fast": 20, "slow": 50}, "start": "2023-01-02",
            "out_of_sample_start": "2025-06-02", "commission_bps": 10, "slippage_bps": 5, "rf": 0.35}
    r = client.post("/api/v1/backtests", json=body)
    assert r.status_code == 200, r.text
    env = r.json()
    d = env["data"]
    assert env["is_fixture"] and "open of day t+1" in env["methodology"]["timing"]
    assert d["window"]["start"] >= "2023-01-02" and len(d["dates"]) == len(d["equity"]) == len(d["benchmark_equity"]) == d["window"]["bars"]
    assert d["equity"][0] == d["benchmark_equity"][0] == 100000
    assert set(d["metrics"]) == {"strategy", "buy_and_hold"} and d["metrics"]["buy_and_hold"]["trades"] == 1
    assert set(d["segments"]) == {"in_sample", "out_of_sample"} and d["segments"]["out_of_sample"]["strategy"]["days"] > 0
    for who in ("strategy", "buy_and_hold"):  # segments chain exactly to the total
        seg = {k: v[who] for k, v in d["segments"].items()}
        chained = (1 + seg["in_sample"]["total_return"]) * (1 + seg["out_of_sample"]["total_return"]) - 1
        assert chained == pytest.approx(d["metrics"][who]["total_return"], rel=1e-9)
        assert seg["in_sample"]["days"] + seg["out_of_sample"]["days"] == d["window"]["bars"] - 1
    assert all(t["date"] > t["signal_date"] for t in d["trades"])
    assert "Not investment advice" in d["disclaimer"]


@pytest.mark.parametrize("strategy,detail", [
    ({"type": "sma_cross", "fast": 50, "slow": 20}, "fast must be shorter"),
    ({"type": "rsi_reversion", "period": 14, "entry": 60, "exit": 40}, "entry must be below"),
    ({"type": "magic"}, "type"),
])
def test_backtest_validation(client, strategy, detail):
    r = client.post("/api/v1/backtests", json={"symbol": "D-BNK1", "strategy": strategy})
    assert r.status_code == 422 and detail in r.text


def test_backtest_window_errors_and_catalogue(client):
    short = client.post("/api/v1/backtests", json={"symbol": "D-BNK1", "strategy": {"type": "buy_and_hold"}, "start": "2026-09-01"})
    assert short.status_code == 422 and "daily bars" in short.json()["detail"]
    oos = client.post("/api/v1/backtests", json={"symbol": "D-BNK1", "strategy": {"type": "buy_and_hold"}, "out_of_sample_start": "1999-01-01"})
    assert oos.status_code == 422
    assert client.post("/api/v1/backtests", json={"symbol": "NOPE", "strategy": {"type": "buy_and_hold"}}).status_code == 404
    cat = {s["type"]: s["params"] for s in client.get("/api/v1/backtests/strategies").json()}
    assert set(cat) == set(bt.STRATEGIES) and cat["sma_cross"]["fast"] == {"default": 20, "min": 2, "max": 250}
