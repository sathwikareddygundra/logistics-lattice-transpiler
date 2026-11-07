"""Confidence-threshold routing and the "did you mean" paraphrase."""

from __future__ import annotations

from dataclasses import dataclass

from nlu.intent import IntentType, ParsedIntent

CONFIDENCE_THRESHOLD = 0.8


@dataclass(frozen=True)
class ConfirmDecision:
    needs_confirmation: bool
    paraphrase: str


def paraphrase(intent: ParsedIntent) -> str:
    if intent.intent_type is IntentType.OUT_OF_SCOPE:
        return "I can't answer that from the dispatch data."
    what = f"the {intent.agg.value if intent.agg else ''} of {intent.metric}".replace("  ", " ")
    parts = [f"Did you mean {what}"]
    if intent.group_by:
        parts.append(f"grouped by {', '.join(intent.group_by)}")
    for f in intent.filters:
        parts.append(f"where {f.column} {f.operator.value} {f.value}")
    if intent.limit:
        parts.append(f"top {intent.limit}")
    return " ".join(parts) + "?"


def route(intent: ParsedIntent, threshold: float = CONFIDENCE_THRESHOLD) -> ConfirmDecision:
    """At or above the threshold skips confirmation; below it asks."""
    return ConfirmDecision(
        needs_confirmation=intent.confidence < threshold, paraphrase=paraphrase(intent)
    )
