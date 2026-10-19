# Security review (Milestone 7, 2026-10-16)

An internal code-level review against the OWASP Top 10 (2021) and ASVS L1 topics. **It is not a substitute for an
independent penetration test**, which is still required before launch (see SECURITY_COMPLIANCE.md).

## Method
- Read every route, dependency and middleware in `apps/api/app`, and the web app's request path (`next.config.ts`
  rewrite, `lib/api-client.ts`).
- Dependency scans: `pip-audit` on the API's frozen environment and `npm audit --omit=dev` on the web app.
- Tested fixes are listed with the test that covers them.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Starlette 0.46.2 (via FastAPI 0.115.12) had 7 published advisories: Host header URL reconstruction, form-parser limits, Range-header DoS, StaticFiles UNC paths on Windows. The app uses none of forms, StaticFiles or FileResponse, so exposure was limited | High (dependency) | **Fixed**: FastAPI 0.143.2 + Starlette 1.8.0; `pip-audit`: no known vulnerabilities. All 193 API tests pass |
| 2 | Browser requests reach the API through the web server's rewrite proxy, so every user shared the proxy's IP: one user could exhaust the per-IP limit for all, and audit logs recorded the proxy address | High | **Fixed**: `client_ip()` honours `X-Forwarded-For` only from `ATLAS_TRUSTED_PROXIES`, read right to left (client-supplied entries cannot spoof). `test_client_ip_honours_forwarded_for_only_from_trusted_proxies` |
| 3 | Rate limits were per process, so N instances allowed N× the limit | Medium | **Fixed**: Redis limiter (`ATLAS_REDIS_URL`), with a per-process fallback during an outage. `test_redis_limiter_is_shared_between_instances_and_falls_back` |
| 4 | No per-account brute-force protection (only per-IP). Distributed guessing against one account was unlimited | Medium | **Fixed**: lockout after `ATLAS_LOGIN_MAX_FAILURES` (5) failures per email for 15 min, applied to unknown emails too (no enumeration). Trade-off: an attacker can lock a known account for 15 min. `test_login_lockout_is_per_email_and_does_not_reveal_accounts` |
| 5 | No way to change a password or end sessions on other devices | Medium | **Fixed**: `POST /auth/password` (re-authentication, revokes every session, new session for this browser) and `POST /auth/logout-all`. `test_password_change_revokes_all_sessions`, `test_logout_all` |
| 6 | No request body size limit | Medium | **Fixed**: 1 MB (`ATLAS_MAX_BODY_BYTES`), also for chunked bodies → 413. `test_body_size_limit` |
| 7 | API responses lacked hardening headers; responses with private data could be cached | Low | **Fixed**: nosniff, `frame-ancestors 'none'` CSP, no-referrer, CORP; `Cache-Control: no-store` on signed-in requests; HSTS in production. `test_security_headers` |
| 8 | Web app had no Content-Security-Policy | Medium | **Partly fixed**: production CSP blocks third-party scripts, framing, plugins and foreign connections. `script-src` still allows `'unsafe-inline'` because Next.js inlines its bootstrap scripts; nonce-based CSP via middleware is open. Zod runs `jitless` so no eval is needed |
| 9 | Unsafe production configuration was possible (SQLite, fixtures served as product, `*` CORS, open metrics) | Medium | **Fixed**: `ATLAS_ENV=production` refuses to start on these. `test_production_refuses_unsafe_configuration` |
| 10 | API docs (`/api/docs`, OpenAPI) were public in every environment | Low | **Fixed**: off by default in production (`ATLAS_EXPOSE_DOCS`). `test_production_app_hardening` |
| 11 | `pg_dump` connection string could carry the database password on the command line (visible in the process list) | Medium | **Fixed before release** (found by the backup tests): password only in `PGPASSWORD`. `test_postgres_commands_keep_password_out_of_argv` |
| 12 | `next` bundles PostCSS < 8.5.23 (source-map path traversal, `</style>` stringify XSS) | Low in this app (PostCSS processes only our own CSS, at build time) | **Open**: fix needs Next 16 (major upgrade) |
| 13 | `sharp` (optional Next.js image optimizer) has libvips/libheif/librsvg advisories | Low | **Mitigated**: the app uses no `next/image`; the optimizer is disabled (`images.unoptimized`). Upgrade with Next 16 |
| 14 | Uvicorn trusts `X-Forwarded-For` from 127.0.0.1 by default, a second, implicit trust rule | Low | **Fixed** in the container (`--no-proxy-headers`); `ATLAS_TRUSTED_PROXIES` is the single source |

## Reviewed, no change needed
- **Injection:** all SQL goes through SQLAlchemy expressions. The two `text()` uses take no user input (`select 1`,
  table names from the database's own catalogue in backups). The screener DSL is a typed tree, not SQL.
- **Access control:** every user-owned resource (portfolios, transactions, saved screens, reports, AI queries) is
  scoped by `user_id` in the query; other users get 404 (tested per resource).
- **Session management:** opaque 256-bit tokens, only SHA-256 stored, HttpOnly + SameSite=Lax (+Secure in
  production), CSRF double-submit on every state change, 12 h TTL.
- **AI copilot:** read-only typed tools, user-scoped portfolio tool, tool output passed as data, per-user limit,
  every query audited (AI_COPILOT.md).
- **Errors:** unhandled exceptions return a generic 500 with a request id; details only in server logs.
- **Secrets:** environment only, never logged. The metrics token is compared in constant time.

## Open items (owner: before launch)
1. External penetration test and dependency review by a third party.
2. Next.js 16 upgrade (findings 12, 13), then nonce-based CSP (finding 8).
3. MFA for administrator accounts; password reset by e-mail (needs an e-mail provider).
4. TLS termination, secret manager, encryption at rest: infrastructure choices, outside this repository.
