"""Convert expert-written questions (finetune/data/human_raw.jsonl) into eval_human.jsonl.

Expert labels use CSV column names and "=" operators; this maps them to ParsedIntent fields.
Questions whose label does not fit the intent taxonomy (see SKIP) are written to human_skipped.jsonl and left out, not silently relabelled.
Run: uv run python finetune/build_human_eval.py   then score like any other split.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

from build_dataset import system_prompt  # noqa: E402

DATA = Path(__file__).parent / "data"
TODAY = date(2026, 9, 15)
OPS = {"=": "eq", "!=": "ne", "gte": "gte", "lt": "lt", "lte": "lte", "gt": "gt"}


SELECT = [
    "invoice_number",
    "dispatch_date",
    "origin_warehouse",
    "destination_city",
    "carrier",
    "current_status",
]
# Expert labels our taxonomy cannot express (or that are wrong for this app): left out, not relabelled.
SKIP = (
    "percentage",  # no percentage measure
    "shipments and total freight cost",  # two measures in one question
    "actual delivery happened after promised",  # column-vs-column comparison
    "checkpoint after dispatch",  # timestamp arithmetic
    "compare dispatch performance for MCW",  # plants are supported here; the expert did not know
)
DATE_COLS = ("dispatch_date", "checkpoint_timestamp")


def _granularity(q: str) -> str:
    q = q.lower()
    if re.search(r"\bdaily\b|\bday\b", q):
        return "day"
    return "week" if "week" in q else "month"


def to_gold(r: dict) -> dict | None:
    q, kind = r["query"], r["intent_type"]
    if any(k in q for k in SKIP) or r.get("ambiguous"):
        return None
    if kind == "aggregation" and any(g.lower().endswith("date") for g in r["group_by"]):
        return None
    if kind == "out_of_scope":
        return {"intent_type": "out_of_scope"}
    out: dict = {"intent_type": kind}
    filters, keep = [], {}
    for f in r["filters"]:
        col = f["column"].lower()
        if f["op"] == "in":
            keep[col] = f["value"].split(",")
        else:
            filters.append({"column": col, "operator": OPS[f["op"]], "value": f["value"]})
    out["filters"] = filters
    if keep:
        out["keep_values"] = keep
    if kind == "join":
        out.update(limit=20, select_columns=SELECT)
        return out
    out["metric"], out["agg"] = r["metric_column"].lower(), r["aggregation"]
    group = [g.lower() for g in r["group_by"]]
    if kind in ("trend", "forecast"):
        out["time_column"] = next(g for g in group if g in DATE_COLS)
        group = [g for g in group if g not in DATE_COLS]
        out["granularity"] = "month" if kind == "forecast" else _granularity(q)
        out["sort_direction"] = "asc"
        if kind == "forecast":
            out["horizon"] = 3
    if group:
        out["group_by"] = group
    if kind == "rank":
        low = re.search(r"bottom|fewest|shortest|lowest|least|cheapest", q.lower())
        out["sort_direction"] = "asc" if low else "desc"
        n = re.search(r"(?:top|bottom|show the)\s+(\d+)", q.lower())
        if n:
            out["limit"] = int(n.group(1))
        elif re.match(r"(which|who)\b", q.lower()):
            out["limit"] = 1
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
