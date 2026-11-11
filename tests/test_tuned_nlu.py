import json
from datetime import date

from nlu.tuned import parse_tuned

TODAY = date(2026, 9, 15)
GOOD = json.dumps(
    {
        "intent_type": "aggregation",
        "metric": "freight_cost_usd",
        "agg": "sum",
        "group_by": ["carrier"],
        "filters": [],
    }
)


def test_valid_model_reply_is_used_with_fixed_confidence():
    r = parse_tuned("total freight cost by carrier", lambda m: GOOD, TODAY)
    assert r.source == "tuned"
    assert r.intent.confidence == 0.9
    assert r.intent.query == "total freight cost by carrier"


def test_bad_json_or_unreachable_model_falls_back_to_rules():
    assert parse_tuned("top 5 carriers by freight cost", lambda m: "nope", TODAY).source.startswith(
        "rules"
    )

    def boom(m):
        raise ConnectionError

    r = parse_tuned("top 5 carriers by freight cost", boom, TODAY)
    assert r.source.startswith("rules")
    assert r.intent.intent_type.value == "rank"


def test_incomplete_model_reply_falls_back_to_rules():
    # an aggregation with no `agg` used to crash the DAG builder with an AssertionError
    bad = json.dumps({"intent_type": "aggregation", "metric": "freight_cost_usd", "filters": []})
    r = parse_tuned(
        "which transporters charge more than the average haulage fees", lambda m: bad, TODAY
    )
    assert r.source.startswith("rules")


def test_pipeline_asks_for_missing_measure_instead_of_crashing(tmp_path):
    from nlu.intent import IntentType, ParsedIntent
    from pipeline import answer
    from plantdb.plants import build_plant_databases

    intent = ParsedIntent(
        query="q", intent_type=IntentType.AGGREGATION, metric="freight_cost_usd", confidence=0.9
    )
    res = answer("q", build_plant_databases(tmp_path), today=TODAY, intent=intent)
    assert res.status == "needs_slot"
