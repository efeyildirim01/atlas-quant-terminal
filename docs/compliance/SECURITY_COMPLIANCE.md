# Security, Governance & Compliance

## Regulatory perimeter (requires Turkish legal counsel before launch)
- **SPK / Capital Markets Law 6362:** investment advisory and portfolio management are licensed activities.
  ATLAS is a research and analytics tool. It has no order execution and no personalised recommendations,
  and the signal classification is held at "insufficient evidence" until calibrated models exist.
- **Market-data licensing:** sources without permission are hard-blocked (`UnavailableSource`). Redistribution
  and derived-index rights are recorded per source in `data_sources`.
- **KVKK (Law 6698):** only email, display name, role, portfolios and audit logs are stored. Still to do:
  VERBIS assessment, a hosting/transfer decision, a retention schedule and a data-subject request workflow.

## Controls
| Control | Implementation | Tested |
|---|---|---|
| Passwords | stdlib scrypt (n=2¹⁵, r=8, p=1), salted; min 12 chars | `test_password_hashing` |
| Sessions | Opaque 256-bit token in an HttpOnly, SameSite=Lax cookie (Secure in production). Only its SHA-256 is stored. 12h TTL. Revoked on logout | `test_register_login_me_logout`, `test_session_token_not_stored_in_plaintext` |
| CSRF | Double-submit token required on every state-changing request with a session | `test_csrf_required_for_state_changes` |
| User enumeration | Constant-cost login (dummy hash) with the same error message | `test_bad_credentials_and_weak_password` |
| RBAC | Roles user < professional < research_analyst < administrator; `require_role` dependency | `test_require_role_dependency` |
| Data isolation | Portfolio queries scoped by `user_id`; other users' resources → 404 | `test_portfolio_isolation_between_users` |
| Rate limiting | Per real client IP (X-Forwarded-For only from trusted proxies): 300/min API, 10/min auth. Redis-backed and shared across instances when `ATLAS_REDIS_URL` is set; per-process fallback | `test_auth_rate_limit`, `test_redis_limiter_is_shared_between_instances_and_falls_back`, `test_client_ip_honours_forwarded_for_only_from_trusted_proxies` |
| Brute force | Per-email lockout after 5 failures for 15 min, also for unknown emails | `test_login_lockout_is_per_email_and_does_not_reveal_accounts` |
| Password change / sessions | Re-authentication; revokes every session; sign out everywhere | `test_password_change_revokes_all_sessions`, `test_logout_all` |
| Request size | 1 MB body limit, incl. chunked | `test_body_size_limit` |
| Production config | Refuses to start with SQLite, fixtures, wildcard CORS or no metrics token; docs off | `test_production_refuses_unsafe_configuration`, `test_production_app_hardening` |
| Backups | Verified snapshots (checksum, integrity, row counts), retention, guarded restore | `test_backup.py` |
| Audit log | Register, login (incl. denied), logout, portfolio create/delete, with request id and IP | `test_bad_credentials_and_weak_password` |
| Secrets | Environment only; `.env` git-ignored; EVDS key sent in a header, never in URLs | `test_evds_parses_and_sends_key_in_header_not_url` |
| LLM assistant | Tools are read-only and typed; tool output treated as data; per-user 6/min limit; every query, evidence and verification stored and audited; numeric verifier flags unsupported figures; API key only from the environment | `test_ai_copilot.py`, `test_ai_verify.py` |
| Headers | API: nosniff, CSP `default-src 'none'`, no-referrer, CORP, `no-store` when signed in, HSTS in production. Web: CSP (production), X-Frame-Options DENY, Permissions-Policy, COOP | `test_security_headers` |
| Errors | Unhandled exceptions return a generic 500 with request id; detail only in logs | — |

## Not yet done
Internal review done (docs/compliance/SECURITY_REVIEW.md). Still open: independent pen test, Next.js 16 upgrade and
nonce-based CSP, MFA, password reset by e-mail, TLS termination, encryption at rest, a secret manager,
Sentry/OpenTelemetry exporters.
