"""Yes/no hook, correction-aware re-parse and the bounded confirm loop (T-30, T-31, T-32)."""

from __future__ import annotations

import select
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from confirm import log
from confirm.router import CONFIDENCE_THRESHOLD, paraphrase
from nlu.intent import IntentType, ParsedIntent
from nlu.parser import parse

MAX_CONFIRM_ATTEMPTS = 2
GIVE_UP_MESSAGE = (
    "Sorry, I couldn't pin down your question after {n} tries. Please rephrase it with a "
    "measure (for example freight cost), a period and, if you want one, a grouping."
)
Responder = Callable[[str, int], str | None]  # (paraphrase, attempt) -> reply or None


class Verdict(StrEnum):
    YES = "yes"
    NO = "no"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class Response:
    verdict: Verdict
    correction: str = ""


def parse_reply(reply: str | None) -> Response:
    if reply is None or not reply.strip():
        return Response(Verdict.TIMEOUT)
    text = reply.strip()
    low = text.lower()
    if low in {"y", "yes", "yep", "yeah", "correct", "right", "ok", "okay"}:
        return Response(Verdict.YES)
    if low.startswith(("n", "wrong", "incorrect")):
        rest = text.split(":", 1)[1] if ":" in text else text.partition(",")[2]
        return Response(Verdict.NO, rest.strip())
    return Response(Verdict.NO, text)  # free text is treated as a correction


def stdin_responder(timeout_s: float = 30.0) -> Responder:
    """Interactive CLI responder that gives up (None) after `timeout_s` seconds."""

    def ask(question: str, attempt: int) -> str | None:
        print(f"{question} [yes / no: <correction>]", flush=True)
        ready, _, _ = select.select([sys.stdin], [], [], timeout_s)
        return sys.stdin.readline().strip() if ready else None

    return ask


def apply_correction(intent: ParsedIntent, correction: str, today: date | None) -> ParsedIntent:
    """Bias the next parse toward the user's correction: whatever the correction states
    overrides the old value; everything else is kept."""
    frag = parse(correction, today)
    if frag.intent_type is IntentType.OUT_OF_SCOPE and not frag.filters:
        return intent
    update: dict = {}
    if frag.metric:
        update["metric"] = frag.metric
    if frag.agg:
        update["agg"] = frag.agg
    if frag.group_by:
        update["group_by"] = frag.group_by
    if frag.granularity:
        update["granularity"] = frag.granularity
        update["time_column"] = frag.time_column
    if frag.limit and not frag.is_row_listing:
        update["limit"] = frag.limit
    if frag.plants:
        update["plants"] = frag.plants
    if frag.compare_by_plant:
        update["compare_by_plant"] = True
    if frag.filters:
        replaced = {f.column for f in frag.filters}
        update["filters"] = [f for f in intent.filters if f.column not in replaced] + frag.filters
    if frag.keep_values:
        update["keep_values"] = frag.keep_values
    if not update:
        return intent
    merged = intent.model_copy(update=update)
    if merged.metric and "metric" in merged.missing_slots:
        merged = merged.model_copy(
            update={"missing_slots": [s for s in merged.missing_slots if s != "metric"]}
        )
    # the user just told us what they mean, so confidence reflects that
    return merged.model_copy(update={"confidence": max(frag.confidence, 0.85)})


@dataclass
class LoopOutcome:
    status: str  # confirmed | cancelled | exhausted
    intent: ParsedIntent
    attempts: int
    message: str


def run_confirm_loop(
    intent: ParsedIntent,
    responder: Responder,
    today: date | None = None,
    max_attempts: int = MAX_CONFIRM_ATTEMPTS,
    trace_id: str = "-",
    log_path: Path | str | None = log.DEFAULT_LOG,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> LoopOutcome:
    current = intent
    for attempt in range(1, max_attempts + 1):
        text = paraphrase(current)
        resp = parse_reply(responder(text, attempt))
        nxt = apply_correction(current, resp.correction, today) if resp.correction else current
        if log_path is not None:
            log.record(
                trace_id, intent.query, text, resp.verdict.value, resp.correction,
                current if resp.verdict is Verdict.YES else nxt, log_path,
            )  # fmt: skip
        if resp.verdict is Verdict.YES:
            return LoopOutcome("confirmed", current, attempt, "Confirmed.")
        if resp.verdict is Verdict.TIMEOUT:
            return LoopOutcome("cancelled", current, attempt, "No response received; cancelled.")
        changed = nxt != current
        current = nxt
        if changed and current.confidence >= threshold:
            return LoopOutcome("confirmed", current, attempt, "Applied your correction.")
    return LoopOutcome("exhausted", current, max_attempts, GIVE_UP_MESSAGE.format(n=max_attempts))
