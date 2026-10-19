# Runbook (local development)

## Windows, one click
Double-click `baslat.cmd` (repo root). It installs on first run, starts both servers in their own windows,
waits for the web app and opens the browser. Re-running it while the servers are up does not start duplicates.

The web app runs as a production build (`apps/web/.next-prod`): `scripts/build-if-changed.mjs` rebuilds only when
web sources changed (about 1 minute, otherwise instant), then `next start`. Page navigations take 25–200 ms.
`gelistir.cmd` starts `next dev` instead (live reload; every page compiles on first visit, 1–3 s). To switch
modes, close the "ATLAS WEB" window first; the running mode is recorded in `apps/web/.atlas-mode`.

There is deliberately no route-level `loading.tsx`: once a Suspense fallback is shown, React holds the real page
back for about 300 ms, which made every click take ≥ 300 ms although the server answered in < 50 ms. The sidebar
shows a small pulsing dot on the clicked item instead, only when a page takes longer than 120 ms.

## Windows PowerShell 5.1, manual
PowerShell 5.1 has no `&&` and blocks `npm.ps1` under the default execution policy, so use the venv python
directly and `npm.cmd`:
```powershell
cd apps\api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.workers.cli ingest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
```powershell
cd apps\web
npm.cmd ci
npm.cmd run dev
```

## bash (macOS/Linux/Git Bash)
```bash
# API
cd apps/api
python -m venv .venv && source .venv/Scripts/activate      # macOS/Linux: .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head                                        # creates apps/api/var/atlas_dev.db (SQLite)
python -m app.workers.cli ingest                            # loads the labelled fixture universe
uvicorn app.main:app --host 127.0.0.1 --port 8000

# Web (second terminal)
cd apps/web
npm ci
npm run dev                                                 # http://localhost:3000
```

## With Docker (written, NOT executed: no Docker on the authoring machine)
```bash
cp .env.example .env          # set POSTGRES_PASSWORD
docker compose up --build     # db → migrate (+ fixture ingest) → api → web
```

## Tests
```bash
cd apps/api && pytest                        # unit, property, API, auth, migrations
cd apps/web && npm run typecheck && npm test # Vitest + Testing Library
cd apps/web && npm run test:e2e              # Playwright; needs API + web running. PW_CHANNEL=msedge uses local Edge
```

## Operations
- Re-ingest: `python -m app.workers.cli ingest` (idempotent; exits non-zero if any run fails).
- Create an admin: `ATLAS_NEW_USER_PASSWORD=... python -m app.workers.cli create-user you@example.com --role administrator`.
- Logs: JSON lines on stdout with `request_id`, route template, status, duration and the real client IP.
  Set `ATLAS_LOG_JSON=false` for plain text.

## Monitoring
| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness: the process answers. Use for restarts |
| `GET /ready` | Readiness: database reachable, schema at the migration head (`behind: …` → run `alembic upgrade head`), rate-limit backend. 503 when not ready; Redis down is reported as `degraded` (memory fallback) and does not fail readiness |
| `GET /metrics` | Prometheus text format. Requires `Authorization: Bearer $ATLAS_METRICS_TOKEN` when the token is set (always, in production) |
| `GET /api/v1/system/data-health` | Per-series freshness and quality issues (human dashboard: `/system/data-health`) |

Metrics: `atlas_http_requests_total{method,route,status}`, `atlas_http_request_duration_seconds` (histogram),
`atlas_http_errors_total`, `atlas_rate_limited_total{bucket}`, `atlas_ratelimit_backend_errors_total`,
`atlas_login_failures_total{outcome}`, `atlas_ai_queries_total{result}`, `atlas_ai_tokens_total{kind}`,
`atlas_data_series{freshness}`, `atlas_data_max_lag_business_days`. Routes are templates
(`/api/v1/equities/{symbol}`), never raw paths, so label cardinality stays bounded. Counters are per process.

Scrape config and alert rules: `infrastructure/monitoring/prometheus.yml`, `alerts.yml` (API down, 5xx > 2%,
p95 > 1 s, data older than 3 business days, Redis errors, lockout spikes, AI upstream failures). Written, **not
executed** here (no Prometheus on this machine); thresholds are starting points.

## Backups and restore
```bash
python -m app.workers.cli backup            # snapshot + manifest, verify, keep newest ATLAS_BACKUP_KEEP (14)
python -m app.workers.cli backups           # list
python -m app.workers.cli verify-backup     # newest; or pass a manifest path
python -m app.workers.cli restore var/backups/atlas-sqlite-<time>.json --target sqlite:///path/to/restored.db
```
- SQLite: online backup API (safe while the API runs), gzipped; verify restores into a temp file, runs
  `PRAGMA integrity_check` and compares row counts and migration revision with the manifest.
- PostgreSQL: `pg_dump --format=custom` (password via `PGPASSWORD`); verify runs `pg_restore --list`. A full
  restore drill into a scratch database is still needed (not run here: no PostgreSQL on this machine).
- Restore never overwrites an existing database without `--force`; with it, the old SQLite file is kept as
  `*.pre-restore-<time>`. Stop the API first.
- `baslat.cmd` takes a backup (keeps 7) before every migration run. Backups live in `apps/api/var/backups`
  (`ATLAS_BACKUP_DIR`), git-ignored. Copy them off the machine: a backup on the same disk does not survive the disk.
- Daily on Windows: Task Scheduler → action `apps\api\.venv\Scripts\python.exe`, arguments
  `-m app.workers.cli backup`, "Start in" `apps\api`.

## Production checklist
`ATLAS_ENV=production` refuses to start unless: PostgreSQL URL, `ATLAS_ENABLE_FIXTURES=false`, explicit https CORS
origins, `ATLAS_METRICS_TOKEN` set. It warns without `ATLAS_REDIS_URL`. Also:
1. TLS in front of the web app (the API sends HSTS in production; set it on the web proxy too).
2. `ATLAS_TRUSTED_PROXIES` = the addresses of the web server / load balancer that forward to the API, nothing wider.
3. `alembic upgrade head` as a release step; `/ready` fails while the schema is behind.
4. Daily backups copied off-host, and a restore drill at least monthly.
5. Docs stay off (`ATLAS_EXPOSE_DOCS` unset). Open items: docs/compliance/SECURITY_REVIEW.md.

## Measured performance (dev laptop, SQLite, fixture data, single request, TestClient)
| Endpoint | Time | Payload |
|---|---|---|
| /search?q=bank | 34 ms (first), 5 ms (warm) | 0.5 KB |
| /equities/{s}/prices?window=3M | 24 ms | 4 KB |
| /equities/{s}/prices?window=MAX&interval=1w | 36 ms | 20 KB |
| /equities/{s}/technicals?window=1Y | 64 ms | 58 KB |
| /equities/{s}/risk | 58 ms | 26 KB |
| /funds/{c}/performance | 62 ms | 147 KB |
| /market/overview | 279 ms cold, 4 ms cached (until the next ingestion run) | 21 KB |

These are indicative only. They are not load-tested and were not measured against PostgreSQL.

## Running a second, isolated dev instance
`NEXT_DIST_DIR=.next-test ATLAS_API_URL=http://127.0.0.1:8001 npm.cmd run dev -- -p 3001` lets a test instance run
alongside the main one without sharing the `.next` build folder.
