# API v1

Interactive docs: `http://127.0.0.1:8000/api/docs`. Machine-readable contract:
`packages/shared-types/openapi.json` (regenerate with `scripts/export_openapi.py`).

## Envelope
Financial endpoints return:
```json
{
  "data": {},
  "provenance": [{"instrument": "D-BNK1", "dataset": "eod_bars",
                  "source": {"source_id": "fixture", "name": "...", "data_mode": "fixture", "attribution": "...", "licence_note": "..."},
                  "as_of": "2026-10-15", "last_ingested_at": "...", "freshness": "FRESH", "lag_business_days": 1,
                  "delay": "end-of-day (synthetic fixture)"}],
  "quality": {"status": "VALIDATED", "rows_used": 2032, "rows_excluded": 0, "open_issues": []},
  "methodology": {}, "units": {"price": "TRY"}, "is_fixture": true, "request_id": "..."
}
```
Every response carries an `X-Request-ID` header. Pass one in to correlate with your own logs.

## Endpoints (implemented)
| Method | Path | Notes |
|---|---|---|
| POST | /auth/register, /auth/login, /auth/logout | Session cookie (HttpOnly, SameSite=Lax) + CSRF cookie. Login: 429 after 5 failures per email for 15 min |
| POST | /auth/password | `current_password`, `new_password` → revokes all sessions, returns a new one for this browser |
| POST | /auth/logout-all | Revokes every session of the user |
| GET | /auth/me | 401 when anonymous |
| GET/POST | /portfolios | Owner-scoped; CSRF header required for POST |
| GET/DELETE | /portfolios/{id} | 404 for other users' portfolios |
| GET/POST | /portfolios/{id}/transactions | POST replays the whole ledger first; rule violations → 422 with the reason |
| DELETE | /portfolios/{id}/transactions/{tid} | Rejected (422) if the remaining ledger would become invalid |
| GET | /portfolios/{id}/analytics | `benchmark` (default D-IDX), `rf`; summary, holdings (FIFO), allocation, TWR/MWR, drawdown, risk metrics, correlation, risk contribution |
| GET | /instruments | Paginated (`page`, `page_size` ≤ 200) |
| GET | /search?q= | Grouped, highlighted, typo-tolerant |
| GET | /equities/{symbol} | Profile + quote summary. `?exchange=` when a symbol is ambiguous (409) |
| GET | /equities/{symbol}/prices | `window` (1M..5Y, YTD, MAX), `interval` (1d, 1w, 1mo); > 5000 points → 422 |
| GET | /equities/{symbol}/technicals | Indicator series + daily-basis research readings + signal placeholder |
| GET | /equities/{symbol}/risk | `window`, `rf`, `benchmark`; metrics, liquidity, distribution, drawdown |
| GET | /equities/{symbol}/fundamentals, /valuation | `UNAVAILABLE` payload naming the required source |
| GET | /funds | Paginated, `category` filter |
| GET | /funds/{code}, /nav, /performance, /risk | Benchmark aligned on common dates |
| POST | /funds/compare | 2–10 codes; common overlapping window |
| GET | /funds/rankings | `horizon` (1Y/3Y/5Y), `metric`, `category`, `rf`. One common window; stale, short-history, undefined and (for Sharpe/Sortino) < 1% volatility funds are excluded with reasons |
| GET | /screener/{equities\|funds}/fields, /presets | Field catalog (incl. unavailable fields with reasons) and preset screens |
| POST | /screener/{equities\|funds} | Filter tree, sort, columns, `as_of`, paging → matches, `snapshot_id`, missing-data counts |
| POST | /screener/{equities\|funds}/export | All matches as CSV with provenance metadata lines |
| GET/POST | /screener/saved | Owner-scoped saved screens (validated before saving) |
| DELETE | /screener/saved/{id} | 404 for other users' screens |
| POST | /reports/generate | `portfolio_risk` (portfolio_id, benchmark, rf) or `fund_comparison` (2–10 codes, rf) → stored report |
| GET | /reports, /reports/{id} | Owner-scoped list and full document |
| GET | /reports/{id}/pdf | PDF rendered from the stored document |
| POST | /reports/{id}/verify | Regenerate from stored inputs and compare every fact → `reproduced` or `differs` (with list) |
| DELETE | /reports/{id} | Owner only |
| GET | /research/status | Whether credentials are present, model, effort, tool list |
| POST | /research/query | Signed-in. `question`, optional `history_ids` (≤5) → answer, evidence `E#`, verification report, usage. 503 if not configured, 429 per-user limit |
| GET | /research/history, /research/history/{id} | Owner-scoped stored queries |
| GET | /market/overview | Index, breadth, sectors, movers; macro/disclosures `UNAVAILABLE` |
| GET | /system/sources, /system/data-health, /system/market-status | Source registry & capability matrix, quality dashboard, session clock |

## Not yet implemented (spec endpoints)
None of the Milestone 1–6 endpoints are outstanding.

## Errors
`401` unauthenticated · `403` CSRF/role · `404` unknown · `409` ambiguous symbol / duplicate account · `413` body over 1 MB ·
`422` validation · `429` rate limit (`Retry-After`) · `502` upstream provider error · `503` source unavailable.

## Operational endpoints (outside /api/v1)
`GET /health` (liveness) · `GET /ready` (database, schema revision, rate-limit backend; 503 when not ready) ·
`GET /metrics` (Prometheus text; Bearer `ATLAS_METRICS_TOKEN`). See docs/operations/RUNBOOK.md.
