"""Minimal Prometheus text-format metrics (counters, histograms, scrape-time gauges). No external dependency.

Per process: with several workers, scrape each one or aggregate in Prometheus (`sum by (...)`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

LabelKey = tuple[tuple[str, str], ...]
DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


def _labels(labels: dict[str, str]) -> LabelKey:
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt(key: LabelKey, extra: dict[str, str] | None = None) -> str:
    items = list(key) + list((extra or {}).items())
    if not items:
        return ""
    return "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in items) + "}"


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


class Registry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._help: dict[str, tuple[str, str]] = {}
        self._counters: dict[str, dict[LabelKey, float]] = {}
        self._hist: dict[str, tuple[tuple[float, ...], dict[LabelKey, list[float]]]] = {}
        self._gauges: dict[str, Callable[[], Iterable[tuple[dict[str, str], float]]]] = {}

    def counter(self, name: str, help_: str) -> None:
        self._help[name] = ("counter", help_)
        self._counters.setdefault(name, {})

    def histogram(self, name: str, help_: str, buckets: tuple[float, ...] = DEFAULT_BUCKETS) -> None:
        self._help[name] = ("histogram", help_)
        self._hist.setdefault(name, (buckets, {}))

    def gauge(self, name: str, help_: str, collect: Callable[[], Iterable[tuple[dict[str, str], float]]]) -> None:
        """Gauge evaluated at scrape time; `collect` yields (labels, value)."""
        self._help[name] = ("gauge", help_)
        self._gauges[name] = collect

    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        key = _labels(labels)
        with self._lock:
            series = self._counters[name]
            series[key] = series.get(key, 0.0) + amount

    def observe(self, name: str, value: float, **labels: str) -> None:
        buckets, series = self._hist[name]
        key = _labels(labels)
        with self._lock:
            row = series.setdefault(key, [0.0] * (len(buckets) + 2))  # cumulative bucket counts..., sum, count
            for i, b in enumerate(buckets):
                if value <= b:
                    row[i] += 1
            row[-2] += value
            row[-1] += 1

    def value(self, name: str, **labels: str) -> float:
        """Counter value (tests and diagnostics)."""
        return self._counters.get(name, {}).get(_labels(labels), 0.0)

    def render(self) -> str:
        out: list[str] = []
        with self._lock:
            counters = {n: dict(s) for n, s in self._counters.items()}
            hists = {n: (b, {k: list(v) for k, v in s.items()}) for n, (b, s) in self._hist.items()}
        for name, (kind, help_) in self._help.items():
            out += [f"# HELP {name} {help_}", f"# TYPE {name} {kind}"]
            if kind == "counter":
                out += [f"{name}{_fmt(k)} {_num(v)}" for k, v in sorted(counters[name].items())]
            elif kind == "histogram":
                buckets, series = hists[name]
                for k, row in sorted(series.items()):
                    for i, b in enumerate(buckets):
                        out.append(f"{name}_bucket{_fmt(k, {'le': _num(b)})} {_num(row[i])}")
                    out.append(f"{name}_bucket{_fmt(k, {'le': '+Inf'})} {_num(row[-1])}")
                    out += [f"{name}_sum{_fmt(k)} {_num(row[-2])}", f"{name}_count{_fmt(k)} {_num(row[-1])}"]
            else:
                try:
                    for labels, v in self._gauges[name]():
                        out.append(f"{name}{_fmt(_labels(labels))} {_num(v)}")
                except Exception:  # a failing gauge must not break the whole scrape
                    out.append(f"# {name} unavailable")
        return "\n".join(out) + "\n"


def build_registry() -> Registry:
    r = Registry()
    r.counter("atlas_http_requests_total", "HTTP requests by method, route template and status code.")
    r.histogram("atlas_http_request_duration_seconds", "HTTP request latency by method and route template.")
    r.counter("atlas_http_errors_total", "Unhandled server errors (500) by route template.")
    r.counter("atlas_rate_limited_total", "Requests rejected by a rate limit, by bucket.")
    r.counter("atlas_ratelimit_backend_errors_total", "Redis errors; the limiter fell back to per-process memory.")
    r.counter("atlas_login_failures_total", "Failed logins, by outcome (denied, locked).")
    r.counter("atlas_ai_queries_total", "AI research queries by result (verification status or error).")
    r.counter("atlas_ai_tokens_total", "AI tokens by kind (input, output, cache_read, cache_creation).")
    return r
