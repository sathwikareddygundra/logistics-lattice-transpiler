import json
from datetime import date

from nlu.tuned import parse_tuned

TODAY = date(2026, 9, 15)
GOOD = json.dumps(
    {
        "intent_type": "aggregation",
        "metrics": [{"column": "freight_cost_usd", "aggregation": "sum"}],
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
