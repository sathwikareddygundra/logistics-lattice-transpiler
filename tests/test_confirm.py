"""Phase 4: confirm routing, yes/no hook, correction-aware re-parse, retry cap, logging."""

import json
from datetime import date
from types import SimpleNamespace

import pytest

from common.groq_client import GroqClientError
from confirm.client import (
    CONFIRM_MAX_RETRIES,
    CONFIRM_TIMEOUT_SECONDS,
    HOSTED_PATH_SLA_SECONDS,
    RULE_NLU_P95_SECONDS,
    make_confirm_client,
    worst_case_seconds,
)
from confirm.log import export_finetune, scrub
from confirm.loop import (
    MAX_CONFIRM_ATTEMPTS,
    Verdict,
    apply_correction,
    parse_reply,
    run_confirm_loop,
)
from confirm.paraphrase_llm import llm_paraphrase
from confirm.router import CONFIDENCE_THRESHOLD, paraphrase, route
from nlu.intent import IntentType, ParsedIntent
from nlu.parser import parse

TODAY = date(2026, 9, 15)


def _intent(conf: float) -> ParsedIntent:
    return ParsedIntent(query="q", intent_type=IntentType.OUT_OF_SCOPE, confidence=conf)


def test_threshold_boundary_is_inclusive():
    assert route(_intent(CONFIDENCE_THRESHOLD)).needs_confirmation is False
    assert route(_intent(CONFIDENCE_THRESHOLD - 0.001)).needs_confirmation is True
    assert route(_intent(1.0)).needs_confirmation is False
    assert route(_intent(0.0)).needs_confirmation is True


def test_paraphrase_reads_as_plain_language():
    text = paraphrase(parse("average TAT by carrier for DHL in August", TODAY))
    assert text.startswith("You want the average turnaround time (hours)")
    assert "broken down by carrier" in text and "carrier is DHL" in text
    assert "2026-08-01" in text and text.endswith("Is that right?")
    assert "_" not in text  # no raw column names


def test_confirm_timeout_budget_fits_the_sla():
    assert CONFIRM_TIMEOUT_SECONDS < make_confirm_client("k")._client.timeout.read + 1e-9 + 1
    assert RULE_NLU_P95_SECONDS + worst_case_seconds() <= HOSTED_PATH_SLA_SECONDS
    assert make_confirm_client("k")._max_retries == CONFIRM_MAX_RETRIES


def test_llm_paraphrase_falls_back_to_the_template():
    intent = parse("total freight cost by carrier", TODAY)

    class Broken:
        def chat_completion(self, *a, **k):
            raise GroqClientError("down")

    class Chatty:
        def chat_completion(self, *a, **k):
            return SimpleNamespace(content="Sure thing, here you go")  # not a question

    class Good:
        def chat_completion(self, *a, **k):
            return SimpleNamespace(content="Do you want total freight cost per carrier?")

    assert llm_paraphrase(intent, Broken()) == paraphrase(intent)
    assert llm_paraphrase(intent, Chatty()) == paraphrase(intent)
    assert llm_paraphrase(intent, Good()) == "Do you want total freight cost per carrier?"


@pytest.mark.parametrize(
    "reply,verdict,corr",
    [
        ("yes", Verdict.YES, ""),
        ("Y", Verdict.YES, ""),
        ("no: I meant freight cost", Verdict.NO, "I meant freight cost"),
        ("no, by carrier", Verdict.NO, "by carrier"),
        ("by warehouse please", Verdict.NO, "by warehouse please"),
        (None, Verdict.TIMEOUT, ""),
        ("   ", Verdict.TIMEOUT, ""),
    ],
)
def test_reply_parsing(reply, verdict, corr):
    r = parse_reply(reply)
    assert r.verdict is verdict and r.correction == corr


def test_correction_changes_the_next_parse_not_just_reruns_it():
    first = parse("total weight by carrier in August", TODAY)
    second = apply_correction(first, "I meant freight cost by warehouse", TODAY)
    assert first.metric == "shipment_weight_kg" and second.metric == "freight_cost_usd"
    assert second.group_by == ["origin_warehouse"]
    assert second.filters == first.filters  # untouched parts persist
    assert second.confidence >= CONFIDENCE_THRESHOLD


def test_yes_confirms_and_logs(tmp_path):
    log_file = tmp_path / "log.jsonl"
    intent = parse("total weight by carrier", TODAY)
    out = run_confirm_loop(intent, lambda q, n: "yes", TODAY, log_path=log_file, trace_id="t1")
    assert out.status == "confirmed" and out.attempts == 1
    assert json.loads(log_file.read_text())["verdict"] == "yes"


def test_no_response_cancels_gracefully(tmp_path):
    out = run_confirm_loop(
        parse("total weight", TODAY), lambda q, n: None, TODAY, log_path=tmp_path / "l.jsonl"
    )
    assert out.status == "cancelled"
    assert "No response" in out.message


def test_no_with_correction_is_applied(tmp_path):
    intent = parse("total weight by carrier", TODAY)
    out = run_confirm_loop(
        intent, lambda q, n: "no: freight cost", TODAY, log_path=tmp_path / "l.jsonl"
    )
    assert out.status == "confirmed"
    assert out.intent.metric == "freight_cost_usd"


def test_loop_terminates_at_the_cap_when_corrections_never_help(tmp_path):
    calls = []

    def stubborn(question, attempt):
        calls.append(attempt)
        return "no: gibberish nothing useful"

    out = run_confirm_loop(
        parse("total weight", TODAY), stubborn, TODAY, log_path=tmp_path / "l.jsonl"
    )
    assert out.status == "exhausted"
    assert len(calls) == MAX_CONFIRM_ATTEMPTS
    assert "couldn't pin down" in out.message and "Traceback" not in out.message


def test_log_scrubs_pii_and_exports_finetune_data(tmp_path):
    assert scrub("INV-2026-00042 driver DRV-4811 mail a@b.com call +1 555 123 4567") == (
        "<INVOICE> driver <DRIVER> mail <EMAIL> call <PHONE>"
    )
    log_file = tmp_path / "l.jsonl"
    run_confirm_loop(
        parse("show shipments for INV-2026-00042", TODAY), lambda q, n: "yes", TODAY,
        log_path=log_file, trace_id="abc",
    )  # fmt: skip
    raw = log_file.read_text()
    assert "INV-2026-00042" not in raw and "abc" not in raw
    out = tmp_path / "ft.jsonl"
    assert export_finetune(log_file, out) == 1
    example = json.loads(out.read_text())
    assert [m["role"] for m in example["messages"]] == ["user", "assistant"]
