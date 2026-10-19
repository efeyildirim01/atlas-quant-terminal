# Project status

Detailed milestone status and known issues. The overview is in the [README](../README.md).

### Status (2026-10-16, iteration 8)

#### Milestone 1: working foundation
| Item | State |
|---|---|
| Monorepo, frontend, backend, config | Done |
| Database models + Alembic migration (17 tables) | Done. Verified on SQLite (upgrade/downgrade/no drift). PostgreSQL DDL rendered offline; **not run against a live PostgreSQL** |
| Docker Compose | Written. **Not executed** (no Docker on this machine) |
| Auth (sessions, CSRF, RBAC, isolation, rate limit, audit) | Done, tested |
| Design system + navigation (EN/TR) | Done. TR covers shell/navigation; page bodies are mostly English |
| CI pipeline | Written. **Not executed** (no GitHub remote) |

#### Milestone 2: verified data foundation
| Item | State |
|---|---|
| Instrument registry, provider interfaces, source registry + capability matrix | Done |
| Price & NAV storage (decimal, UTC, point-in-time columns) | Done |
| Quality engine (row-level statuses, issues, runs) + `/system/data-health` dashboard | Done |
| "At least one permitted real source" | **Not met.** EVDS adapter implemented and mock-tested, but no API key. BIST/KAP/TEFAS need licences |

#### Vertical slice: search → stored history → chart → metrics → source metadata
Done and exercised end to end in a browser and by Playwright.

#### Tests (all executed on 2026-10-16)
| Suite | Result |
|---|---|
| `apps/api` pytest (reference values, Hypothesis properties, no-look-ahead, quality, ingestion, auth, API, migrations, rankings, portfolio accounting & isolation, screener, reports, AI copilot & verifier, hardening, backtester, backups) | **211 passed** |
| `apps/web` Vitest + Testing Library | **24 passed** (mutation-checked: 2 deliberate bugs were caught) |
| `apps/web` TypeScript strict | clean |
| `apps/web` Playwright (Edge, against dev servers) | **10 passed** (incl. backtesting, the spec's three workflows, screener, reports/PDF and the AI assistant setup state) |

#### Known issues
- No real market data (licensing). Fundamentals, valuation, holdings, macro, disclosures and inflation/FX-adjusted
  returns return explicit `UNAVAILABLE`.
- Prices are unadjusted (no corporate-action feed).
- Exchange holidays are not modelled in freshness or market-status.
- Redis rate limiting, Prometheus alerts and PostgreSQL backups are written and unit-tested but not run against real Redis/Prometheus/PostgreSQL (no Docker here).
- Open security items: independent pen test, Next.js 16 upgrade, nonce CSP, MFA (compliance/SECURITY_REVIEW.md).
- `/market/overview` reads every series per request (~300 ms on SQLite). It needs a cached aggregate.
- shadcn/ui CLI was not run. Primitives are hand-written in the shadcn idiom.
- The AI copilot needs `ANTHROPIC_API_KEY` on the API process and has not been run live here; report narrative is rule-based. Portfolio analytics ignore taxes and FX. Screener fundamentals fields are unavailable (no licensed source).

### Next milestone
All seven milestones are implemented. Next: real data sources (EVDS key, BIST/TEFAS licences), a live AI check with an Anthropic key, and the open security items.
Iteration 8 delivered production hardening (operations/RUNBOOK.md, docs/compliance/SECURITY_REVIEW.md). Iteration 7 delivered the AI research copilot (financial-methodology/AI_COPILOT.md). Iteration 6 completed Milestone 5 with research reports and PDF export (financial-methodology/REPORTS.md). Iteration 5 delivered the equity/fund screeners (see docs/financial-methodology/SCREENER.md). Iteration 4 delivered portfolio analytics (`/portfolio`): validated transactions, FIFO P&L, TWR/MWR, benchmark
comparison, risk metrics, correlation and risk contribution. See docs/financial-methodology/PORTFOLIO.md. In parallel (non-engineering):
EVDS key → first real source; BIST EOD vendor licence; TEFAS/Takasbank permission request.
See [docs/ROADMAP.md](ROADMAP.md).
