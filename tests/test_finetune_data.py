import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "finetune"))

import build_dataset  # noqa: E402

from nlu.intent import ParsedIntent  # noqa: E402


def test_generation_is_deterministic_and_labels_are_valid():
    a_train, a_val, _ = build_dataset.build(120, 30)
    b_train, b_val, _ = build_dataset.build(120, 30)
    assert a_train == b_train and a_val == b_val
    assert len(a_train) == 120 and len(a_val) == 30
    for row in a_train + a_val:
        q = row["messages"][1]["content"]
        target = json.loads(row["messages"][2]["content"])
        ParsedIntent.model_validate({**target, "query": q, "confidence": 1.0})


def test_validation_phrasings_never_appear_in_training():
    train, val, _ = build_dataset.build(300, 60)
    assert {r["messages"][1]["content"].lower() for r in train}.isdisjoint(
        r["messages"][1]["content"].lower() for r in val
    )
    assert all(r["meta"]["heldout_phrasing"] for r in val)
    assert not any(r["meta"]["heldout_phrasing"] for r in train)
