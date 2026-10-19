"""ATLAS API application factory."""

from __future__ import annotations

import hmac
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.api.v1 import auth, backtests, equities, funds, portfolios, reports, research, screener, system
from app.core.config import API_ROOT, Settings, get_settings, production_issues
from app.core.db import Database
from app.core.metrics import Registry, build_registry
from app.core.observability import (
    BodySizeLimitMiddleware, CorrelationIdMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware, configure_logging,
    parse_networks, request_id_var,
)
from app.core.ratelimit import build_limiter
from app.integrations.base import ProviderError, ProviderUnavailable

log = logging.getLogger("atlas.api")


def migration_head() -> str | None:
    """Head revision of the migration scripts, or None where the scripts are not shipped."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        return ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini"))).get_current_head()
    except Exception:  # pragma: no cover - packaging without migrations
        return None


def _data_gauges(app: FastAPI, registry: Registry) -> None:
    """Freshness gauges, computed at scrape time from the database and cached for 60 s."""
    from app.repositories.series import latest_observation_dates
    from app.services.data_quality import series_freshness
    from app.services.provenance import istanbul_today

    cache: dict = {"at": float("-inf"), "series": [], "lag": []}

    def refresh() -> None:
        if time.monotonic() - cache["at"] < 60:
            return
        with app.state.db.sessionmaker() as s:
            latest = latest_observation_dates(s)
        today, stale = istanbul_today(), app.state.settings.stale_after_business_days
        counts: dict[str, int] = {}
        worst = 0
        for d in latest.values():
            status, lag = series_freshness(d, today, stale)
            counts[status] = counts.get(status, 0) + 1
            worst = max(worst, lag or 0)
        cache.update(at=time.monotonic(), series=[({"freshness": k}, v) for k, v in sorted(counts.items())],
                     lag=[({}, worst)] if latest else [])

    def series():
        refresh()
        return cache["series"]

    def lag():
        refresh()
        return cache["lag"]

    registry.gauge("atlas_data_series", "Stored price/NAV series by freshness status.", series)
    registry.gauge("atlas_data_max_lag_business_days", "Largest business-day lag of any stored series.", lag)


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_json)
    if settings.is_production:
        errors, warnings = production_issues(settings)
        for w in warnings:
            log.warning("production config: %s", w)
        if errors:
            raise RuntimeError("Refusing to start in production:\n- " + "\n- ".join(errors))
    docs = settings.expose_docs
    app = FastAPI(
        title="ATLAS QUANT TERMINAL API", version="0.3.0",
        description="Research & analytics API. Not investment advice. No order execution.",
        docs_url="/api/docs" if docs else None, openapi_url="/api/openapi.json" if docs else None, redoc_url=None,
    )
    app.state.settings = settings
    app.state.db = database or Database(settings.database_url)
    app.state.metrics = build_registry()
    app.state.rate_limiter = build_limiter(settings.redis_url, app.state.metrics)
    app.state.trusted_networks = parse_networks(settings.trusted_proxies)
    app.state.migration_head = migration_head()
    _data_gauges(app, app.state.metrics)

    # Starlette runs the last-added middleware outermost:
    # correlation id/metrics → security headers → rate limit → body size → CORS → routes.
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["content-type", "x-csrf-token", "x-request-id"],
                       expose_headers=["x-request-id"])
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(RateLimitMiddleware, general_limit=settings.rate_limit_per_minute,
                       auth_limit=settings.auth_rate_limit_per_minute)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(CorrelationIdMiddleware)

    @app.exception_handler(ProviderUnavailable)
    async def _unavailable(_: Request, exc: ProviderUnavailable):
        return JSONResponse(status_code=503, content={"detail": str(exc), "status": "UNAVAILABLE", "request_id": request_id_var.get()})

    @app.exception_handler(ProviderError)
    async def _provider(_: Request, exc: ProviderError):
        log.warning("provider error: %s", exc)
        return JSONResponse(status_code=502, content={"detail": "Upstream data error", "request_id": request_id_var.get()})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "Internal error", "request_id": request_id_var.get()})

    @app.get("/health", tags=["system"])
    def health() -> dict:
        """Liveness: the process answers. Does not touch dependencies."""
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    def ready() -> JSONResponse:
        """Readiness: database reachable, schema at the migration head, rate-limit backend reachable."""
        checks: dict[str, str] = {}
        ok = True
        try:
            with app.state.db.engine.connect() as c:
                c.execute(text("select 1"))
                checks["database"] = "ok"
                try:
                    current = c.execute(text("select version_num from alembic_version")).scalar()
                except Exception:
                    current = None
                    c.rollback()
            head = app.state.migration_head
            if current is None:
                # create_all()-built dev/test databases have no version table; production must be migrated.
                checks["schema"] = "unversioned"
                ok &= not settings.is_production
            elif head and current != head:
                checks["schema"] = f"behind: {current} (head {head}); run alembic upgrade head"
                ok = False
            else:
                checks["schema"] = "ok"
        except Exception:
            checks["database"] = "unavailable"
            ok = False
        limiter = app.state.rate_limiter
        if limiter.ping():
            checks["rate_limiter"] = f"ok ({limiter.backend})"
        else:
            # Degraded, not down: the limiter falls back to per-process memory.
            checks["rate_limiter"] = f"degraded ({limiter.backend} unreachable, memory fallback)"
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> PlainTextResponse:
        token = settings.metrics_token
        if token:
            given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(given.encode(), token.encode()):
                return PlainTextResponse("unauthorized\n", status_code=401, headers={"WWW-Authenticate": "Bearer"})
        elif settings.is_production:  # unreachable: production refuses to start without a token
            return PlainTextResponse("not found\n", status_code=404)
        return PlainTextResponse(app.state.metrics.render(), media_type="text/plain; version=0.0.4")

    for r in (auth.router, portfolios.router, equities.router, funds.router, screener.router, reports.router, research.router,
              backtests.router, system.router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
