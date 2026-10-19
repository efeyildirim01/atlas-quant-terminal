"""Structured JSON logging, request correlation IDs, metrics, client IP resolution and the HTTP hardening middleware.

Sentry/OpenTelemetry exporters attach here once their DSNs are configured.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.ratelimit import MemoryRateLimiter

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Backwards-compatible name: the in-memory limiter.
RateLimiter = MemoryRateLimiter

UNLIMITED_PATHS = {"/health", "/ready", "/metrics"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key in ("method", "path", "route", "status", "duration_ms", "client_ip", "user_id", "event"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(json_logs: bool) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger("atlas")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False


access_log = logging.getLogger("atlas.access")


# ── client IP ─────────────────────────────────────────────────────────────────────────────────────
def parse_networks(items: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(i, strict=False) for i in items]


def _trusted(ip: str, networks) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in networks)


def client_ip(request: Request) -> str:
    """The real client address. X-Forwarded-For is honoured only from trusted proxies, read right to left, so a
    client cannot spoof its address by sending the header itself."""
    peer = request.client.host if request.client else "unknown"
    networks = getattr(request.app.state, "trusted_networks", [])
    if not _trusted(peer, networks):
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not _trusted(hop, networks):
            return hop
    return hops[0] if hops else peer


def route_template(request: Request) -> str:
    """Route path template (e.g. /api/v1/equities/{symbol}) so metric labels stay low-cardinality.

    FastAPI >= 0.13x nests included routers, so scope["route"].path is relative to the router prefix; the static
    prefix is recovered as the part of the request path that the route's own pattern does not cover."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not template:
        return "unmatched"
    path = request.scope.get("path", "")
    regex = getattr(route, "path_regex", None)
    if regex is None or regex.match(path):
        return template
    for i in range(1, len(path)):
        if path[i] == "/" and regex.match(path[i:]):
            return path[:i] + template
    return template


# ── middleware ────────────────────────────────────────────────────────────────────────────────────
class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Request id, access log and HTTP metrics. Outermost, so every response (incl. 429/413) is counted."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum() else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        metrics = getattr(request.app.state, "metrics", None)
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Handled here (not in an app exception handler) so the error response and log keep the request id.
                logging.getLogger("atlas.api").exception("unhandled error")
                response = JSONResponse(status_code=500, content={"detail": "Internal error", "request_id": rid})
            elapsed = time.perf_counter() - start
            route = route_template(request)
            response.headers["X-Request-ID"] = rid
            if metrics is not None:
                metrics.inc("atlas_http_requests_total", method=request.method, route=route, status=str(response.status_code))
                metrics.observe("atlas_http_request_duration_seconds", elapsed, method=request.method, route=route)
                if response.status_code >= 500:
                    metrics.inc("atlas_http_errors_total", route=route)
            access_log.info(
                "request",
                extra={"method": request.method, "path": request.url.path, "route": route, "status": response.status_code,
                       "duration_ms": round(elapsed * 1000, 1), "client_ip": client_ip(request)},
            )
            return response
        finally:
            request_id_var.reset(token)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per client IP: general API limit, and a tighter one for POST /auth/*. Uses app.state.rate_limiter."""

    def __init__(self, app, general_limit: int, auth_limit: int):
        super().__init__(app)
        self.general, self.auth = general_limit, auth_limit

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in UNLIMITED_PATHS:
            return await call_next(request)
        limiter = request.app.state.rate_limiter
        is_auth = path.startswith("/api/v1/auth/") and request.method == "POST"
        bucket, limit = ("auth", self.auth) if is_auth else ("api", self.general)
        if not limiter.allow(bucket, client_ip(request), limit):
            if (m := getattr(request.app.state, "metrics", None)) is not None:
                m.inc("atlas_rate_limited_total", bucket=bucket)
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}, headers={"Retry-After": "60"})
        return await call_next(request)


DOCS_PATHS = ("/api/docs", "/api/openapi.json", "/api/docs/oauth2-redirect")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """API responses are JSON/CSV/PDF, never pages: forbid framing, sniffing, referrers and any active content.
    Responses to signed-in requests are not stored by browsers or shared caches."""

    def __init__(self, app, hsts: bool):
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if not request.url.path.startswith(DOCS_PATHS):  # Swagger UI needs scripts from its CDN
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if "atlas_session" in request.cookies or request.url.path.startswith("/api/v1/auth/"):
            h.setdefault("Cache-Control", "no-store")
        if self.hsts:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class BodySizeLimitMiddleware:
    """Pure ASGI: reject request bodies over `max_bytes` with 413 before the app (or JSON parser) sees them.
    Checks Content-Length up front and counts streamed (chunked) bodies, buffering at most `max_bytes`."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None:
            try:
                too_big = int(length) > self.max_bytes
            except ValueError:
                too_big = True
            if too_big:
                return await self._reject(scope, receive, send)
            return await self.app(scope, receive, send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                return await self._reject(scope, receive, send)
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)

    async def _reject(self, scope, receive, send):
        response = JSONResponse(status_code=413, content={"detail": f"Request body exceeds {self.max_bytes} bytes"})
        await response(scope, receive, send)
