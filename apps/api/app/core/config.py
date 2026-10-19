"""Environment-based configuration. Secrets are never defaulted, logged or echoed in responses."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    environment: str = field(default_factory=lambda: os.getenv("ATLAS_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: os.getenv("ATLAS_DATABASE_URL", f"sqlite:///{(API_ROOT / 'var' / 'atlas_dev.db').as_posix()}")
    )
    # Fixtures: synthetic, deterministic, always labelled. Fixed end date = reproducible, never "live".
    enable_fixtures: bool = field(default_factory=lambda: _bool("ATLAS_ENABLE_FIXTURES", True))
    fixture_end: date = field(default_factory=lambda: date.fromisoformat(os.getenv("ATLAS_FIXTURE_END", "2026-10-15")))
    csv_dir: str | None = field(default_factory=lambda: os.getenv("ATLAS_CSV_DIR") or None)
    evds_api_key: str | None = field(default_factory=lambda: os.getenv("ATLAS_EVDS_API_KEY") or None)
    evds_base_url: str = field(default_factory=lambda: os.getenv("ATLAS_EVDS_BASE_URL", "https://evds2.tcmb.gov.tr/service/evds/"))
    cors_origins: list[str] = field(default_factory=lambda: _list("ATLAS_CORS_ORIGINS", "http://localhost:3000"))
    session_ttl_hours: int = field(default_factory=lambda: int(os.getenv("ATLAS_SESSION_TTL_HOURS", "12")))
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("ATLAS_RATE_LIMIT_PER_MIN", "300")))
    auth_rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("ATLAS_AUTH_RATE_LIMIT_PER_MIN", "10")))
    stale_after_business_days: int = field(default_factory=lambda: int(os.getenv("ATLAS_STALE_AFTER_BDAYS", "3")))
    log_json: bool = field(default_factory=lambda: _bool("ATLAS_LOG_JSON", True))
    # AI research copilot. Credentials come from ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login`, never from here.
    ai_enabled: bool = field(default_factory=lambda: _bool("ATLAS_AI_ENABLED", True))
    ai_model: str = field(default_factory=lambda: os.getenv("ATLAS_AI_MODEL", "claude-opus-5-5"))
    ai_effort: str = field(default_factory=lambda: os.getenv("ATLAS_AI_EFFORT", "medium"))
    ai_max_rounds: int = field(default_factory=lambda: int(os.getenv("ATLAS_AI_MAX_ROUNDS", "8")))
    ai_queries_per_minute: int = field(default_factory=lambda: int(os.getenv("ATLAS_AI_QUERIES_PER_MIN", "6")))
    # Production hardening (Milestone 7).
    redis_url: str | None = field(default_factory=lambda: os.getenv("ATLAS_REDIS_URL") or None)
    # Only these peers may set X-Forwarded-For (the web server's rewrite proxy, a load balancer). CIDRs allowed.
    trusted_proxies: list[str] = field(default_factory=lambda: _list("ATLAS_TRUSTED_PROXIES", "127.0.0.1/32,::1/128"))
    max_body_bytes: int = field(default_factory=lambda: int(os.getenv("ATLAS_MAX_BODY_BYTES", "1000000")))
    login_max_failures: int = field(default_factory=lambda: int(os.getenv("ATLAS_LOGIN_MAX_FAILURES", "5")))
    login_lockout_minutes: int = field(default_factory=lambda: int(os.getenv("ATLAS_LOGIN_LOCKOUT_MINUTES", "15")))
    metrics_token: str | None = field(default_factory=lambda: os.getenv("ATLAS_METRICS_TOKEN") or None)
    expose_docs_env: str | None = field(default_factory=lambda: os.getenv("ATLAS_EXPOSE_DOCS") or None)
    backup_dir: str = field(default_factory=lambda: os.getenv("ATLAS_BACKUP_DIR") or (API_ROOT / "var" / "backups").as_posix())
    backup_keep: int = field(default_factory=lambda: int(os.getenv("ATLAS_BACKUP_KEEP", "14")))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def secure_cookies(self) -> bool:
        # The public demo is served over HTTPS but runs with fixture data and SQLite, so it is not "production".
        return self.environment in {"production", "demo"}

    @property
    def expose_docs(self) -> bool:
        if self.expose_docs_env is not None:
            return self.expose_docs_env.strip().lower() in {"1", "true", "yes"}
        return not self.is_production


def production_issues(s: Settings) -> tuple[list[str], list[str]]:
    """(errors, warnings) for ATLAS_ENV=production. Errors stop the API from starting."""
    errors, warnings = [], []
    if s.database_url.startswith("sqlite"):
        errors.append("ATLAS_DATABASE_URL must point to PostgreSQL in production (SQLite is for development and tests).")
    if s.enable_fixtures:
        errors.append("ATLAS_ENABLE_FIXTURES must be false in production: synthetic data must never be served as a product.")
    if any(o == "*" or o.startswith("http://") and "localhost" not in o for o in s.cors_origins):
        errors.append("ATLAS_CORS_ORIGINS must list explicit https origins in production.")
    if not s.metrics_token:
        errors.append("ATLAS_METRICS_TOKEN must be set in production (/metrics is otherwise refused).")
    if not s.redis_url:
        warnings.append("ATLAS_REDIS_URL is not set: rate limits and login lockout are per process.")
    if s.expose_docs:
        warnings.append("API docs are exposed (ATLAS_EXPOSE_DOCS=true).")
    return errors, warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
