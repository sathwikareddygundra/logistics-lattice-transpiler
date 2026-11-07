"""CI gate (T-25): intent accuracy and entity F1 on the hand-labeled set, plus the
confidence outputs promised by T-21."""

from datetime import date

from nlu.evaluation import (
    MIN_ENTITY_F1,
    MIN_INTENT_ACCURACY,
    calibration_table,
    evaluate,
    load_dataset,
)
from nlu.parser import parse
from nlu.taxonomy import IntentType


def test_dataset_is_large_and_covers_every_intent():
    rows = load_dataset()
    assert len(rows) >= 100
    assert {r["intent"] for r in rows} == {i.value for i in IntentType}


def test_intent_accuracy_gate():
    res = evaluate()
    assert res.intent_accuracy >= MIN_INTENT_ACCURACY, res.misses[:5]


def test_entity_f1_gate():
    res = evaluate()
    assert res.entity_f1 >= MIN_ENTITY_F1, res.misses[:5]


def test_every_parse_emits_overall_and_per_entity_confidence():
    for row in load_dataset():
        intent = parse(row["query"], date(2026, 9, 15))
        assert 0.0 <= intent.confidence <= 1.0
        if intent.intent_type is not IntentType.OUT_OF_SCOPE:
            assert intent.entity_confidence
            assert all(0.0 <= v <= 1.0 for v in intent.entity_confidence.values())


def test_confident_parses_are_usually_right():
    """Calibration sanity: the top confidence bin must be at least 90% exactly right."""
    top = [row for row in calibration_table(evaluate()) if row[0].startswith("0.8")]
    assert top and top[0][2] >= 0.9
