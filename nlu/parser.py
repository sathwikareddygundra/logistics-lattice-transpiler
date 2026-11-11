"""Rule-based NL parser (deterministic, offline).

Turns a question into a ParsedIntent covering every taxonomy intent
(aggregation, join, filter, forecast, comparison, trend, rank) or marks it
out of scope. An LLM parser (nlu.groq_parser) can take over where this one
is unsure. Required-but-missing pieces are reported in `missing_slots` for
the slot-filling step (nlu.slots).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from dag.model import AggregateOp, FilterOperator, Granularity, SortDirection
from nlu.entities import DEFAULTED, DIMENSION_WORDS, EXACT, extract
from nlu.intent import IntentFilter, IntentHaving, IntentType, ParsedIntent
from plantdb.catalog import JOIN_KEY, tables_for_columns

LISTING_LIMIT = 20
AVG_BY_DEFAULT = {"total_tat_hours", "loading_time_mins", "unloading_time_mins"}
DEFAULT_HORIZON = 3
DEFAULT_LISTING_COLUMNS = [
    "invoice_number", "dispatch_date", "origin_warehouse", "destination_city", "carrier",
]  # fmt: skip
LISTING_COLUMN_WORDS = {
    "sla": "sla_status", "driver": "driver_id", "status": "current_status",
    "location": "last_known_location", "tat": "total_tat_hours",
    "turnaround": "total_tat_hours",
}  # fmt: skip
_OUT_OF_SCOPE = re.compile(
    r"\b(optimi[sz]e|optimi[sz]ation|route plan|routing|simulate|simulation|hsn|duty|gst|"
    r"e-?way|weather|eoq|reorder point|safety stock|vrp|bin packing|monte carlo|gps)\b"
)
_FORECAST = re.compile(r"\b(forecast|predict|projection|projected|project)\b")
_TREND = re.compile(r"\b(trend|over time|month over month|mom|time series|growth)\b")
_COMPARE = re.compile(r"\b(compare|comparison|versus|vs\.?|against)\b")
_LISTING = re.compile(
    r"\b(list|show|display|find|get|give me|fetch|which shipments|what shipments)\b"
)
_RANK_WORDS = re.compile(
    r"\b(most|least|highest|lowest|largest|smallest|longest|shortest|biggest|worst|best)\b"
)


_GT = (
    r"more than|greater than|higher than|larger than|bigger than|above|over|exceeds?|exceeding"
    r"|at least"
)
_LT = r"less than|lower than|smaller than|fewer than|below|under|at most|cheaper than"
_RELATIVE = re.compile(
    rf"\b(?P<dir>(?P<gt>{_GT})|(?P<lt>{_LT}))\s+(?:the\s+|our\s+)?(?:overall\s+)?"
    r"(?P<avg>average|avg|mean)\b"
)
_NUMERIC = re.compile(
    rf"(?<!last )(?<!next )(?<!top )(?<!bottom )\b(?P<dir>(?P<gt>{_GT})|(?P<lt>{_LT}))\s+"
    r"\$?(?P<num>\d+(?:\.\d+)?)\b"
)
_OPERATORS = {
    "more than": FilterOperator.GT, "greater than": FilterOperator.GT,
    "higher than": FilterOperator.GT, "larger than": FilterOperator.GT,
    "bigger than": FilterOperator.GT, "above": FilterOperator.GT, "over": FilterOperator.GT,
    "exceed": FilterOperator.GT, "exceeds": FilterOperator.GT, "exceeding": FilterOperator.GT,
    "at least": FilterOperator.GTE, "less than": FilterOperator.LT,
    "lower than": FilterOperator.LT, "smaller than": FilterOperator.LT,
    "fewer than": FilterOperator.LT, "below": FilterOperator.LT, "under": FilterOperator.LT,
    "at most": FilterOperator.LTE, "cheaper than": FilterOperator.LT,
}  # fmt: skip
_SUBJECT = re.compile(r"\b(" + "|".join(sorted(DIMENSION_WORDS, key=len, reverse=True)) + r")\b")


def _threshold(t: str) -> tuple[FilterOperator, float | None, bool] | None:
    """A "more than N" or "more than the average" condition: (operator, number, is_relative)."""
    if m := _RELATIVE.search(t):
        return _OPERATORS[m.group("dir")], None, True
    if m := _NUMERIC.search(t):
        return _OPERATORS[m.group("dir")], float(m.group("num")), False
    return None


def _tokens(query: str) -> str:
    return re.sub(r"\s+", " ", query.lower().replace("_", " ")).strip()


def _merge_same_column_filters(filters: list[IntentFilter]) -> tuple[list[IntentFilter], dict]:
    """Two values of one column ("DHL and FedEx") mean OR, which the grammar has no
    operator for: turn it into grouping by that column plus a post-merge row filter."""
    by_col: dict[str, list[IntentFilter]] = defaultdict(list)
    for f in filters:
        if f.operator is FilterOperator.EQ:
            by_col[f.column].append(f)
    keep: dict[str, list[str]] = {}
    drop: set[str] = set()
    for col, fs in by_col.items():
        if len(fs) > 1:
            keep[col] = [str(f.value) for f in fs]
            drop.add(col)
    return [f for f in filters if f.column not in drop], keep


def parse(query: str, today: date | None = None) -> ParsedIntent:
    today = today or date.today()
    t = _tokens(query)
    cond = _threshold(t)
    subject = next(
        (DIMENSION_WORDS[w] for w in _SUBJECT.findall(t) if DIMENSION_WORDS[w] != "plant"), None
    )
    # row level ("shipments that cost more than the average cost"): the word "average"
    # names the comparison there, not an aggregate to compute
    row_level = cond is not None and subject is None
    text = (
        re.sub(r"\b(average|avg|mean)\b", "", query, flags=re.I)
        if cond and row_level and cond[2]
        else query
    )
    ent = extract(text, today)
    row_level = row_level and ent.metric is not None and ent.agg is None

    def out_of_scope() -> ParsedIntent:
        return ParsedIntent(query=query, intent_type=IntentType.OUT_OF_SCOPE, confidence=0.0)

    if _OUT_OF_SCOPE.search(t):
        return out_of_scope()

    forecast = bool(_FORECAST.search(t)) or ent.horizon is not None
    trend = bool(_TREND.search(t)) or ent.granularity is not None
    compare = bool(_COMPARE.search(t))
    rank_words = bool(_RANK_WORDS.search(t))
    rank = ent.top_n is not None or (
        rank_words and bool(re.search(r"\b(which|what)\b", t)) and bool(ent.dimensions)
    )
    listing = bool(_LISTING.search(t)) and ent.agg is None and not rank and not trend
    if listing and re.search(r"\bhow many\b", t):
        listing = False
    if row_level and not (forecast or trend or compare):
        listing = True

    has_measure = ent.metric is not None or ent.count_requested or ent.agg == "count"
    if not (has_measure or listing or forecast or trend or rank or compare):
        return out_of_scope()
    if listing and not (ent.filters or ent.dimensions or ent.plants or ent.metric):
        listing = True  # bare "show dispatches": missing-filter slot will ask

    filters, keep_values = _merge_same_column_filters(ent.filters)
    group_by = [d for d in ent.dimensions if d != "plant"]
    compare_by_plant = "plant" in ent.dimensions or (compare and len(ent.plants) >= 2)
    for col in keep_values:
        if col not in group_by:
            group_by.append(col)

    # --- measure -------------------------------------------------------------
    metric, agg = ent.metric, ent.agg
    metric_conf = ent.metric_conf
    if metric is None and (ent.count_requested or agg == "count"):
        metric, agg, metric_conf = JOIN_KEY, "count", EXACT
    if agg == "count" and ent.metric is not None:
        metric = JOIN_KEY  # "how many shipments" never counts a measure column
    agg_conf = EXACT
    if agg is None and metric is not None:
        # durations are averaged by default, quantities and money are summed
        default = "count" if metric == JOIN_KEY else "avg" if metric in AVG_BY_DEFAULT else "sum"
        agg, agg_conf = default, DEFAULTED + 0.2
    # a condition on the result: group level ("depots whose average load time is over 90") or
    # row level ("shipments costing more than the average")
    having: list[IntentHaving] = []
    if cond and not (forecast or trend):
        op, num, relative = cond
        if row_level:
            assert ent.metric is not None
            filters.append(
                IntentFilter(
                    column=ent.metric,
                    operator=op,
                    value=num if num is not None else 0,
                    relative_to="avg" if relative else None,
                )
            )
        elif subject is not None and metric is not None:
            if subject not in group_by:
                group_by.append(subject)
            if relative and ent.agg is None and metric != JOIN_KEY:
                agg = "avg"  # "charge more than the average" means average charge
            having.append(
                IntentHaving(
                    operator=op, value=num, relative_to="overall_avg" if relative else None
                )
            )
    # rank words like "highest" pick direction there, not the aggregate
    if rank and agg in ("max", "min") and not re.search(r"\b(maximum|minimum)\b", t):
        agg = "sum" if metric != JOIN_KEY else "count"

    kind = (
        IntentType.FORECAST if forecast
        else IntentType.RANK if rank
        else IntentType.COMPARISON if compare
        else IntentType.TREND if trend
        else None
    )  # fmt: skip
    intent_conf: dict[str, float] = {}
    sort_direction = None
    limit = None
    select_columns: list[str] = []
    granularity = None
    time_column = None
    horizon = None

    if kind is IntentType.RANK:
        limit = ent.top_n or 1
        low = ent.bottom or bool(re.search(r"\b(lowest|least|smallest|shortest|worst)\b", t))
        sort_direction = SortDirection.ASC if low else SortDirection.DESC
        if metric is None and ent.count_requested:  # "which carrier has the most delayed shipments"
            metric, agg, metric_conf = JOIN_KEY, "count", EXACT
    elif kind in (IntentType.TREND, IntentType.FORECAST):
        granularity = ent.granularity or Granularity.MONTH
        time_column = ent.time_column
        sort_direction = SortDirection.ASC
        if kind is IntentType.FORECAST:
            horizon = ent.horizon or DEFAULT_HORIZON
    elif kind is None:
        if listing:
            cols = list(DEFAULT_LISTING_COLUMNS)
            for extra in [f.column for f in filters] + group_by + ([metric] if metric else []):
                if extra not in cols and extra != JOIN_KEY:
                    cols.append(extra)
            for word, col in LISTING_COLUMN_WORDS.items():
                if re.search(rf"\b{word}\b", t) and col not in cols:
                    cols.append(col)
            select_columns = cols
            limit = ent.top_n or LISTING_LIMIT
            kind = (
                IntentType.JOIN
                if len(tables_for_columns(select_columns)) > 1
                else IntentType.FILTER
            )
            metric, agg, group_by = None, None, []
        else:
            kind = IntentType.AGGREGATION

    # --- slots ---------------------------------------------------------------
    missing: list[str] = []
    if kind in (
        IntentType.AGGREGATION, IntentType.TREND, IntentType.FORECAST,
        IntentType.COMPARISON, IntentType.RANK,
    ):  # fmt: skip
        if metric is None:
            missing.append("metric")
    if kind is IntentType.RANK and not group_by and not compare_by_plant:
        missing.append("dimension")
    if kind is IntentType.COMPARISON and not group_by and not compare_by_plant:
        missing.append("dimension")
    if kind in (IntentType.FILTER, IntentType.JOIN) and not (filters or ent.plants):
        missing.append("filter")

    # --- confidence (T-21): per-entity scores and an overall score -----------
    if metric is not None:
        intent_conf["metric"] = metric_conf or DEFAULTED
    if agg is not None:
        intent_conf["agg"] = agg_conf
    for key, conf in ent.filter_conf.items():
        intent_conf[key] = conf
    if ent.plants:
        intent_conf["plants"] = 0.95
    explicit = bool(forecast or trend or compare or rank or listing or ent.agg)
    if not explicit:
        intent_conf["intent_type"] = 0.7
    overall = sum(intent_conf.values()) / len(intent_conf) if intent_conf else DEFAULTED
    if missing:
        overall = min(overall, 0.5)

    return ParsedIntent(
        query=query,
        intent_type=kind,
        metric=metric,
        agg=AggregateOp(agg) if agg else None,
        group_by=group_by,
        filters=filters,
        select_columns=select_columns,
        sort_direction=sort_direction,
        limit=limit,
        granularity=granularity,
        time_column=time_column,
        horizon=horizon,
        plants=ent.plants,
        compare_by_plant=compare_by_plant,
        keep_values=keep_values,
        having=having,
        confidence=round(min(overall, 0.99), 3),
        entity_confidence={k: round(v, 3) for k, v in intent_conf.items()},
        missing_slots=missing,
    )
