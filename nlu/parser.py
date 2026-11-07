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
from nlu.entities import DEFAULTED, EXACT, extract
from nlu.intent import IntentFilter, IntentType, ParsedIntent
from plantdb.catalog import JOIN_KEY, tables_for_columns

LISTING_LIMIT = 20
DEFAULT_HORIZON = 3
DEFAULT_LISTING_COLUMNS = [
    "invoice_number", "dispatch_date", "origin_warehouse", "destination_city", "carrier",
]  # fmt: skip
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
    ent = extract(query, today)

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
        agg, agg_conf = ("count" if metric == JOIN_KEY else "sum"), DEFAULTED + 0.2
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
            if "driver_id" in re.findall(r"[a-z_]+", t.replace(" ", "_")) or "driver" in t:
                cols.append("driver_id") if "driver_id" not in cols else None
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
        confidence=round(min(overall, 0.99), 3),
        entity_confidence={k: round(v, 3) for k, v in intent_conf.items()},
        missing_slots=missing,
    )
