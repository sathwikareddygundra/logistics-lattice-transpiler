"""Confidence-threshold routing and the "did you mean" paraphrase (T-27, T-29)."""

from __future__ import annotations

from dataclasses import dataclass

from nlu.intent import IntentType, ParsedIntent

CONFIDENCE_THRESHOLD = 0.8

_NAMES = {
    "shipment_weight_kg": "shipment weight (kg)", "freight_cost_usd": "freight cost (USD)",
    "total_tat_hours": "turnaround time (hours)", "loading_time_mins": "loading time (minutes)",
    "unloading_time_mins": "unloading time (minutes)", "invoice_number": "number of shipments",
    "origin_warehouse": "origin warehouse", "destination_city": "destination city",
    "current_status": "tracking status", "sla_status": "SLA status", "carrier": "carrier",
    "driver_id": "driver", "dispatch_date": "dispatch date",
    "promised_delivery_date": "promised delivery date",
    "actual_delivery_date": "actual delivery date",
}  # fmt: skip
_AGG = {"sum": "the total", "avg": "the average", "min": "the minimum", "max": "the maximum",
        "count": "the count"}  # fmt: skip


_OP_WORDS = {"eq": "is", "ne": "is not", "gt": "is more than", "gte": "is at least",
             "lt": "is less than", "lte": "is at most"}  # fmt: skip
_HAVING_WORDS = {"gt": "more than", "gte": "at least", "lt": "less than", "lte": "at most",
                 "eq": "exactly", "ne": "not"}  # fmt: skip


@dataclass(frozen=True)
class ConfirmDecision:
    needs_confirmation: bool
    paraphrase: str


def _name(col: str) -> str:
    return _NAMES.get(col, col.replace("_", " "))


def _conditions(intent: ParsedIntent) -> list[str]:
    parts: list[str] = []
    by_col: dict[str, list] = {}
    for f in intent.filters:
        by_col.setdefault(f.column, []).append(f)
    for col, fs in by_col.items():
        ops = {f.operator.value: f.value for f in fs}
        if "gte" in ops and "lt" in ops:
            parts.append(f"{_name(col)} from {ops['gte']} up to (not including) {ops['lt']}")
        else:
            for f in fs:
                value = "the average" if f.relative_to else f.value
                parts.append(f"{_name(f.column)} {_OP_WORDS.get(f.operator.value, 'is')} {value}")
    return parts


def paraphrase(intent: ParsedIntent) -> str:
    if intent.intent_type is IntentType.OUT_OF_SCOPE:
        return "I can't answer that from the dispatch data."
    scope = f"plants {', '.join(intent.plants)}" if intent.plants else "all plants"
    cond = _conditions(intent)
    if intent.is_row_listing:
        text = f"You want a list of up to {intent.limit} shipments"
    else:
        measure = _name(intent.metric or "")
        if intent.metric == "invoice_number":
            text = (
                f"You want {_AGG.get(intent.agg.value if intent.agg else '', 'the')} of shipments"
            )
        else:
            text = f"You want {_AGG.get(intent.agg.value if intent.agg else '', 'the')} {measure}"
        if intent.granularity:
            text += f" per {intent.granularity.value}"
        if intent.group_by:
            text += f", broken down by {', '.join(_name(c) for c in intent.group_by)}"
        if intent.compare_by_plant:
            text += ", compared across plants"
        if intent.intent_type is IntentType.RANK:
            order = (
                "lowest"
                if intent.sort_direction and intent.sort_direction.value == "asc"
                else "highest"
            )
            text += f", showing the {order} {intent.limit}"
        if intent.intent_type is IntentType.FORECAST:
            unit = intent.granularity.value if intent.granularity else "month"
            text += f", forecast {intent.horizon} {unit}s ahead"
    if cond:
        text += ", where " + " and ".join(cond)
    for h in intent.having:
        target = "the average" if h.relative_to else f"{h.value:g}"
        text += (
            f", keeping only groups where the result is {_HAVING_WORDS[h.operator.value]} {target}"
        )
    return f"{text}, across {scope}. Is that right?"


def route(intent: ParsedIntent, threshold: float = CONFIDENCE_THRESHOLD) -> ConfirmDecision:
    """At or above the threshold skips confirmation; below it asks."""
    return ConfirmDecision(
        needs_confirmation=intent.confidence < threshold, paraphrase=paraphrase(intent)
    )
