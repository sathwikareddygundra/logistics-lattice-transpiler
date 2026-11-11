"""Phase 3 pieces: entities, slots, fallback, prompts, few-shot, hybrid routing."""

import json
from datetime import date
from types import SimpleNamespace

import pytest

from common.groq_client import GroqClientError
from nlu.entities import extract, resolve_dates
from nlu.fallback import decline, log_fallback
from nlu.groq_parser import (
    PROMPT_VERSION,
    GroqParseError,
    build_system_prompt,
    parse_with_groq,
)
from nlu.hybrid import parse_hybrid
from nlu.intent import IntentType, ParsedIntent
from nlu.parser import parse
from nlu.slots import fill_slots, next_question
from nlu.taxonomy import IntentType as TaxonomyIntent

TODAY = date(2026, 9, 15)
HERE = __import__("pathlib").Path(__file__).resolve().parent.parent / "nlu"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("last month", (date(2026, 8, 1), date(2026, 9, 1))),
        ("this month", (date(2026, 9, 1), date(2026, 10, 1))),
        ("last quarter", (date(2026, 4, 1), date(2026, 7, 1))),
        ("in July 2026", (date(2026, 7, 1), date(2026, 8, 1))),
        ("Q3 2026", (date(2026, 7, 1), date(2026, 10, 1))),
        ("last 30 days", (date(2026, 8, 16), date(2026, 9, 16))),
        ("from June to August", (date(2026, 6, 1), date(2026, 9, 1))),
        ("in 2026", (date(2026, 1, 1), date(2027, 1, 1))),
        ("last year", (date(2025, 1, 1), date(2026, 1, 1))),
    ],
)
def test_calendar_date_expressions(text, expected):
    assert resolve_dates(text, TODAY) == expected


def test_fiscal_conventions_differ_from_calendar():
    assert resolve_dates("FY25", TODAY) == (date(2024, 4, 1), date(2025, 4, 1))
    assert resolve_dates("FY26 Q1", TODAY) == (date(2025, 4, 1), date(2025, 7, 1))
    assert resolve_dates("Q1 2026", TODAY) == (date(2026, 1, 1), date(2026, 4, 1))


def test_may_the_verb_is_not_the_month():
    assert resolve_dates("which carriers may be late", TODAY) is None
    assert resolve_dates("in May 2026", TODAY) == (date(2026, 5, 1), date(2026, 6, 1))


@pytest.mark.parametrize(
    "text,plant",
    [
        ("MCW", "MCW"),
        ("mcw", "MCW"),
        ("Mellacheruvu", "MCW"),
        ("ycw", "YCW"),
        ("Yerraguntla", "YCW"),
        ("VGU", "VGU"),
    ],
)
def test_every_known_plant_alias_resolves(text, plant):
    assert extract(f"total weight for {text}", TODAY).plants == [plant]


@pytest.mark.parametrize(
    "text,column,value",
    [
        ("fedx", "carrier", "FedEx"),
        ("jbhunt", "carrier", "JB Hunt"),
        ("xpo", "carrier", "XPO Logistics"),
        ("chicgo", "origin_warehouse", "Chicago_WH"),
        ("los angeles", "origin_warehouse", "LA_WH"),
        ("Dalas", "origin_warehouse", "Dallas_WH"),
        ("Houstan", "destination_city", "Houston"),
    ],
)
def test_aliases_and_misspellings_resolve_to_one_identifier(text, column, value):
    got = {(f.column, f.value) for f in extract(f"freight from {text}", TODAY).filters}
    assert (column, value) in got


def test_sla_vs_tracking_delayed_disambiguation():
    assert any(f.column == "sla_status" for f in extract("sla breaches", TODAY).filters)
    assert any(f.column == "current_status" for f in extract("delayed shipments", TODAY).filters)


def test_missing_slot_asks_exactly_one_targeted_question():
    intent = parse("top 3 carriers", TODAY)
    assert intent.missing_slots == ["metric"]
    q = next_question(intent)
    assert q is not None and q.startswith("Which measure")


def test_slot_answer_completes_the_query_and_keeps_earlier_slots():
    intent = parse("top 3 carriers", TODAY)
    filled = fill_slots(intent, "freight cost", TODAY)
    assert filled.missing_slots == [] and filled.metric == "freight_cost_usd"
    assert filled.limit == 3 and filled.group_by == ["carrier"]  # not re-asked
    assert next_question(filled) is None
    with_filter = fill_slots(parse("show me dispatches", TODAY), "DHL in August", TODAY)
    assert {f.column for f in with_filter.filters} >= {"carrier", "dispatch_date"}
    assert with_filter.missing_slots == []


def test_required_slots_per_intent():
    assert parse("show me dispatches", TODAY).missing_slots == ["filter"]
    assert parse("compare freight cost", TODAY).missing_slots == ["dimension"]
    assert parse("forecast next 3 months", TODAY).missing_slots == ["metric"]
    assert parse("total freight cost", TODAY).missing_slots == []


def test_fallback_declines_with_suggestions_and_logs(tmp_path):
    fb = decline("optimise my delivery routes")
    assert "rephras" in fb.message and len(fb.suggestions) == 2
    log = tmp_path / "fb.jsonl"
    log_fallback("optimise my delivery routes", "trace-1", log)
    log_fallback("what is the weather", "trace-2", log)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["query"] for r in rows] == ["optimise my delivery routes", "what is the weather"]


def test_prompt_template_and_fewshot_are_version_controlled_files():
    assert (HERE / "prompts" / f"parse_intent.{PROMPT_VERSION}.txt").exists()
    fewshot = json.loads((HERE / "fewshot.json").read_text())
    assert set(fewshot) == {i.value for i in TaxonomyIntent}
    for intent, examples in fewshot.items():
        assert len(examples) >= 10, intent
    prompt = build_system_prompt(TODAY)
    assert "{" not in prompt.replace("{", "", 0) or "{{" not in prompt  # template fully formatted
    assert "2026-09-15" in prompt and "Atlanta_WH" in prompt


def test_every_fewshot_output_validates_and_matches_the_parser():
    fewshot = json.loads((HERE / "fewshot.json").read_text())
    for intent, examples in fewshot.items():
        for ex in examples:
            data = {**ex["output"], "query": ex["query"]}
            data.setdefault("confidence", 0.0)
            parsed = ParsedIntent.model_validate(data)
            assert parsed.intent_type.value == intent
            assert parse(ex["query"], TODAY).intent_type.value == intent


class _Fake:
    def __init__(self, content=None, error=None):
        self.content, self.error, self.calls = content, error, 0

    def chat_completion(self, model, messages, extra=None):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content)


GOOD = json.dumps(
    {
        "intent_type": "aggregation", "metric": "freight_cost_usd", "agg": "sum",
        "group_by": [], "filters": [{"column": "origin_warehouse", "operator": "eq", "value": "Atlanta"}],
        "confidence": 0.9,
    }
)  # fmt: skip


def test_groq_parser_validates_and_snaps_values_to_the_vocabulary():
    got = parse_with_groq("freight from atlanta", _Fake("```json\n" + GOOD + "\n```"), TODAY)
    assert got.filters[0].value == "Atlanta_WH"
    with pytest.raises(GroqParseError):
        parse_with_groq("x", _Fake("here you go!"), TODAY)
    with pytest.raises(GroqParseError):
        parse_with_groq("x", _Fake(json.dumps({"intent_type": "nonsense"})), TODAY)


def test_hybrid_uses_rules_when_confident_and_never_calls_the_model():
    client = _Fake(GOOD)
    res = parse_hybrid("total freight cost by carrier", TODAY, client)
    assert res.source == "rules" and client.calls == 0


def test_hybrid_asks_the_model_when_rules_give_up():
    client = _Fake(GOOD)
    res = parse_hybrid("how much money went out the door from atlanta", TODAY, client)
    assert client.calls == 1
    assert res.source == "llm" and res.intent.intent_type is IntentType.AGGREGATION


def test_hybrid_falls_back_to_rules_when_the_model_fails_or_declines():
    q = "gibberish zzz"
    assert (
        parse_hybrid(q, TODAY, _Fake(error=GroqClientError("429"))).source
        == "rules (llm unavailable)"
    )
    declined = json.dumps({"intent_type": "out_of_scope", "confidence": 0})
    assert parse_hybrid(q, TODAY, _Fake(declined)).source == "rules"
    assert parse_hybrid(q, TODAY, None).source == "rules"
