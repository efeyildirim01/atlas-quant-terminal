# Financial Methodology: Screener

Implementation: `apps/api/app/analytics/screen.py` (evaluation) and `app/services/screener_service.py` (fields, snapshots, presets).

## Snapshots (point-in-time)
A screen runs on a snapshot: one row per instrument, every field computed from stored, quality-filtered data up to
`as_of` (default: latest). Passing a past `as_of` re-computes every field on data that existed up to that date, so
a historical screen does not see later prices. Snapshots are cached per (data version, universe, as_of) and
invalidated by any new ingestion run. Every response carries a `snapshot_id`, a hash of query + data version +
as_of. The same id means the same inputs.

## Filter language
Nested groups (`and` / `or`), at most 3 levels and 20 conditions.
| Field type | Operators |
|---|---|
| number | gt, gte, lt, lte, between (inclusive), eq, neq |
| category | eq, neq, in, not_in |
| boolean | is_true, is_false |

**Missing values never pass a condition**, including complement operators. The response reports, per condition, how
many instruments were excluded only because their value was missing. There is no NOT operator: negating
"missing → false" would let missing values pass.

Units follow the API: fractions are decimals (0.05 = 5%). The UI edits them as percentages and converts.
Sorting is server-side, with missing values last in both directions and ties broken by symbol.

## Field definitions
Equities: returns over 1/21/63/252 sessions, relative strength vs the index over the same dates, volatility
(log returns, √252), drawdown and Sharpe (rf = 0) over the last 252 sessions, 20-session average turnover, RSI/ADX
(Wilder), close vs SMA 50/200.
Funds: the same calendar NAV-to-NAV definitions as the fund pages (verified by a regression test), 3Y risk only with
≥ 3 years of history, Sharpe omitted below 1% volatility, excess return vs benchmark on common dates.

Valuation, profitability, growth and leverage fields, and fund holdings exposure, are listed with `available: false`
and a reason. They cannot be filtered until a licensed fundamentals/holdings source exists.

## Saved screens and export
Saved screens are private to the user (others get 404). A definition is validated against the field catalog before
it is stored. CSV export returns **all** matches (not one page), with `#` metadata lines: snapshot id, as-of,
source, fixture flag, match count and units.
