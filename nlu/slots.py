"""Slot-filling for incomplete queries (T-20)."""

from __future__ import annotations

from datetime import date

from nlu.intent import ParsedIntent
from nlu.parser import parse

QUESTIONS = {
    "metric": (
        "Which measure should I use: shipment weight, freight cost, turnaround time (TAT), "
        "loading time, unloading time, or a count of shipments?"
    ),
    "dimension": (
        "Group the result by what: carrier, warehouse, destination city, status, SLA, or plant?"
    ),
    "filter": (
        "Which shipments do you mean? Give a period (e.g. 'August 2026'), carrier, warehouse, "
        "city, or status."
    ),
}
SLOT_ORDER = ["metric", "dimension", "filter"]


def next_question(intent: ParsedIntent) -> str | None:
    """Exactly one targeted question: the first missing required slot."""
    for slot in SLOT_ORDER:
        if slot in intent.missing_slots:
            return QUESTIONS[slot]
    return None


def fill_slots(intent: ParsedIntent, answer: str, today: date | None = None) -> ParsedIntent:
    """Merge the user's answer into the original question. Everything already
    understood persists because the original text is re-parsed together with the answer."""
    combined = f"{intent.query.rstrip('.?! ')}. {answer}"
    filled = parse(combined, today)
    return filled.model_copy(update={"query": f"{intent.query} [{answer}]"})
