# Financial Methodology: Portfolio Accounting

Implementation: `apps/api/app/analytics/portfolio.py` (pure functions) and `app/services/portfolio_service.py`.

## Transactions
| Type | Cash effect | External flow? | Required fields |
|---|---|---|---|
| deposit | + amount | yes (+) | amount |
| withdrawal | − amount | yes (−) | amount |
| buy | − (qty × price + commission) | no | symbol, quantity, price, commission ≥ 0 |
| sell | + (qty × price − commission) | no | symbol, quantity, price, commission ≥ 0 |
| dividend | + amount | no (investment income) | amount (symbol optional) |
| fee | − amount | no (investment cost) | amount |

Prices are entered by the user and are never inferred from market data. Transaction dates cannot be in the future.

## Ledger rules (enforced on every add **and** delete by replaying the whole ledger)
- The first transaction must be a deposit.
- No short selling: a sell can never exceed the quantity held on that date.
- No margin: buys, withdrawals and fees can never take cash below zero.
- Same-day order: deposits and dividends → sells → buys → withdrawals and fees.

## Cost basis and P&L
FIFO lots. Buy commission is capitalised into the lot's unit cost. Sell commission is deducted from proceeds.
Realised P&L = proceeds − FIFO cost of the units sold. Unrealised P&L = market value − remaining FIFO cost.
Identity checked in tests: **total P&L = value − net contributions = realised + unrealised + dividends − fees.**

## Valuation
Each business day (plus any transaction date) is valued at close: cash + Σ quantity × last stored close (or NAV)
on or before that day. Marks older than 5 business days are flagged. Days with a holding that has no price yet are
not valued, and a warning is returned.

## Returns
- **TWR** (time-weighted): r_t = (V_t − F_t) / V_{t−1} − 1, where F_t is the day's external flow (end-of-day
  convention). When nothing was invested the day before (the first deposit, or after a full withdrawal),
  r_t = V_t / F_t − 1, so fresh capital is measured from the amount deposited. A first-day gain from buying below the
  close therefore counts (fixed in iteration 6; previously that first-day return was dropped). Sub-period returns are chained geometrically. It is neutral to the size and timing of deposits.
  Annualised only when the period is ≥ 1 year.
- **MWR** (money-weighted): XIRR of investor cash flows (deposits −, withdrawals +, ending value +), Actual/365,
  solved by bisection. Returns `null` when there is no sign change. It reflects the investor's timing.

## Plausibility warnings
A trade price more than 10% away from the stored close on the trade date produces a non-blocking warning
(usually a typo or an unadjusted corporate action).

## Risk
Risk metrics (`metrics.risk_report`) run on the TWR index, with an optional benchmark (default D-IDX).
Correlation and contribution to variance use the last 252 common daily returns of current holdings:
RC_i = w_i (Σw)_i / wᵀΣw, with weights on total portfolio value. Cash has zero variance and contributes nothing.

## Not modelled
Withholding tax (stopaj), FX for non-TRY instruments, corporate actions (prices are unadjusted), settlement lag
(the settlement date is stored but valuation uses the trade date).
