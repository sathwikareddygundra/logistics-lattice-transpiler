"""Scoring the NLU against the hand-labeled set (T-21, T-25)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dag.dependencies import window_alias
from nlu.intent import ParsedIntent
from nlu.parser import parse

DATASET = Path(__file__).parent / "data" / "labeled_queries.jsonl"
EVAL_TODAY = date(2026, 9, 15)
MIN_INTENT_ACCURACY = 0.85
MIN_ENTITY_F1 = 0.9


def entity_set(intent: ParsedIntent) -> set[str]:
    out: set[str] = set()
    if intent.metric:
        out.add(f"metric:{intent.metric}")
    if intent.agg:
        out.add(f"agg:{intent.agg.value}")
    out |= {f"group:{g}" for g in intent.group_by}
    if intent.limit and not intent.is_row_listing:
        out.add(f"limit:{intent.limit}")
    if intent.granularity:
        out.add(f"gran:{intent.granularity.value}")
    if intent.horizon:
        out.add(f"horizon:{intent.horizon}")
    out |= {f"plant:{p}" for p in intent.plants}
    if intent.compare_by_plant:
        out.add("compare_plants")
    for col, values in intent.keep_values.items():
        out |= {f"keep:{col}={v}" for v in values}
    bounds: dict[str, dict[str, str]] = {}
    for f in intent.filters:
        if f.operator.value in ("gte", "lt"):
            bounds.setdefault(f.column, {})[f.operator.value] = str(f.value)
        else:
            out.add(f"filter:{f.column}={f.value}")
    for col, b in bounds.items():
        if {"gte", "lt"} <= b.keys():
            out.add(f"date:{col}:{b['gte']}..{b['lt']}")
    return out


@dataclass
class EvalResult:
    total: int = 0
    intent_correct: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    misses: list[dict] = field(default_factory=list)
    calibration: list[tuple[float, bool]] = field(default_factory=list)  # (confidence, correct)

    @property
    def intent_accuracy(self) -> float:
        return self.intent_correct / self.total

    @property
    def entity_f1(self) -> float:
        p = self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0
        r = self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0
        return 2 * p * r / (p + r) if p + r else 0.0


def load_dataset(path: Path = DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def evaluate(rows: list[dict] | None = None, today: date = EVAL_TODAY) -> EvalResult:
    res = EvalResult()
    for row in rows or load_dataset():
        got = parse(row["query"], today)
        want = set(row["entities"])
        have = entity_set(got)
        ok_intent = got.intent_type.value == row["intent"]
        res.total += 1
        res.intent_correct += ok_intent
        res.tp += len(want & have)
        res.fp += len(have - want)
        res.fn += len(want - have)
        exact = ok_intent and want == have
        res.calibration.append((got.confidence, exact))
        if not exact:
            res.misses.append(
                {
                    "query": row["query"],
                    "want": [row["intent"], sorted(want)],
                    "got": [got.intent_type.value, sorted(have)],
                }
            )
    return res


def calibration_table(res: EvalResult, bins: int = 5) -> list[tuple[str, int, float]]:
    """(bin label, count, observed accuracy). Calibrated means accuracy ~ mean confidence."""
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        pts = [ok for c, ok in res.calibration if lo <= c < hi or (i == bins - 1 and c == 1.0)]
        if pts:
            out.append((f"{lo:.1f}-{hi:.1f}", len(pts), sum(pts) / len(pts)))
    return out


__all__ = ["EvalResult", "calibration_table", "entity_set", "evaluate", "window_alias"]
