"""Strategy backtests on stored daily bars. See docs/financial-methodology/BACKTESTING.md."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.analytics import backtest as bt
from app.analytics import metrics as m
from app.api.v1.common import RF_NOTE, envelope, settings_of
from app.auth.deps import get_db
from app.repositories.series import load_prices
from app.services.series_ops import arr, dates, resolve

router = APIRouter(prefix="/backtests", tags=["backtests"])
MAX_TRADES_RETURNED = 500
MIN_BARS = 60


class BuyAndHold(BaseModel):
    type: Literal["buy_and_hold"]


class SmaCross(BaseModel):
    type: Literal["sma_cross"]
    fast: int = Field(20, ge=2, le=250)
    slow: int = Field(50, ge=3, le=400)

    @model_validator(mode="after")
    def _order(self):
        if self.fast >= self.slow:
            raise ValueError("fast must be shorter than slow")
        return self


class RsiReversion(BaseModel):
    type: Literal["rsi_reversion"]
    period: int = Field(14, ge=2, le=100)
    entry: float = Field(30, gt=0, lt=100)
    exit: float = Field(55, gt=0, lt=100)

    @model_validator(mode="after")
    def _order(self):
        if self.entry >= self.exit:
            raise ValueError("entry must be below exit")
        return self


class Momentum(BaseModel):
    type: Literal["momentum"]
    lookback: int = Field(126, ge=5, le=504)


class Donchian(BaseModel):
    type: Literal["donchian_breakout"]
    window: int = Field(55, ge=5, le=250)


Strategy = Annotated[BuyAndHold | SmaCross | RsiReversion | Momentum | Donchian, Field(discriminator="type")]


class BacktestIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    strategy: Strategy
    start: date | None = None
    end: date | None = None
    out_of_sample_start: date | None = Field(None, description="Report metrics separately before and after this date")
    initial_capital: float = Field(100_000, gt=0, le=1e12)
    commission_bps: float = Field(10, ge=0, le=500)
    slippage_bps: float = Field(5, ge=0, le=500)
    rf: float = Field(0.0, ge=-0.5, le=2.0)


def _segment(eq: pd.Series, pos: pd.Series, rf: float) -> dict | None:
    if len(eq) < 2:
        return None
    r = bt.BacktestResult(eq, pos, pos)
    s = bt.summarize(r, rf)
    return {k: s[k] for k in ("total_return", "cagr", "volatility", "sharpe", "max_drawdown", "exposure")} | {"days": len(eq) - 1}


@router.post("")
def run(body: BacktestIn, request: Request, db: Session = Depends(get_db)):
    inst = resolve(db, body.symbol, ("equity", "index"))
    bundle = load_prices(db, inst)
    full = bundle.frame
    if body.end:
        full = full.loc[: pd.Timestamp(body.end)]
    params = body.strategy.model_dump(exclude={"type"})
    # Indicators are computed on the full history (warmed up), then the window is cut: day-one signals are real.
    signal = bt.signal_for(body.strategy.type, full["close"], params) if len(full) else pd.Series(dtype=float)
    bars = full.loc[pd.Timestamp(body.start):] if body.start else full
    if len(bars) < MIN_BARS:
        raise HTTPException(422, f"At least {MIN_BARS} daily bars are needed in the window; got {len(bars)}.")
    costs = bt.Costs(body.commission_bps, body.slippage_bps)
    res = bt.run_backtest(bars, body.strategy.type, params, costs, body.initial_capital, signal=signal.loc[bars.index[0]:])
    bench = bt.run_backtest(bars, "buy_and_hold", {}, costs, body.initial_capital)
    segments = None
    if body.out_of_sample_start:
        cut = pd.Timestamp(body.out_of_sample_start)
        if not (bars.index[0] < cut < bars.index[-1]):
            raise HTTPException(422, "out_of_sample_start must fall inside the backtest window")
        # The out-of-sample segment starts from the last in-sample close, so the two segment returns chain exactly
        # to the total: (1 + in) × (1 + out) = 1 + total.
        last_in = bars.index[bars.index.searchsorted(cut) - 1]
        segments = {}
        for name, sl in (("in_sample", slice(None, last_in)), ("out_of_sample", slice(last_in, None))):
            segments[name] = {"strategy": _segment(res.equity.loc[sl], res.position.loc[sl], body.rf),
                              "buy_and_hold": _segment(bench.equity.loc[sl], bench.position.loc[sl], body.rf)}
    warnings = []
    if len(res.trades) < 10:
        warnings.append(f"Only {len(res.trades)} trades: too few for the statistics to mean much.")
    if inst.instrument_type == "index":
        warnings.append("Backtesting an index assumes it is directly investable at these prices.")
    trades = res.trades[:MAX_TRADES_RETURNED]
    data = {
        "symbol": inst.symbol,
        "strategy": body.strategy.model_dump(),
        "window": {"start": bars.index[0].date().isoformat(), "end": bars.index[-1].date().isoformat(), "bars": len(bars)},
        "dates": dates(bars.index),
        "equity": arr(res.equity, 2),
        "benchmark_equity": arr(bench.equity, 2),
        "drawdown": arr(m.drawdown_series(res.equity), 6),
        "position": arr(res.position, 0),
        "metrics": {"strategy": bt.summarize(res, body.rf), "buy_and_hold": bt.summarize(bench, body.rf)},
        "segments": segments,
        "trades": [t.__dict__ for t in trades],
        "trades_truncated": len(res.trades) > MAX_TRADES_RETURNED,
        "round_trips": bt.round_trips(res.trades)[:MAX_TRADES_RETURNED],
        "warnings": warnings,
        "disclaimer": "Historical simulation on stored data. Past results do not predict future returns. Not investment advice.",
    }
    return envelope(db, settings_of(request), data, [bundle], units={"price": inst.currency, "equity": inst.currency},
                    methodology={
                        "timing": "signal on the close of day t, executed at the open of day t+1; marked to market at each close",
                        "costs": f"{body.commission_bps} bps commission + {body.slippage_bps} bps slippage per side",
                        "position": "long or flat, fully invested when long; fractional units; cash earns 0",
                        "warm_up": "indicators computed on the full stored history before the window starts",
                        "benchmark": "buy-and-hold of the same instrument through the same engine and costs",
                        "prices": "unadjusted: no corporate-action feed, so splits and dividends are not reflected",
                        "rf": RF_NOTE,
                    })


@router.get("/strategies")
def strategies() -> list[dict]:
    """Strategy catalogue with parameter bounds, for building forms."""
    out = []
    for model in (BuyAndHold, SmaCross, RsiReversion, Momentum, Donchian):
        schema = model.model_json_schema()
        props = {k: v for k, v in schema["properties"].items() if k != "type"}
        out.append({"type": model.model_fields["type"].annotation.__args__[0],
                    "params": {k: {"default": v.get("default"), "min": v.get("minimum", v.get("exclusiveMinimum")),
                                   "max": v.get("maximum", v.get("exclusiveMaximum"))} for k, v in props.items()}})
    return out
