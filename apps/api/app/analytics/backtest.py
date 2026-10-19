"""Single-instrument, long/flat strategy backtester.

Timing (no look-ahead by construction): the signal for day t uses closes up to and including t; the position
changes at the OPEN of day t+1; the portfolio is marked at each close. Costs are charged per side: commission on
traded notional and slippage as an adverse move of the execution price. Units are fractional (notional backtest).
Strategies are typed parameter sets, never user code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.analytics import metrics as m
from app.analytics import technical as ta

STRATEGIES = ("buy_and_hold", "sma_cross", "rsi_reversion", "momentum", "donchian_breakout")


@dataclass(frozen=True)
class Costs:
    commission_bps: float = 10.0  # per side, on traded notional
    slippage_bps: float = 5.0  # per side, adverse price move

    @property
    def commission(self) -> float:
        return self.commission_bps / 1e4

    @property
    def slippage(self) -> float:
        return self.slippage_bps / 1e4


@dataclass
class Trade:
    date: str
    side: str  # buy | sell
    signal_date: str
    price: float  # executed price incl. slippage
    reference_price: float  # open before slippage
    units: float
    notional: float
    commission: float


@dataclass
class BacktestResult:
    equity: pd.Series
    position: pd.Series  # 1 = invested at that close, 0 = flat
    signal: pd.Series
    trades: list[Trade] = field(default_factory=list)


# ── signals: 1 = want to be long after this close, 0 = flat. Only data up to each date is used. ──
def signal_for(strategy: str, close: pd.Series, params: dict) -> pd.Series:
    if strategy == "buy_and_hold":
        return pd.Series(1.0, index=close.index)
    if strategy == "sma_cross":
        fast, slow = ta.sma(close, params["fast"]), ta.sma(close, params["slow"])
        return (fast > slow).astype(float).where(slow.notna(), 0.0)
    if strategy == "momentum":
        past = close.shift(params["lookback"])
        return (close / past - 1 > 0).astype(float).where(past.notna(), 0.0)
    if strategy == "rsi_reversion":
        r = ta.rsi(close, params["period"]).to_numpy()
        out, held = np.zeros(len(r)), 0.0
        for i, v in enumerate(r):  # stateful: enter below `entry`, hold until above `exit`
            if not math.isnan(v):
                if held == 0.0 and v < params["entry"]:
                    held = 1.0
                elif held == 1.0 and v > params["exit"]:
                    held = 0.0
            out[i] = held
        return pd.Series(out, index=close.index)
    if strategy == "donchian_breakout":
        n = params["window"]
        upper, lower = close.shift(1).rolling(n).max(), close.shift(1).rolling(n).min()  # prior n days, excluding today
        out, held = np.zeros(len(close)), 0.0
        for i, (c, u, lo) in enumerate(zip(close.to_numpy(), upper.to_numpy(), lower.to_numpy())):
            if not math.isnan(u):
                if held == 0.0 and c > u:
                    held = 1.0
                elif held == 1.0 and c < lo:
                    held = 0.0
            out[i] = held
        return pd.Series(out, index=close.index)
    raise ValueError(f"unknown strategy {strategy}")


def run_backtest(bars: pd.DataFrame, strategy: str, params: dict, costs: Costs = Costs(), capital: float = 100_000.0,
                 signal: pd.Series | None = None) -> BacktestResult:
    """`bars` needs open and close columns on a DatetimeIndex. `signal` may be passed precomputed (computed on the
    full history so indicators are warmed up, then trimmed to the backtest window)."""
    bars = bars[["open", "close"]].dropna()
    close, opens = bars["close"], bars["open"]
    sig = (signal if signal is not None else signal_for(strategy, close, params)).reindex(bars.index).fillna(0.0)
    n = len(bars)
    cash, units = capital, 0.0
    equity, position = np.empty(n), np.zeros(n)
    trades: list[Trade] = []
    idx = bars.index
    c, s = costs.commission, costs.slippage
    for i in range(n):
        if i > 0:
            want, have = sig.iloc[i - 1], 1.0 if units > 0 else 0.0
            if want != have:
                ref = float(opens.iloc[i])
                if want == 1.0:
                    px = ref * (1 + s)
                    units = cash / (px * (1 + c))
                    notional = units * px
                    fee = notional * c
                    cash -= notional + fee
                    side = "buy"
                else:
                    px = ref * (1 - s)
                    notional = units * px
                    fee = notional * c
                    cash += notional - fee
                    side = "sell"
                    trade_units, units = units, 0.0
                trades.append(Trade(date=idx[i].date().isoformat(), side=side, signal_date=idx[i - 1].date().isoformat(),
                                    price=px, reference_price=ref, units=units if side == "buy" else trade_units,
                                    notional=notional, commission=fee))
        equity[i] = cash + units * float(close.iloc[i])
        position[i] = 1.0 if units > 0 else 0.0
    return BacktestResult(pd.Series(equity, index=idx), pd.Series(position, index=idx), sig, trades)


def round_trips(trades: list[Trade]) -> list[dict]:
    """Closed buy→sell pairs with net P&L including both sides' costs."""
    out, entry = [], None
    for t in trades:
        if t.side == "buy":
            entry = t
        elif entry is not None:
            cost_in = entry.notional + entry.commission
            proceeds = t.notional - t.commission
            out.append({"entry": entry.date, "exit": t.date, "return": proceeds / cost_in - 1,
                        "days": (pd.Timestamp(t.date) - pd.Timestamp(entry.date)).days})
            entry = None
    return out


def summarize(res: BacktestResult, rf: float = 0.0) -> dict:
    eq = res.equity
    metric = lambda r: r.value if r.status == "ok" else None  # noqa: E731
    trips = round_trips(res.trades)
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    traded = sum(t.notional for t in res.trades)
    return {
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1),
        "cagr": metric(m.calculate_cagr(eq)),
        "volatility": metric(m.calculate_annualized_volatility(eq)),
        "sharpe": metric(m.calculate_sharpe_ratio(eq, rf)),
        "sortino": metric(m.calculate_sortino_ratio(eq, rf)),
        "max_drawdown": metric(m.calculate_max_drawdown(eq)),
        "calmar": metric(m.calculate_calmar_ratio(eq)),
        "trades": len(res.trades),
        "round_trips": len(trips),
        "win_rate": (sum(1 for t in trips if t["return"] > 0) / len(trips)) if trips else None,
        "avg_trade_return": float(np.mean([t["return"] for t in trips])) if trips else None,
        "avg_holding_days": float(np.mean([t["days"] for t in trips])) if trips else None,
        "exposure": float(res.position.mean()),
        "annual_turnover": float(traded / eq.mean() / years),
        "total_costs": float(sum(t.commission for t in res.trades)
                             + sum(abs(t.price - t.reference_price) * t.units for t in res.trades)),
        "final_equity": float(eq.iloc[-1]),
    }
