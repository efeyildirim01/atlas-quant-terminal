"""Milestone 7 hardening: shared rate limiting, client IP, lockout, password change, headers, body limit, metrics,
readiness and production configuration checks."""

from __future__ import annotations

import fnmatch
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.requests import Request

from app.auth.deps import CSRF_COOKIE
from app.core.config import production_issues
from app.core.db import Base, Database
from app.core.metrics import build_registry
from app.core.observability import client_ip, parse_networks
from app.core.ratelimit import MemoryRateLimiter, RedisRateLimiter
from app.main import create_app
from tests.conftest import make_settings

PASSWORD = "correct horse battery"


class FakeRedis:
    """The subset of redis-py the limiter uses; `down=True` simulates an outage."""

    def __init__(self):
        self.data: dict[str, int] = {}
        self.ttl: dict[str, int] = {}
        self.down = False

    def _check(self):
        if self.down:
            raise ConnectionError("redis down")

    def pipeline(self, transaction=True):
        fake, ops = self, []

        class P:
            def incr(self, k):
                ops.append(("incr", k))

            def expire(self, k, s):
                ops.append(("expire", k, s))

            def execute(self):
                fake._check()
                out = []
                for op in ops:
                    if op[0] == "incr":
                        fake.data[op[1]] = fake.data.get(op[1], 0) + 1
                        out.append(fake.data[op[1]])
                    else:
                        fake.ttl[op[1]] = op[2]
                        out.append(True)
                return out

        return P()

    def get(self, k):
        self._check()
        return self.data.get(k)

    def scan_iter(self, match):
        self._check()
        return [k for k in list(self.data) if fnmatch.fnmatch(k, match)]

    def delete(self, k):
        self.data.pop(k, None)

    def ping(self):
        self._check()
        return True


def app_for(tmp_path, name="h.db", **overrides):
    settings = make_settings(f"sqlite:///{(tmp_path / name).as_posix()}", **overrides)
    database = Database(settings.database_url)
    Base.metadata.create_all(database.engine)
    return create_app(settings, database)


def register(c: TestClient, email: str | None = None) -> tuple[str, dict]:
    email = email or f"h-{uuid.uuid4().hex[:8]}@example.com"
    r = c.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email, {"X-CSRF-Token": c.cookies.get(CSRF_COOKIE)}


# ── rate limiting ─────────────────────────────────────────────────────────────────────────────────
def test_memory_limiter_sliding_window():
    now = [0.0]
    lim = MemoryRateLimiter(clock=lambda: now[0])
    assert [lim.allow("b", "k", 2, 10) for _ in range(3)] == [True, True, False]
    now[0] = 10.5
    assert lim.allow("b", "k", 2, 10) and lim.count("b", "k", 10) == 1
    lim.reset("b", "k")
    assert lim.count("b", "k", 10) == 0


def test_redis_limiter_is_shared_between_instances_and_falls_back():
    shared, metrics = FakeRedis(), build_registry()
    now = [1_000.0]
    a = RedisRateLimiter(shared, metrics=metrics, clock=lambda: now[0])
    b = RedisRateLimiter(shared, metrics=metrics, clock=lambda: now[0])  # a second API process
    assert [a.allow("api", "1.2.3.4", 3), b.allow("api", "1.2.3.4", 3), a.allow("api", "1.2.3.4", 3)] == [True] * 3
    assert b.allow("api", "1.2.3.4", 3) is False  # the limit is global, not per process
    assert all(ttl == 61 for ttl in shared.ttl.values())  # keys expire with the window
    now[0] += 60
    assert a.allow("api", "1.2.3.4", 3)  # next window
    b.hit("login_fail", "x@example.com", 900)
    assert a.count("login_fail", "x@example.com", 900) == 1
    a.reset("login_fail", "x@example.com")
    assert b.count("login_fail", "x@example.com", 900) == 0

    shared.down = True  # outage: still limited (per process), never raises, counted
    assert [a.allow("api", "5.6.7.8", 2) for _ in range(3)] == [True, True, False]
    assert metrics.value("atlas_ratelimit_backend_errors_total") == 3 and a.ping() is False


def test_ai_and_api_limits_use_the_shared_limiter(tmp_path):
    app = app_for(tmp_path)
    app.state.rate_limiter = RedisRateLimiter(FakeRedis(), metrics=app.state.metrics)
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    assert c.get("/ready").json()["checks"]["rate_limiter"] == "ok (redis)"
    assert c.get("/api/v1/system/sources").status_code == 200


# ── client IP ─────────────────────────────────────────────────────────────────────────────────────
def _req(peer: str, xff: str | None, trusted=("127.0.0.1/32", "10.0.0.0/8")) -> Request:
    app = type("A", (), {"state": type("S", (), {"trusted_networks": parse_networks(list(trusted))})()})()
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers, "app": app})


def test_client_ip_honours_forwarded_for_only_from_trusted_proxies():
    assert client_ip(_req("127.0.0.1", "203.0.113.9")) == "203.0.113.9"  # via the web rewrite proxy
    assert client_ip(_req("198.51.100.7", "203.0.113.9")) == "198.51.100.7"  # direct client cannot spoof
    # Client-supplied leftmost entry is ignored; the first untrusted hop from the right is the client.
    assert client_ip(_req("10.1.2.3", "6.6.6.6, 203.0.113.9, 10.0.0.5")) == "203.0.113.9"
    assert client_ip(_req("127.0.0.1", None)) == "127.0.0.1"


# ── login lockout, password change, sign out everywhere ──────────────────────────────────────────
def test_login_lockout_is_per_email_and_does_not_reveal_accounts(tmp_path):
    c = TestClient(app_for(tmp_path, login_max_failures=3))
    email, _ = register(c)
    c.post("/api/v1/auth/logout")
    bad = [c.post("/api/v1/auth/login", json={"email": email, "password": "wrong password!"}).status_code for _ in range(3)]
    assert bad == [401, 401, 401]
    locked = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert locked.status_code == 429 and "Try again in 15 minutes" in locked.json()["detail"]
    # Unknown accounts behave identically (no enumeration).
    ghost = [c.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"}).status_code for _ in range(4)]
    assert ghost == [401, 401, 401, 429]
    # Another account is unaffected; success clears earlier failures.
    other, _ = register(c)
    c.post("/api/v1/auth/logout")
    for _ in range(2):
        c.post("/api/v1/auth/login", json={"email": other, "password": "nope nope nope"})
    assert c.post("/api/v1/auth/login", json={"email": other, "password": PASSWORD}).status_code == 200
    assert c.app.state.rate_limiter.count("login_fail", other, 900) == 0
    assert c.app.state.metrics.value("atlas_login_failures_total", outcome="locked") == 2


def test_password_change_revokes_all_sessions(tmp_path):
    app = app_for(tmp_path)
    phone, laptop = TestClient(app), TestClient(app)
    email, h = register(laptop)
    assert phone.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    assert laptop.post("/api/v1/auth/password", json={"current_password": "wrong", "new_password": "another long secret"},
                       headers=h).status_code == 403
    old_cookie = laptop.cookies.get("atlas_session")
    r = laptop.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "another long secret"}, headers=h)
    assert r.status_code == 200 and laptop.cookies.get("atlas_session") != old_cookie
    assert laptop.get("/api/v1/auth/me").status_code == 200  # fresh session for this browser
    assert phone.get("/api/v1/auth/me").status_code == 401  # every other device signed out
    assert TestClient(app).post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert TestClient(app).post("/api/v1/auth/login", json={"email": email, "password": "another long secret"}).status_code == 200
    # Without CSRF the change is refused.
    assert laptop.post("/api/v1/auth/password", json={"current_password": "another long secret", "new_password": "x" * 20}).status_code == 403


def test_logout_all(tmp_path):
    app = app_for(tmp_path)
    a, b = TestClient(app), TestClient(app)
    email, h = register(a)
    b.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert a.post("/api/v1/auth/logout-all", headers=h).status_code == 204
    assert a.get("/api/v1/auth/me").status_code == 401 and b.get("/api/v1/auth/me").status_code == 401


# ── headers and body limit ────────────────────────────────────────────────────────────────────────
def test_security_headers(client):
    r = client.get("/api/v1/system/sources")
    for k, v in {"x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer",
                 "content-security-policy": "default-src 'none'; frame-ancestors 'none'"}.items():
        assert r.headers[k] == v
    assert "strict-transport-security" not in r.headers  # HSTS only in production (behind TLS)
    assert "cache-control" not in r.headers  # public market data, anonymous
    assert client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x"}).headers["cache-control"] == "no-store"
    assert "content-security-policy" not in client.get("/api/docs").headers  # Swagger UI loads its CDN assets


def test_body_size_limit(tmp_path):
    c = TestClient(app_for(tmp_path, max_body_bytes=200))
    big = {"email": "a@example.com", "password": "p" * 300}
    assert c.post("/api/v1/auth/login", json=big).status_code == 413

    def chunks():  # no Content-Length: streamed body is counted too
        yield b'{"email": "a@example.com", '
        yield b'"password": "' + b"p" * 300 + b'"}'

    assert c.post("/api/v1/auth/login", content=chunks(), headers={"content-type": "application/json"}).status_code == 413
    small = c.post("/api/v1/auth/login", content=iter([b'{"email": "a@example.com", ', b'"password": "short"}']),
                   headers={"content-type": "application/json"})
    assert small.status_code == 401  # replayed body reaches the endpoint intact


# ── metrics and readiness ─────────────────────────────────────────────────────────────────────────
def test_metrics_exposition(client):
    client.get("/api/v1/equities/D-BNK1")
    client.get("/api/v1/equities/D-BNK2")
    client.get("/no/such/path")
    body = client.get("/metrics").text
    assert 'atlas_http_requests_total{method="GET",route="/api/v1/equities/{symbol}",status="200"}' in body  # template, not raw path
    assert 'route="unmatched",status="404"' in body and "D-BNK1" not in body
    assert 'atlas_http_request_duration_seconds_bucket{method="GET",route="/api/v1/equities/{symbol}",le="+Inf"}' in body
    assert 'atlas_data_series{freshness="FRESH"}' in body or 'atlas_data_series{freshness="STALE"}' in body
    assert "# TYPE atlas_http_requests_total counter" in body and "atlas_data_max_lag_business_days " in body


def test_metrics_token(tmp_path):
    c = TestClient(app_for(tmp_path, metrics_token="s3cret-token"))
    assert c.get("/metrics").status_code == 401
    assert c.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/metrics", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_ready_reports_schema_behind(tmp_path):
    app = app_for(tmp_path)
    with app.state.db.engine.begin() as conn:
        conn.execute(text("create table alembic_version (version_num varchar(32) not null)"))
        conn.execute(text("insert into alembic_version values ('0001')"))
    r = TestClient(app).get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["schema"].startswith("behind: 0001")
    with app.state.db.engine.begin() as conn:
        conn.execute(text("update alembic_version set version_num = :h"), {"h": app.state.migration_head})
    assert TestClient(app).get("/ready").json()["checks"]["schema"] == "ok"


# ── production configuration ──────────────────────────────────────────────────────────────────────
def test_production_refuses_unsafe_configuration(tmp_path):
    settings = replace(make_settings(f"sqlite:///{(tmp_path / 'p.db').as_posix()}"), environment="production")
    errors, _ = production_issues(settings)
    assert len(errors) == 3  # sqlite, fixtures, metrics token (localhost CORS origin is allowed)
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        create_app(settings)


def test_production_app_hardening(tmp_path):
    settings = replace(make_settings("postgresql+psycopg://atlas:x@db.internal:5432/atlas"), environment="production",
                       enable_fixtures=False, metrics_token="tok", cors_origins=["https://atlas.example.com"],
                       redis_url=None)
    errors, warnings = production_issues(settings)
    assert errors == [] and any("ATLAS_REDIS_URL" in w for w in warnings)
    database = Database(f"sqlite:///{(tmp_path / 'p.db').as_posix()}")
    Base.metadata.create_all(database.engine)
    c = TestClient(create_app(settings, database))
    r = c.get("/health")
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")
    assert c.get("/api/docs").status_code == 404 and c.get("/api/openapi.json").status_code == 404
    assert c.get("/ready").status_code == 503  # unversioned schema is not acceptable in production
    assert c.get("/metrics").status_code == 401


def test_demo_mode_uses_secure_cookies_but_is_not_production(tmp_path):
    c = TestClient(app_for(tmp_path, environment="demo"))
    r = c.post("/api/v1/auth/register", json={"email": "demo@example.com", "password": PASSWORD})
    assert r.status_code == 201
    assert all("secure" in v.lower() for v in r.headers.get_list("set-cookie"))
    assert "strict-transport-security" not in r.headers  # HSTS stays a production decision
    assert c.get("/api/docs").status_code == 200  # reviewers can browse the API in the demo
