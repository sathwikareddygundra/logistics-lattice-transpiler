"""Hybrid NLU (decision in docs/adr-nlu-approach.md): the deterministic rule parser
answers first; the hosted model is consulted only when the rules are unsure or give up."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from common.groq_client import GroqClient, GroqClientError
from confirm.router import CONFIDENCE_THRESHOLD
from nlu.groq_parser import GroqParseError, parse_with_groq
from nlu.intent import IntentType, ParsedIntent
from nlu.parser import parse


@dataclass(frozen=True)
class HybridResult:
    intent: ParsedIntent
    source: str  # rules | llm | rules (llm unavailable)


def parse_hybrid(
    query: str,
    today: date | None = None,
    client: GroqClient | None = None,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> HybridResult:
    rules = parse(query, today)
    unsure = rules.intent_type is IntentType.OUT_OF_SCOPE or rules.confidence < threshold
    if not unsure or client is None:
        return HybridResult(rules, "rules")
    try:
        llm = parse_with_groq(query, client, today)
    except (GroqClientError, GroqParseError):
        return HybridResult(rules, "rules (llm unavailable)")
    if llm.intent_type is IntentType.OUT_OF_SCOPE:
        return HybridResult(rules, "rules")  # both agree it is out of scope or unclear
    return HybridResult(llm, "llm")
