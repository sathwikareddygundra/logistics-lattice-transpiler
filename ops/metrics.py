"""Tiny in-process metrics registry with Prometheus text output (T-98)."""

from __future__ import annotations

import threading

FAILURE_CATEGORIES = (
    "syntax_error",
    "semantic_mismatch",
    "intent_mismatch",
    "timeout",
    "resource_limit",
    "permission",
    "schema_drift",
)
# Upper bounds in milliseconds; +Inf is added on render.
LATENCY_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000)

STAGE_LATENCY = "lattice_stage_latency_ms"
QUERIES_TOTAL = "lattice_queries_total"
CONFIRM_TRIGGERED = "lattice_confirm_triggered_total"
FAILURES_TOTAL = "lattice_failures_total"

LabelKey = tuple[tuple[str, str], ...]


def _key(labels: dict[str, str] | None) -> LabelKey:
    return tuple(sorted((labels or {}).items()))


def _fmt(name: str, key: LabelKey, extra: tuple[tuple[str, str], ...] = ()) -> str:
    pairs = key + extra
    if not pairs:
        return name
    body = ",".join(f'{k}="{v}"' for k, v in pairs)
    return f"{name}{{{body}}}"


class Counter:
    def __init__(self, name: str, help_text: str = "") -> None:
        self.name, self.help = name, help_text
        self._values: dict[LabelKey, float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1, labels: dict[str, str] | None = None) -> None:
        if amount < 0:
            raise ValueError("counters only go up")
        with self._lock:
            k = _key(labels)
            self._values[k] = self._values.get(k, 0) + amount

    def value(self, labels: dict[str, str] | None = None) -> float:
        return self._values.get(_key(labels), 0)

    def items(self) -> dict[LabelKey, float]:
        with self._lock:
            return dict(self._values)


class Histogram:
    def __init__(
        self, name: str, help_text: str = "", buckets: tuple[float, ...] = LATENCY_BUCKETS_MS
    ) -> None:
        self.name, self.help, self.buckets = name, help_text, tuple(sorted(buckets))
        self._data: dict[LabelKey, dict] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            d = self._data.setdefault(
                _key(labels), {"counts": [0] * len(self.buckets), "sum": 0.0, "count": 0}
            )
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    d["counts"][i] += 1
            d["sum"] += value
            d["count"] += 1

    def items(self) -> dict[LabelKey, dict]:
        with self._lock:
            return {k: {**v, "counts": list(v["counts"])} for k, v in self._data.items()}

    def quantile(self, q: float, labels: dict[str, str] | None = None) -> float | None:
        """Estimate from bucket counts: the smallest bucket bound covering fraction q."""
        d = self._data.get(_key(labels))
        if not d or d["count"] == 0:
            return None
        for bound, c in zip(self.buckets, d["counts"], strict=True):
            if c >= q * d["count"]:
                return float(bound)
        return float("inf")


class Registry:
    def __init__(self) -> None:
        self.stage_latency = Histogram(STAGE_LATENCY, "Per-stage latency in milliseconds")
        self.queries = Counter(QUERIES_TOTAL, "Queries by final status")
        self.confirm = Counter(CONFIRM_TRIGGERED, "Times the confirm step asked the user")
        self.failures = Counter(FAILURES_TOTAL, "Failures by category")

    def observe_stage(self, stage: str, ms: float) -> None:
        self.stage_latency.observe(ms, {"stage": stage})

    def record_query(self, status: str) -> None:
        self.queries.inc(labels={"status": status})

    def record_confirm(self) -> None:
        self.confirm.inc()

    def record_failure(self, category: str) -> None:
        if category not in FAILURE_CATEGORIES:
            raise ValueError(
                f"unknown failure category {category!r}; use one of {FAILURE_CATEGORIES}"
            )
        self.failures.inc(labels={"category": category})

    def snapshot(self) -> dict:
        """Plain-dict view used by alerts and rollout gates."""
        qs = {dict(k)["status"]: v for k, v in self.queries.items().items()}
        total = sum(qs.values())
        fails = {dict(k)["category"]: v for k, v in self.failures.items().items()}
        stages = {}
        for k in self.stage_latency.items():
            stage = dict(k)["stage"]
            stages[stage] = {
                "count": self.stage_latency.items()[k]["count"],
                "p50": self.stage_latency.quantile(0.5, dict(k)),
                "p95": self.stage_latency.quantile(0.95, dict(k)),
                "p99": self.stage_latency.quantile(0.99, dict(k)),
            }
        return {
            "queries_total": total,
            "queries_by_status": qs,
            "confirm_triggered": self.confirm.value(),
            "failures_by_category": fails,
            "failures_total": sum(fails.values()),
            "stage_latency_ms": stages,
        }

    def render_prometheus(self) -> str:
        lines: list[str] = []
        for c in (self.queries, self.confirm, self.failures):
            lines += [f"# HELP {c.name} {c.help}", f"# TYPE {c.name} counter"]
            items = c.items() or {(): 0}
            for k, v in sorted(items.items()):
                lines.append(f"{_fmt(c.name, k)} {v:g}")
        h = self.stage_latency
        lines += [f"# HELP {h.name} {h.help}", f"# TYPE {h.name} histogram"]
        for k, d in sorted(h.items().items()):
            for bound, count in zip(h.buckets, d["counts"], strict=True):
                lines.append(f"{_fmt(h.name + '_bucket', k, (('le', f'{bound:g}'),))} {count}")
            lines.append(f"{_fmt(h.name + '_bucket', k, (('le', '+Inf'),))} {d['count']}")
            lines.append(f"{_fmt(h.name + '_sum', k)} {d['sum']:g}")
            lines.append(f"{_fmt(h.name + '_count', k)} {d['count']}")
        return "\n".join(lines) + "\n"


REGISTRY = Registry()


def snapshot() -> dict:
    return REGISTRY.snapshot()


def render_prometheus() -> str:
    return REGISTRY.render_prometheus()
