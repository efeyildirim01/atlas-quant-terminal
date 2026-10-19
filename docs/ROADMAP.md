# Roadmap

"Done" means implemented, tested and demonstrated. It does not mean designed.

| Milestone | Scope | State |
|---|---|---|
| 1. Working foundation | Monorepo, apps, DB + migrations, auth, design system, navigation, CI, tests | **Done**, except that Docker Compose and CI are written but not executed here |
| 2. Verified data foundation | Instrument/source registry, storage, quality engine, data-health | **Done**, except the "real permitted source" criterion (blocked on EVDS key / licences) |
| 3. Equity research | Search, detail page, charts, technicals, risk | **Done** (fixture data). Fundamentals data model exists; no source |
| 4. TEFAS intelligence | Fund search/detail, NAV charts, performance, risk, comparison | **Done** (fixture data): detail, comparison UI (≤10, CSV export), rankings with eligibility rules. Holdings need a licensed source |
| 5. Professional tools | Screeners, portfolio analytics (TWR/MWR), reports + PDF | **Done**: portfolio analytics, screeners, research reports with PDF and reproducibility check |
| 6. AI copilot | Tool registry, orchestration, citations, numeric verification | **Done** (fake-client tested; live run needs an Anthropic key): 13 tools, cited evidence, deterministic numeric verifier, history |
| 7. Production hardening | Monitoring, Redis rate limit, security review, backups | **Done in code and tests**; Prometheus, Redis and PostgreSQL backups not executed here (no Docker). Open: pen test, Next 16, MFA (SECURITY_REVIEW.md) |

## Next iteration (proposed)
1. Live check of the AI copilot with a real Anthropic key; small eval set of research questions.
2. Corporate-action model → adjusted series (`adjusted_close`, `adjustment_version`) with reference tests.
3. EVDS live verification as soon as a key is available (`pytest -m live`).

Done in iteration 9: strategy backtester (`/backtest`, docs/financial-methodology/BACKTESTING.md); public GitHub repository with CI.

Done in iteration 8: production hardening: Redis rate limits, real client IP, login lockout, password change, body limit, security headers/CSP, /metrics + alert rules, readiness with schema check, verified backups/restore, FastAPI/Starlette security upgrade.

Done in iteration 7: AI research copilot (`/ai-research`, docs/financial-methodology/AI_COPILOT.md).

Done in iteration 4: portfolio transactions with ledger validation, FIFO P&L, TWR/MWR, benchmark comparison,
risk metrics, correlation and risk contribution (`/portfolio`).

Done in iteration 6: research reports (portfolio risk, fund comparison) as stored documents, PDF export, `verify`
reproducibility check; TWR fix for fresh capital; trade-price plausibility warning.

Done in iteration 5: equity and fund screeners (`/screener/*`): nested AND/OR conditions, point-in-time `as_of`,
missing-data diagnostics, presets, saved screens, server-side sort/paging, column choice, CSV export.

Done in iteration 3: fund comparison UI + CSV, fund rankings, cached `/market/overview` (279 ms → 4 ms warm).
