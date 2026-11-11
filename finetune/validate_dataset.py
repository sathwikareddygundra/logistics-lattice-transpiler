"""Check every generated label by running it through the real pipeline.

A row passes when its JSON becomes a valid ParsedIntent and the pipeline returns `ok`
(or `out_of_scope` for out-of-scope rows). Run: uv run python finetune/validate_dataset.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import structlog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nlu.intent import ParsedIntent  # noqa: E402
from pipeline import answer  # noqa: E402
from plantdb.plants import build_plant_databases  # noqa: E402

DATA = Path(__file__).parent / "data"


def check(row: dict, dbs: dict) -> tuple[bool, str]:
    q = row["messages"][1]["content"]
    target = json.loads(row["messages"][2]["content"])
    try:
        intent = ParsedIntent.model_validate({**target, "query": q, "confidence": 1.0})
    except ValueError as e:
        return False, f"invalid intent: {e}"
    want = "out_of_scope" if target["intent_type"] == "out_of_scope" else "ok"
    if want == "out_of_scope":
        return True, ""
    res = answer(
        q, dbs, today=date.fromisoformat(row["meta"]["today"]), intent=intent, confirmed=True
    )
    if res.status != want:
        return False, f"{res.status}: {res.message[:120]}"
    if res.frame is None:
        return False, "no result"
    # A date range outside the data (e.g. "this month" when today is in October) is a correct
    # label that legitimately returns no rows; anything else empty is suspicious.
    has_dates = any(f["column"] == "dispatch_date" for f in target.get("filters", []))
    if res.frame.empty and not has_dates:
        return False, "empty result without a date filter"
    return True, ""


def main() -> int:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(50))
    rows = [
        json.loads(line)
        for name in ("train", "val")
        for line in (DATA / f"{name}.jsonl").read_text().splitlines()
    ]
    with tempfile.TemporaryDirectory() as tmp:
        dbs = build_plant_databases(Path(tmp))
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda r: check(r, dbs), rows))
    bad = [(r, why) for r, (ok, why) in zip(rows, results, strict=True) if not ok]
    print(f"{len(rows) - len(bad)}/{len(rows)} rows pass")
    for why, n in Counter(w.split(":")[0] for _, w in bad).most_common(8):
        print(f"  {n:5d}  {why}")
    for r, why in bad[:10]:
        print("  ", r["messages"][1]["content"], "|", why)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
