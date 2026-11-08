"""Load test (T-95): run labeled queries through answer() at several concurrency levels.

Usage: uv run python loadtest/run_loadtest.py [--queries 300] [--levels 1 4 8]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import structlog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import answer  # noqa: E402
from plantdb.plants import build_plant_databases  # noqa: E402

P95_TARGET_MS = 2000
TARGET_CONCURRENCY = 4


def load_queries() -> list[str]:
    rows = (ROOT / "nlu/data/labeled_queries.jsonl").read_text().splitlines()
    parsed = [json.loads(r) for r in rows if r.strip()]
    return [r["query"] for r in parsed if r["intent"] != "out_of_scope"]


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def run(level: int, queries: list[str], dbs) -> dict:
    def one(q: str) -> tuple[float, str, str]:
        t0 = time.perf_counter()
        try:
            res = answer(q, dbs, today=date(2026, 9, 15))
            return (time.perf_counter() - t0) * 1000, res.status, ""
        except Exception as e:  # recorded, never raised: the point is to count them
            return (time.perf_counter() - t0) * 1000, "exception", f"{type(e).__name__}: {e}"

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=level) as pool:
        out = list(pool.map(one, queries))
    wall = time.perf_counter() - t0
    lat = [o[0] for o in out]
    return {
        "concurrency": level,
        "queries": len(queries),
        "p50_ms": round(statistics.median(lat), 1),
        "p95_ms": round(pct(lat, 0.95), 1),
        "p99_ms": round(pct(lat, 0.99), 1),
        "qps": round(len(queries) / wall, 2),
        "wall_s": round(wall, 1),
        "statuses": dict(Counter(o[1] for o in out)),
        "exceptions": [o[2] for o in out if o[2]][:5],
        "exception_count": sum(1 for o in out if o[2]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=300)
    ap.add_argument("--levels", type=int, nargs="+", default=[1, 4, 8])
    args = ap.parse_args()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(50))
    base = load_queries()
    queries = [base[i % len(base)] for i in range(args.queries)]
    with tempfile.TemporaryDirectory() as tmp:
        dbs = build_plant_databases(Path(tmp))
        results = [run(level, queries, dbs) for level in args.levels]
    print(json.dumps(results, indent=2))
    by = {r["concurrency"]: r for r in results}
    if 8 in by:
        print("zero exceptions at 8:", by[8]["exception_count"] == 0)
    if TARGET_CONCURRENCY in by:
        print(
            f"p95 at {TARGET_CONCURRENCY} < {P95_TARGET_MS} ms:",
            by[TARGET_CONCURRENCY]["p95_ms"] < P95_TARGET_MS,
        )


if __name__ == "__main__":
    main()
