"""Score model predictions (and the rule parser) on the same questions.

Usage: uv run python finetune/score.py finetune/data/preds_<run>_<file>.jsonl
Metrics: valid JSON, intent accuracy, entity-set exact match, and (validation file only)
execution accuracy: the predicted intent and the gold intent return the same table.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nlu.evaluation import entity_set  # noqa: E402
from nlu.intent import ParsedIntent  # noqa: E402
from nlu.parser import parse  # noqa: E402
from pipeline import answer  # noqa: E402
from plantdb.plants import build_plant_databases  # noqa: E402


def to_intent(text: str, query: str) -> ParsedIntent | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return ParsedIntent.model_validate({**json.loads(text), "query": query, "confidence": 1.0})
    except ValueError:
        return None


def frame(intent: ParsedIntent | None, q: str, today: date, dbs: dict) -> pd.DataFrame | None:
    if intent is None or intent.intent_type.value == "out_of_scope":
        return None
    try:
        return answer(q, dbs, today=today, intent=intent, confirmed=True).frame
    except Exception:
        return None


def same_table(a: pd.DataFrame | None, b: pd.DataFrame | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return False
    key = list(a.columns)
    a2 = a.sort_values(key).reset_index(drop=True)
    b2 = b.sort_values(key).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(a2, b2, check_dtype=False, rtol=1e-6)
        return True
    except AssertionError:
        return False


def score(rows: list[dict], preds: list[str] | None, dbs: dict) -> dict:
    """preds=None scores the rule parser instead of a model."""
    n = valid = intent_ok = ent_ok = exec_ok = exec_n = 0
    misses: list[str] = []
    for i, row in enumerate(rows):
        q = row["messages"][1]["content"]
        today = date.fromisoformat(row["meta"]["today"])
        n += 1
        pred = parse(q, today=today) if preds is None else to_intent(preds[i], q)
        valid += pred is not None
        gold_type = (
            row.get("gold", {}).get("intent")
            or json.loads(row["messages"][2]["content"])["intent_type"]
        )
        ok_intent = pred is not None and pred.intent_type.value == gold_type
        intent_ok += ok_intent
        if "gold" in row:
            gold_ents = set(row["gold"]["entities"] or [])
            ent_ok += (
                pred is not None
                and ok_intent
                and (gold_type == "out_of_scope" or entity_set(pred) == gold_ents)
            )
        else:
            gold = ParsedIntent.model_validate(
                {**json.loads(row["messages"][2]["content"]), "query": q, "confidence": 1.0}
            )
            ent_ok += pred is not None and entity_set(pred) == entity_set(gold)
            exec_n += 1
            exec_ok += same_table(frame(pred, q, today, dbs), frame(gold, q, today, dbs))
        if not ok_intent and len(misses) < 8:
            misses.append(
                f"{q!r}: wanted {gold_type}, got {pred.intent_type.value if pred else 'invalid JSON'}"
            )
    out = {
        "n": n, "valid_json": valid / n, "intent_accuracy": intent_ok / n, "entity_exact": ent_ok / n,
        "examples_of_intent_misses": misses,
    }  # fmt: skip
    if exec_n:
        out["execution_accuracy"] = exec_ok / exec_n
    return out


def main() -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(50))
    path = Path(sys.argv[1])
    recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows, preds = [r["row"] for r in recs], [r["pred"] for r in recs]
    with tempfile.TemporaryDirectory() as tmp:
        dbs = build_plant_databases(Path(tmp))
        report = {"model": score(rows, preds, dbs), "rule_parser": score(rows, None, dbs)}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
