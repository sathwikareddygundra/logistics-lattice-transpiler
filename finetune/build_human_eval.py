"""Convert expert-written questions (finetune/data/human_raw.jsonl) into eval_human.jsonl.

Expert labels use CSV column names and "=" operators; this maps them to ParsedIntent fields.
Questions whose label does not fit the intent taxonomy (a monthly breakdown is a `trend` here, with
a granularity) are written to human_skipped.jsonl and left out, not silently relabelled.
Run: uv run python finetune/build_human_eval.py   then score like any other split.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

from build_dataset import system_prompt  # noqa: E402

DATA = Path(__file__).parent / "data"
TODAY = date(2026, 9, 15)
OPS = {"=": "eq", "!=": "ne", "gte": "gte", "lt": "lt", "lte": "lte", "gt": "gt", "in": "in"}


def to_gold(r: dict) -> dict | None:
    if r["intent_type"] == "aggregation" and any(g.lower().endswith("date") for g in r["group_by"]):
        return None
    out: dict = {"intent_type": r["intent_type"]}
    if r.get("metric_column"):
        out["metric"] = r["metric_column"].lower()
        out["agg"] = r["aggregation"]
    if r["group_by"]:
        out["group_by"] = [g.lower() for g in r["group_by"]]
    out["filters"] = [
        {"column": f["column"].lower(), "operator": OPS[f["op"]], "value": f["value"]}
        for f in r["filters"]
    ]
    return out


def main() -> None:
    rows = [json.loads(x) for x in (DATA / "human_raw.jsonl").read_text().splitlines() if x.strip()]
    kept, skipped = [], []
    for r in rows:
        gold = to_gold(r)
        if gold is None:
            skipped.append(r)
            continue
        kept.append(
            {
                "messages": [
                    {"role": "system", "content": system_prompt(TODAY)},
                    {"role": "user", "content": r["query"]},
                    {"role": "assistant", "content": json.dumps(gold, sort_keys=True)},
                ],
                "meta": {"today": TODAY.isoformat()},
            }
        )
    (DATA / "eval_human.jsonl").write_text("".join(json.dumps(r) + "\n" for r in kept))
    (DATA / "human_skipped.jsonl").write_text("".join(json.dumps(r) + "\n" for r in skipped))
    print(f"kept {len(kept)}, skipped {len(skipped)}")


if __name__ == "__main__":
    main()
