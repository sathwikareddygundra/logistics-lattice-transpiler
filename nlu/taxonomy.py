"""
T-17 — Supported intent taxonomy.

Defines every intent category the NLU stage (Phase 3) is allowed to
recognize, with real example NL queries per category, plus an explicit
"out of scope" bucket for everything else.

This module is the thing T-12's parsed-intent JSON Schema has to agree
with: the schema's `intent_type` enum is generated from IntentType below,
so the two can never silently drift apart.

Downstream consumers:
- T-18 (NLU approach) prototypes against these categories.
- T-20 (slot-filling) defines required/optional slots per category.
- T-24 (out-of-scope fallback) uses is_out_of_scope().
- T-35 (parsed intent -> DAG) needs one DAG template per category here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IntentType(str, Enum):
    """Every value here must have a matching entry in TAXONOMY below."""

    AGGREGATION = "aggregation"
    JOIN = "join"
    FILTER = "filter"
    FORECAST = "forecast"
    COMPARISON = "comparison"
    TREND = "trend"
    RANK = "rank"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class IntentDefinition:
    intent_type: IntentType
    description: str
    example_queries: tuple[str, ...]

    def __post_init__(self) -> None:
        # Guard rail from the "Done when" criteria: every real (non
        # out-of-scope) category needs 3+ grounded examples.
        if self.intent_type is not IntentType.OUT_OF_SCOPE and len(self.example_queries) < 3:
            raise ValueError(
                f"{self.intent_type} has only {len(self.example_queries)} "
                "example queries; T-17 requires 3+."
            )


TAXONOMY: dict[IntentType, IntentDefinition] = {
    IntentType.AGGREGATION: IntentDefinition(
        intent_type=IntentType.AGGREGATION,
        description=(
            "Reduces a set of rows to a single summary number, or a small "
            "set of grouped summary numbers (sum, count, avg, min, max)."
        ),
        example_queries=(
            "What was the total dispatch tonnage from MCW last month?",
            "How many rakes did YCW load in August 2026?",
            "What's the average lead distance for VGU dispatches this quarter?",
        ),
    ),
    IntentType.JOIN: IntentDefinition(
        intent_type=IntentType.JOIN,
        description=(
            "Combines data across two or more related tables (or plants) "
            "into one result, without necessarily aggregating it."
        ),
        example_queries=(
            "Show dispatch records along with the vehicle type used, for MCW.",
            "List rakes with their assigned driver and destination for last week.",
            "Give me dispatch by plant and vehicle type for YCW and VGU.",
        ),
    ),
    IntentType.FILTER: IntentDefinition(
        intent_type=IntentType.FILTER,
        description=(
            "Narrows a result set to rows matching specific conditions, "
            "with no aggregation or cross-table combination required."
        ),
        example_queries=(
            "Show me all dispatches from MCW on 3rd September 2026.",
            "List rakes destined for Hyderabad this week.",
            "Which dispatches from YCW exceeded 30 tonnes?",
        ),
    ),
    IntentType.FORECAST: IntentDefinition(
        intent_type=IntentType.FORECAST,
        description=(
            "Projects a future value based on historical data; always "
            "implies a model or extrapolation step downstream."
        ),
        example_queries=(
            "What will MCW's dispatch volume be next month?",
            "Forecast rake availability for YCW over the next two weeks.",
            "Predict lead distance trends for VGU through year end.",
        ),
    ),
    IntentType.COMPARISON: IntentDefinition(
        intent_type=IntentType.COMPARISON,
        description=(
            "Compares a metric across two or more discrete groups "
            "(plants, periods, vehicle types) side by side."
        ),
        example_queries=(
            "Compare dispatch tonnage between MCW and YCW for August 2026.",
            "How does VGU's lead distance compare to MCW's this quarter?",
            "Compare rake turnaround time across all three plants.",
        ),
    ),
    IntentType.TREND: IntentDefinition(
        intent_type=IntentType.TREND,
        description=(
            "Describes how a metric changed over time, typically as a "
            "series of values across periods rather than one number."
        ),
        example_queries=(
            "Show me MCW's dispatch trend over the last six months.",
            "How has YCW's average lead distance changed this year?",
            "What's the weekly rake utilization trend for VGU?",
        ),
    ),
    IntentType.RANK: IntentDefinition(
        intent_type=IntentType.RANK,
        description=(
            "Orders entities by a metric and typically returns a "
            "top/bottom N slice."
        ),
        example_queries=(
            "Which vehicle type had the highest dispatch tonnage at MCW last month?",
            "Top 5 destinations by dispatch volume for YCW this year.",
            "Which plant had the lowest average lead distance in Q3?",
        ),
    ),
    IntentType.OUT_OF_SCOPE: IntentDefinition(
        intent_type=IntentType.OUT_OF_SCOPE,
        description=(
            "Anything that isn't a data question the pipeline can answer: "
            "opinions, actions outside the system's reach, unrelated "
            "domains, or requests to write/mutate data. See T-24 for the "
            "runtime fallback behavior."
        ),
        example_queries=(
            "Should we open a fourth plant next year?",
            "Delete last month's dispatch records for MCW.",
            "What's the weather like at YCW today?",
        ),
    ),
}


def is_out_of_scope(intent_type: IntentType) -> bool:
    return intent_type is IntentType.OUT_OF_SCOPE


def allowed_intent_values() -> list[str]:
    """The exact enum values T-12's JSON Schema must expose."""
    return [member.value for member in IntentType]


if __name__ == "__main__":
    # Cheap manual smoke check: every category has real examples, and every
    # IntentType member has a TAXONOMY entry (no silent gaps).
    assert set(TAXONOMY.keys()) == set(IntentType), "TAXONOMY is missing an IntentType entry"
    for intent, definition in TAXONOMY.items():
        print(f"{intent.value:12s} ({len(definition.example_queries)} examples)")
    print("\nOK: every IntentType has a taxonomy entry with grounded examples.")
