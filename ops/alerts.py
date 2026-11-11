"""Alert rules (T-99). Thresholds come from ops.rollout so there is one source of numbers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ops import rollout


@dataclass(frozen=True)
class Alert:
    name: str
    severity: str  # "page" or "ticket"
    message: str


@dataclass(frozen=True)
class AlertRule:
    name: str
    severity: str
    check: Callable[[dict], str | None]  # returns a message when firing


def _failure_rate(s: dict) -> str | None:
    total = s.get("queries_total", 0)
    if (
        total >= rollout.MIN_QUERIES
        and s.get("failures_total", 0) / total > rollout.MAX_FAILURE_RATE
    ):
        return (
            f"failure rate {s['failures_total'] / total:.1%} above {rollout.MAX_FAILURE_RATE:.0%}"
        )
    return None


def _latency(s: dict) -> str | None:
    bad = [
        f"{st} p95 {v['p95']:g} ms"
        for st, v in s.get("stage_latency_ms", {}).items()
        if v.get("p95") is not None and v["p95"] > rollout.MAX_P95_MS
    ]
    return ", ".join(bad) + f" above {rollout.MAX_P95_MS} ms" if bad else None


def _schema_drift(s: dict) -> str | None:
    n = s.get("failures_by_category", {}).get("schema_drift", 0)
    return f"{n:g} schema_drift failures" if n else None


def _row_mismatch(s: dict) -> str | None:
    n = s.get("row_count_mismatches", 0)
    return (
        f"{n} results off by {rollout.ROW_COUNT_MISMATCH_FACTOR}x or more"
        if n > rollout.MAX_ROW_MISMATCHES
        else None
    )


RULES = (
    AlertRule("HighFailureRate", "page", _failure_rate),
    AlertRule("SlowStage", "page", _latency),
    AlertRule("SchemaDriftFailures", "page", _schema_drift),
    AlertRule("RowCountMismatch", "ticket", _row_mismatch),
)


def evaluate(snapshot: dict, rules: tuple[AlertRule, ...] = RULES) -> list[Alert]:
    alerts = []
    for rule in rules:
        msg = rule.check(snapshot)
        if msg:
            alerts.append(Alert(rule.name, rule.severity, msg))
    return alerts
