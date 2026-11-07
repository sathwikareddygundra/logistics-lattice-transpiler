"""Builds nlu/fewshot.json: 10 domain examples per intent family (T-23), drawn from the
hand-labeled set and rendered with the verified parser output."""

import json
from datetime import date
from pathlib import Path

from nlu.evaluation import EVAL_TODAY, entity_set, load_dataset
from nlu.parser import parse

PER_INTENT = 10


def build(today: date = EVAL_TODAY) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in load_dataset():
        intent = parse(row["query"], today)
        if intent.intent_type.value != row["intent"] or entity_set(intent) != set(row["entities"]):
            continue  # only verified examples
        bucket = out.setdefault(row["intent"], [])
        if len(bucket) < PER_INTENT:
            data = intent.model_dump(mode="json", exclude_defaults=True)
            for k in ("query", "entity_confidence", "missing_slots"):
                data.pop(k, None)
            bucket.append({"query": row["query"], "output": data})
    return out


if __name__ == "__main__":
    path = Path(__file__).resolve().parent.parent / "nlu" / "fewshot.json"
    data = build()
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    print({k: len(v) for k, v in data.items()})
