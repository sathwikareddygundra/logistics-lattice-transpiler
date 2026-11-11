"""ParsedIntent -> the JSON wire format of schemas/parsed_intent.schema.json (T-12)."""

from __future__ import annotations

from nlu.intent import IntentType, ParsedIntent

_BOUNDS = {"gte", "gt"}


def to_wire(intent: ParsedIntent, trace_id: str) -> dict:
    ec = intent.entity_confidence
    entities: list[dict] = []

    def add(kind: str, value: str, normalized: object, conf: float) -> None:
        entities.append(
            {
                "entity_type": kind,
                "value": value,
                "normalized_value": normalized,
                "confidence": conf,
            }
        )

    if intent.intent_type is not IntentType.OUT_OF_SCOPE:
        for table in intent.tables():
            add("table", table, table, 0.95)
        if intent.metric:
            add("column", intent.metric, intent.metric, ec.get("metric", 0.5))
        if intent.agg:
            add("aggregation_op", intent.agg.value, intent.agg.value, ec.get("agg", 0.5))
        for col in intent.group_by:
            add("column", col, col, 0.95)
        for p in intent.plants:
            add("plant", p, p, ec.get("plants", 0.95))
        bounds: dict[str, dict[str, str]] = {}
        for f in intent.filters:
            if f.operator.value in ("gte", "lt"):
                bounds.setdefault(f.column, {})[f.operator.value] = str(f.value)
            else:
                key = f"{f.column}={f.value}"
                add("filter_value", str(f.value), {"column": f.column, "value": f.value},
                    ec.get(key, 0.9))  # fmt: skip
        for col, b in bounds.items():
            add(
                "date_range",
                f"{b.get('gte', '')}..{b.get('lt', '')}",
                {"column": col, "start": b.get("gte"), "end": b.get("lt")},
                ec.get("date_range", 0.9),
            )
    return {
        "schema_version": "1.0.0",
        "trace_id": trace_id,
        "raw_query": intent.query,
        "intent_type": intent.intent_type.value,
        "entities": entities,
        "confidence": {
            "overall": intent.confidence,
            "per_entity": [e["confidence"] for e in entities],
        },
    }
