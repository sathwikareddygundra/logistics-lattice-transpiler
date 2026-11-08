"""Rollout order and the gates a plant must pass before the next one goes live (T-97)."""

from __future__ import annotations

ROLLOUT_ORDER = ("MCW", "YCW", "VGU")
"""MCW first: SQLite, simplest engine, so problems show up where they are cheapest to fix.
YCW (DuckDB) second, VGU (PostgreSQL, a real server) last."""

MIN_QUERIES = 200
"""Fewer queries than this tells us nothing; at 200 a 2% failure rate is about 4 events."""

MAX_FAILURE_RATE = 0.02
"""At most 2% of queries may end in a failure. Our e2e suite runs at 0%, so 2% leaves
room for odd phrasing without hiding a regression."""

MAX_P95_MS = 2000
"""Same bar as the load test (T-95): p95 under 2000 ms for any stage."""

ROW_COUNT_MISMATCH_FACTOR = 10
"""From T-86: a result whose row count differs from the cost estimate by 10x or more
is suspect, and blocks promotion."""

MAX_ROW_MISMATCHES = 0
"""Any such mismatch blocks advancing the plant."""


def may_advance(snapshot: dict, plant: str) -> tuple[bool, list[str]]:
    """Decide whether `plant` may move on, given a metrics snapshot. Returns reasons for a no."""
    if plant not in ROLLOUT_ORDER:
        raise ValueError(f"unknown plant {plant!r}; rollout order is {ROLLOUT_ORDER}")
    reasons: list[str] = []
    total = snapshot.get("queries_total", 0)
    if total < MIN_QUERIES:
        reasons.append(f"only {total} queries seen, need at least {MIN_QUERIES}")
    if total:
        rate = snapshot.get("failures_total", 0) / total
        if rate > MAX_FAILURE_RATE:
            reasons.append(f"failure rate {rate:.1%} is above {MAX_FAILURE_RATE:.0%}")
    for stage, s in snapshot.get("stage_latency_ms", {}).items():
        p95 = s.get("p95")
        if p95 is not None and p95 > MAX_P95_MS:
            reasons.append(f"{stage} p95 {p95:g} ms is above {MAX_P95_MS} ms")
    mism = snapshot.get("row_count_mismatches", 0)
    if mism > MAX_ROW_MISMATCHES:
        reasons.append(
            f"{mism} results differed from the estimate by {ROW_COUNT_MISMATCH_FACTOR}x or more"
        )
    return (not reasons, reasons)
