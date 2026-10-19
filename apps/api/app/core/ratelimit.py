"""Rate limiting. Redis when ATLAS_REDIS_URL is set (shared by every API instance), otherwise per-process memory.

Interface used everywhere: `allow` (consume one unit if under the limit), `hit` (count an event), `count`, `reset`.
Redis uses fixed windows (INCR + EXPIRE in one transaction): cheap and atomic, at most a 2x burst at a window edge.
If Redis is unreachable the limiter falls back to memory for that call (limits stay enforced per process), logs a
warning at most once a minute, and counts `atlas_ratelimit_backend_errors_total`.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

log = logging.getLogger("atlas.ratelimit")


class MemoryRateLimiter:
    """Sliding window per (bucket, key). Exact, but per process."""

    backend = "memory"

    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self.hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _window(self, bucket: str, key: str, window: float) -> deque[float]:
        now = self.clock()
        q = self.hits[(bucket, key)]
        while q and now - q[0] > window:
            q.popleft()
        return q

    def allow(self, bucket: str, key: str, limit: int, window: float = 60.0) -> bool:
        q = self._window(bucket, key, window)
        if len(q) >= limit:
            return False
        q.append(self.clock())
        return True

    def hit(self, bucket: str, key: str, window: float = 60.0) -> int:
        q = self._window(bucket, key, window)
        q.append(self.clock())
        return len(q)

    def count(self, bucket: str, key: str, window: float = 60.0) -> int:
        return len(self._window(bucket, key, window))

    def reset(self, bucket: str, key: str) -> None:
        self.hits.pop((bucket, key), None)

    def ping(self) -> bool:
        return True


class RedisRateLimiter:
    backend = "redis"

    def __init__(self, client, prefix: str = "atlas:rl", metrics=None, clock=time.time) -> None:
        self.r, self.prefix, self.metrics, self.clock = client, prefix, metrics, clock
        self.fallback = MemoryRateLimiter()
        self._last_warn = float("-inf")

    def _key(self, bucket: str, key: str, window: float) -> str:
        return f"{self.prefix}:{bucket}:{int(window)}:{key}:{int(self.clock() // window)}"

    def _failed(self, exc: Exception) -> None:
        if self.metrics:
            self.metrics.inc("atlas_ratelimit_backend_errors_total")
        if self.clock() - self._last_warn > 60:
            self._last_warn = self.clock()
            log.warning("redis rate limiter unavailable, using per-process fallback: %s", exc)

    def hit(self, bucket: str, key: str, window: float = 60.0) -> int:
        k = self._key(bucket, key, window)
        try:
            pipe = self.r.pipeline(transaction=True)
            pipe.incr(k)
            pipe.expire(k, int(window) + 1)
            return int(pipe.execute()[0])
        except Exception as exc:  # redis.RedisError, OSError: the limiter must never fail the request
            self._failed(exc)
            return self.fallback.hit(bucket, key, window)

    def allow(self, bucket: str, key: str, limit: int, window: float = 60.0) -> bool:
        return self.hit(bucket, key, window) <= limit

    def count(self, bucket: str, key: str, window: float = 60.0) -> int:
        try:
            return int(self.r.get(self._key(bucket, key, window)) or 0)
        except Exception as exc:
            self._failed(exc)
            return self.fallback.count(bucket, key, window)

    def reset(self, bucket: str, key: str) -> None:
        try:
            for k in self.r.scan_iter(match=f"{self.prefix}:{bucket}:*:{key}:*"):
                self.r.delete(k)
        except Exception as exc:
            self._failed(exc)
        self.fallback.reset(bucket, key)

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception:
            return False


def build_limiter(redis_url: str | None, metrics=None) -> MemoryRateLimiter | RedisRateLimiter:
    if not redis_url:
        return MemoryRateLimiter()
    import redis  # lazily: only needed when configured

    client = redis.Redis.from_url(redis_url, socket_timeout=0.25, socket_connect_timeout=0.25)
    return RedisRateLimiter(client, metrics=metrics)
