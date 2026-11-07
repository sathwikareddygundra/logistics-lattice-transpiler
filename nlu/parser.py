"""Rule-based NL parser (deterministic, offline).

Covers the slice: aggregations (total / average / count / max / min of a
metric, optionally grouped and filtered) and "top N" rankings. Anything
else is OUT_OF_SCOPE. A hosted-LLM parser (nlu.groq_parser) can take over
when this one is not confident.
"""

from __future__ import annotations

import re
from datetime import date

from dag.model import AggregateOp, FilterOperator, SortDirection
from nlu.intent import IntentFilter, IntentType, ParsedIntent
from plantdb.generate import CARRIERS, DESTINATIONS, PLANTS, PRODUCTS

TABLE = "dispatch"

_METRICS = {
    "weight": "weight_tons",
    "tons": "weight_tons",
    "tonnage": "weight_tons",
    "freight": "freight_cost",
    "cost": "freight_cost",
}
_AGG_WORDS = [
    (r"\b(average|avg|mean)\b", AggregateOp.AVG),
    (r"\b(maximum|max|highest|largest)\b", AggregateOp.MAX),
    (r"\b(minimum|min|lowest|smallest)\b", AggregateOp.MIN),
    (r"\b(how many|count|number of)\b", AggregateOp.COUNT),
    (r"\b(total|sum)\b", AggregateOp.SUM),
]
_DIMENSIONS = {
    "plant": "plant",
    "plants": "plant",
    "destination": "destination",
    "destinations": "destination",
    "carrier": "carrier",
    "carriers": "carrier",
    "product": "product",
    "products": "product",
}
_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]  # fmt: skip
DEFAULT_YEAR = 2026


def _month_range(year: int, month: int) -> tuple[str, str]:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return date(year, month, 1).isoformat(), nxt.isoformat()


def _date_filters(text: str, today: date) -> list[IntentFilter]:
    if "last month" in text:
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    else:
        found = next((m for m in _MONTHS if re.search(rf"\b{m}\b", text)), None)
        if found is None:
            return []
        month = _MONTHS.index(found) + 1
        y = re.search(rf"\b{found}\s+(\d{{4}})\b", text)
        year = int(y.group(1)) if y else DEFAULT_YEAR
    start, end = _month_range(year, month)
    return [
        IntentFilter(column="dispatch_date", operator=FilterOperator.GTE, value=start),
        IntentFilter(column="dispatch_date", operator=FilterOperator.LT, value=end),
    ]


def _entity_filters(query: str) -> list[IntentFilter]:
    filters = []
    for column, values in (
        ("plant", PLANTS),
        ("carrier", CARRIERS),
        ("product", PRODUCTS),
        ("destination", DESTINATIONS),
    ):
        for value in values:
            if re.search(rf"\b{re.escape(value)}\b", query, re.IGNORECASE):
                filters.append(IntentFilter(column=column, operator=FilterOperator.EQ, value=value))
    return filters


def parse(query: str, today: date | None = None) -> ParsedIntent:
    today = today or date.today()
    text = query.lower()

    out_of_scope = ParsedIntent(
        query=query, intent_type=IntentType.OUT_OF_SCOPE, confidence=0.0
    )

    metric = next((col for word, col in _METRICS.items() if re.search(rf"\b{word}\b", text)), None)
    agg = next((op for pattern, op in _AGG_WORDS if re.search(pattern, text)), None)
    top = re.search(r"\btop\s+(\d+)\b", text)

    if metric is None and agg is not AggregateOp.COUNT and not top:
        return out_of_scope
    if agg is None and not top:
        return out_of_scope

    filters = _entity_filters(query) + _date_filters(text, today)

    group_by: list[str] = []
    by = re.search(r"\b(?:by|per|for each|across)\s+(?:each\s+)?(\w+)", text)
    if by and by.group(1) in _DIMENSIONS:
        group_by = [_DIMENSIONS[by.group(1)]]

    if top:
        dim = next((_DIMENSIONS[w] for w in re.findall(r"\w+", text) if w in _DIMENSIONS), None)
        if dim is None:
            return out_of_scope
        # entity filter on the ranked dimension would defeat the ranking
        filters = [f for f in filters if f.column != dim]
        explicit_metric = metric is not None
        confidence = 0.85 if explicit_metric else 0.6
        return ParsedIntent(
            query=query,
            intent_type=IntentType.RANK,
            table=TABLE,
            metric=metric or "weight_tons",
            agg=agg or AggregateOp.SUM,
            group_by=[dim],
            filters=filters,
            sort_direction=SortDirection.ASC if "bottom" in text else SortDirection.DESC,
            limit=int(top.group(1)),
            confidence=confidence,
        )

    confidence = 0.55
    if metric is not None or agg is AggregateOp.COUNT:
        confidence += 0.25
    confidence += 0.1  # an aggregation word matched
    if filters or group_by:
        confidence += 0.1
    return ParsedIntent(
        query=query,
        intent_type=IntentType.AGGREGATION,
        table=TABLE,
        metric=metric or "invoice_number",
        agg=agg,
        group_by=group_by,
        filters=filters,
        confidence=min(confidence, 0.99),
    )
