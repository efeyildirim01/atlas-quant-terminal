# Backtesting

`/backtest` (web) · `POST /api/v1/backtests`, `GET /api/v1/backtests/strategies` (API) · code in
`apps/api/app/analytics/backtest.py`.

A single-instrument, long/flat simulator for simple rule-based strategies on stored daily bars. It exists to
answer "would this rule have beaten holding the instrument, after costs?", not to find trading strategies.

## Timing (no look-ahead by construction)
| Step | Uses |
|---|---|
| Signal for day *t* | Closes up to and including *t* |
| Position change | **Open of day *t+1*** |
| Mark to market | Close of every day |

Day 0 can only produce a signal; the first possible trade is at the open of day 1. Indicators are computed on the
full stored history before the window is cut, so a window starting in 2022 has a valid 200-day average on day one.

Tested by perturbing every price after day *k* and asserting that equity and signals up to *k* are unchanged, for
every strategy (`test_no_look_ahead`). Two deliberate bugs (same-day execution, peeking at the next close) both
make the suite fail.

## Costs
Per side: commission on traded notional (`commission_bps`) and slippage as an adverse move of the execution price
(`slippage_bps`): buys fill at `open × (1 + s)`, sells at `open × (1 − s)`. Defaults: 10 bps + 5 bps.
`test_costs_only_ever_reduce_the_result` checks that higher costs never improve a result.

## Strategies
| Type | Long when | Parameters |
|---|---|---|
| `buy_and_hold` | always (enters at the first open) | none |
| `sma_cross` | SMA(fast) > SMA(slow) | fast 2–250, slow 3–400, fast < slow |
| `momentum` | close / close *n* days ago − 1 > 0 | lookback 5–504 |
| `rsi_reversion` | enter when RSI < entry, hold until RSI > exit | period 2–100, entry < exit |
| `donchian_breakout` | enter on a close above the prior *n*-day high, exit on a close below the prior *n*-day low | window 5–250 |

Strategies are typed parameter sets validated by the API; no user code is executed.

## Outputs
Equity curve, drawdown, every trade (signal date, execution date, price incl. slippage, units, commission),
round trips, and for both the strategy and buy-and-hold: total return, CAGR, volatility, Sharpe, Sortino, max
drawdown, Calmar, trades, win rate, average trade, holding period, time invested, annual turnover and costs paid.

**Benchmark:** buy-and-hold of the same instrument, run through the same engine with the same costs.

**In-sample vs out-of-sample:** with `out_of_sample_start`, metrics are also reported for the two periods. The
out-of-sample segment starts from the last in-sample close, so the segment returns chain exactly to the total
(tested). A rule whose edge exists only in-sample was most likely fitted to that period.

## Assumptions and limits
- Fully invested when long, fractional units, no leverage, no shorting; cash earns 0. With TRY rates in double
  digits, a strategy that is often flat is penalised against `rf` in Sharpe; set `rf` explicitly.
- Unadjusted prices (no corporate-action feed): splits and dividends are not reflected.
- Fills at the open with a fixed slippage; no volume or liquidity constraints, no partial fills, no gaps handling
  beyond using the actual open.
- One instrument at a time; no portfolio-level allocation.
- Results on fixture data are synthetic. **Past results do not predict future returns. Not investment advice.**
