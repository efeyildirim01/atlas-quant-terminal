> **Phase 1 document (superseded in part).** The repository layout, database and API paths have since moved to
> `apps/api`, `apps/web` and `/api/v1`. See [TECHNICAL_ASSESSMENT.md](TECHNICAL_ASSESSMENT.md) and [../api/API.md](../api/API.md).
> The requirements critique and risk register below remain current.

# ATLAS QUANT TERMINAL — Architecture (Phase 1)

## 1. Critical evaluation of the requirements

The brief describes several years of work for a funded team. It is internally consistent and puts
rigour first. Taken literally, though, it has four structural problems that shape this architecture:

1. **The data is the product, and most of it is licensed.** BIST prices, KAP disclosures and TEFAS
   NAVs are not openly licensed for automated redistribution (see `DATA_PROVIDERS.md`). Every
   analytical feature downstream depends on contracts that do not exist yet. *Decision:* build
   everything against a provider interface. Ship a clearly labelled **demo** provider and a
   **user-supplied CSV** provider. Real feeds plug in as soon as licences are signed.
2. **"Institutional-grade ML signals" invite self-deception.** On ~500 BIST names with daily data,
   most ML return forecasts will not beat simple baselines after costs. *Decision:* the ML engine
   (Phase 5) starts from an evaluation harness: purged walk-forward CV, embargo, cost model and
   baseline comparison. Models come after. A signal only reaches the UI with calibrated
   out-of-sample evidence. Until then the signal panel shows **"Insufficient evidence"**.
3. **Regulatory perimeter.** Under SPK rules, individualised buy/sell recommendations and portfolio
   management are licensed activities (investment advisory). *Decision:* v1 is a research and
   analytics tool. It has no order routing. Signal language describes setups ("bullish setup"),
   never instructions. A legal opinion is required before any personalised output ships.
4. **Inflation and FX distort Turkish financials.** TAS 29 / IAS 29 hyperinflation accounting
   (applied from FY2023) breaks naive growth and margin time series. *Decision:* the fundamentals
   schema stores the reporting basis (`inflation_adjusted` flag, currency, restatement version) and
   keeps point-in-time copies. Analyses must never mix bases silently.

### Key risks

| Risk | Type | Mitigation |
|---|---|---|
| No licensed BIST/TEFAS/KAP feed | Data/legal | Provider gate, CSV import, vendor RFP (roadmap Phase 2b) |
| Look-ahead / restated data in research | Research | Point-in-time tables (`known_at`), no-look-ahead unit tests on every indicator |
| Survivorship bias | Research | `instrument.delisted_on`, universe-at-date queries |
| Corporate-action errors (bedelsiz/bedelli splits are frequent in BIST) | Data | Raw prices + adjustment factors stored separately; adjusted series derived, never stored as truth |
| LLM fabricating numbers | AI | LLM only calls deterministic tools; verification agent checks every number against tool output IDs |
| Investment-advice classification | Regulatory | Research-only positioning, disclaimers, no personalisation in v1, legal review |
| KVKK (personal data) | Regulatory | Data minimisation, TR/EU hosting decision, DPA with vendors, deletion workflows |

## 2. System architecture

```
                ┌──────────────────────── Next.js terminal (TS, Tailwind) ───────────────────────┐
                │  Market · Equities · Funds · Charting · Quant · Copilot · Lab · Portfolio ...   │
                └───────────────▲─────────────────────────────────────────────────────────────────┘
                                │ JSON envelopes {data, provenance, validation}
                ┌───────────────┴──────────────── FastAPI (API layer) ────────────────────────────┐
                │ auth · RBAC · rate limit · audit log · licence enforcement · OpenAPI contracts   │
                └──┬───────────────┬───────────────┬───────────────┬──────────────┬───────────────┘
                   │               │               │               │              │
            Analytics engine   Risk engine    Strategy/backtest   ML engine    AI orchestration
            (technical,        (VaR, CVaR,    (event-driven,      (walk-fwd,   (tool-calling LLM,
             returns, funds)    stress)        cost models)        calibration)  agents, verifier)
                   └───────────────┴───────┬───────┴───────────────┴──────────────┘
                                           │ typed repositories (point-in-time aware)
                ┌──────────────────────────┴──────────────────────────────────────────────────────┐
                │ PostgreSQL + TimescaleDB (bars, NAV, macro)  · Redis (cache, queues) · S3 (raw)   │
                └──────────────────────────▲──────────────────────────────────────────────────────┘
                                           │ validated, versioned writes
                ┌──────────────────────────┴──────────── Ingestion workers ───────────────────────┐
                │ provider adapters → raw landing (S3) → validation → normalise → upsert + lineage │
                └─────────────────────────────────────────────────────────────────────────────────┘
```

**Layering rules**

- Analytics functions are **pure** (pandas/numpy in, pandas/numpy out). They do no I/O and have no clock.
  That makes them unit-testable and reproducible.
- Providers do I/O and return `(DataFrame, Provenance)`. Validation runs on every load and returns
  structured issues. It never silently drops rows.
- The API composes providers, validation and analytics. Every response carries provenance.
- The AI layer has **read-only tool access** to the API. It cannot produce a number that did not
  come from a tool call.

### Current Phase 2 slice vs target

| Concern | Target | Implemented now |
|---|---|---|
| Storage | Postgres/Timescale (`schema.sql`) | Providers read directly; in-process TTL cache |
| Workers | Celery/Arq + scheduler | Not yet |
| Auth | OIDC + RBAC | **Not yet** — API runs unauthenticated on localhost only |
| Providers | Vendor feeds | Demo, CSV, EVDS (key-gated), licence gates |

## 3. Repository structure

```
atlas-quant-terminal/
├── docs/                  architecture, data feasibility, schema, security, roadmap
├── backend/
│   ├── atlas/
│   │   ├── domain/        Pydantic models (Instrument, Provenance, envelopes)
│   │   ├── providers/     base contract, demo, csv, evds, licence gates, registry
│   │   ├── validation/    OHLCV and NAV data-quality checks
│   │   ├── analytics/     returns, risk, technical, fund analytics (pure functions)
│   │   └── api/           FastAPI app and routers
│   └── tests/             unit + no-look-ahead + API tests
└── frontend/              Next.js App Router terminal
```

## 4. API contracts (v1)

Every endpoint returns:

```json
{
  "data": { ... },
  "provenance": [{ "provider": "demo", "data_mode": "demo", "as_of": "2026-10-15",
                   "retrieved_at": "...", "attribution": "...", "license_note": "..." }],
  "validation": [{ "severity": "warning", "code": "gap", "message": "...", "count": 3 }],
  "methodology": { "returns": "log", "annualization": 252, "risk_free": "0.0 (configurable)" }
}
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/v1/providers` | provider status, mode, licence notes |
| GET | `/v1/market/overview` | index level, breadth, top movers, volatility regime (descriptive) |
| GET | `/v1/instruments?q=&kind=` | search equities / funds / indices |
| GET | `/v1/instruments/{symbol}` | metadata |
| GET | `/v1/instruments/{symbol}/bars?start=&end=` | OHLCV or NAV with validation |
| GET | `/v1/instruments/{symbol}/technicals` | indicator series (SMA, EMA, RSI, MACD, BB, ATR, ADX, OBV, Donchian) |
| GET | `/v1/instruments/{symbol}/risk?benchmark=&rf=` | risk/return statistics vs benchmark |
| GET | `/v1/funds/{code}/performance?benchmark=` | period returns, rolling returns, drawdowns, risk-adjusted metrics |

OpenAPI is generated by FastAPI at `/docs`.

## 5. Frontend structure

```
app/
  layout.tsx                 shell: sidebar nav (14 sections; unbuilt ones marked Planned), data-mode banner
  page.tsx                   Market Overview
  equities/page.tsx          searchable equity table
  equities/[symbol]/page.tsx candlestick + volume + indicator panes, risk panel, provenance
  funds/page.tsx             fund table
  funds/[code]/page.tsx      NAV vs benchmark, drawdown, rolling returns, metrics
components/
  charts/                    lightweight-charts wrappers (client components)
  ui/                        shadcn-style primitives (Card, Badge, Table, Stat)
  provenance.tsx             source/freshness/mode chip shown on every panel
lib/api.ts                   typed fetch client with error handling
```

## 6. Conventions (quant)

- Returns: simple returns for portfolio aggregation, log returns for time-series statistics.
  Each endpoint states which one it uses.
- Annualisation: 252 trading days for BIST daily bars. Fund NAVs use TEFAS business days (also 252).
  Volatility scales by √252. CAGR uses calendar time.
- Sharpe/Sortino: excess return over a risk-free rate taken as an **explicit input**. In Turkey it
  should come from a TRY money-market or policy-rate series (EVDS). A 0% default would badly
  overstate Sharpe in TRY, so the API returns the rf actually used.
- VaR/CVaR: historical, one-day, reported as positive loss fractions at 95%/99%.
- Indicators: Wilder smoothing for RSI/ATR/ADX. Every indicator is tested for **no look-ahead**:
  appending future bars must not change any past value.
