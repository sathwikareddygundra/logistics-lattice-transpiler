"""Entity extraction and normalization (T-19).

Everything resolves to canonical values: "last month" becomes a date
range, plant and carrier aliases (and near-misspellings) become one
identifier. Each extracted entity carries a confidence for T-21.
"""

from __future__ import annotations

import calendar
import difflib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from dag.model import FilterOperator, Granularity
from nlu.intent import IntentFilter
from plantdb.plants import Plant
from plantdb.vocab import column_values

EXACT, ALIAS, FUZZY, DEFAULTED = 0.98, 0.95, 0.8, 0.5
FISCAL_YEAR_START_MONTH = 4  # April-March; "FY25" = Apr 2024 - Mar 2025

PLANT_ALIASES = {
    "mcw": Plant.MCW, "mellacheruvu": Plant.MCW,
    "ycw": Plant.YCW, "yerraguntla": Plant.YCW,
    "vgu": Plant.VGU,
}  # fmt: skip

WAREHOUSE_ALIASES = {
    "chicago": "Chicago_WH", "columbus": "Columbus_WH", "los angeles": "LA_WH",
    "la": "LA_WH", "atlanta": "Atlanta_WH", "dallas": "Dallas_WH",
}  # fmt: skip
CARRIER_ALIASES = {"jbhunt": "JB Hunt", "jb hunt": "JB Hunt", "xpo": "XPO Logistics",
                   "fed ex": "FedEx", "federal express": "FedEx"}  # fmt: skip
STATUS_ALIASES = {"in transit": "In Transit", "delivered": "Delivered",
                  "customs hold": "Customs Hold",
                  "out for delivery": "Out for Delivery"}  # fmt: skip

METRIC_WORDS = [  # order matters: first match wins
    (r"\bunloading\b", "unloading_time_mins"),
    (r"\bloading\b", "loading_time_mins"),
    (r"\b(tat|turnaround|turn around|transit time)\b", "total_tat_hours"),
    (r"\b(weight|tonnage|tons?|tonnes?|kgs?|kilograms?)\b", "shipment_weight_kg"),
    (r"\b(freight|cost|costs|spend|charges|expense|expenses|revenue)\b", "freight_cost_usd"),
]
COUNT_WORDS = r"\b(how many|count|number of|dispatches|shipments|invoices|deliveries)\b"
AGG_WORDS = [
    (r"\b(average|avg|mean)\b", "avg"),
    (r"\b(maximum|max|highest|largest|longest|biggest)\b", "max"),
    (r"\b(minimum|min|lowest|smallest|shortest)\b", "min"),
    (r"\b(how many|count|number of)\b", "count"),
    (r"\b(total|sum|overall|combined)\b", "sum"),
]
DIMENSION_WORDS = {
    "carrier": "carrier", "carriers": "carrier", "transporter": "carrier",
    "warehouse": "origin_warehouse", "warehouses": "origin_warehouse",
    "origin": "origin_warehouse", "city": "destination_city", "cities": "destination_city",
    "destination": "destination_city", "destinations": "destination_city",
    "status": "current_status", "statuses": "current_status",
    "sla": "sla_status", "driver": "driver_id", "drivers": "driver_id",
    "plant": "plant", "plants": "plant",
}  # fmt: skip
GRANULARITY_WORDS = {
    "day": Granularity.DAY, "daily": Granularity.DAY, "week": Granularity.WEEK,
    "weekly": Granularity.WEEK, "month": Granularity.MONTH, "monthly": Granularity.MONTH,
    "quarter": Granularity.QUARTER, "quarterly": Granularity.QUARTER,
    "year": Granularity.YEAR, "yearly": Granularity.YEAR, "annual": Granularity.YEAR,
}  # fmt: skip
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9})


@dataclass
class Entities:
    metric: str | None = None
    metric_conf: float = 0.0
    count_requested: bool = False
    agg: str | None = None
    dimensions: list[str] = field(default_factory=list)
    filters: list[IntentFilter] = field(default_factory=list)
    filter_conf: dict[str, float] = field(default_factory=dict)
    plants: list[str] = field(default_factory=list)
    top_n: int | None = None
    bottom: bool = False
    granularity: Granularity | None = None
    horizon: int | None = None
    date_range: tuple[date, date] | None = None
    time_column: str = "dispatch_date"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("_", " ")).strip()


def _month_start(y: int, m: int) -> date:
    return date(y + (m - 1) // 12, (m - 1) % 12 + 1, 1)


def _add_months(d: date, n: int) -> date:
    return _month_start(d.year, d.month + n)


def _quarter_range(year: int, q: int, fiscal: bool) -> tuple[date, date]:
    first = FISCAL_YEAR_START_MONTH if fiscal else 1
    start = _month_start(year, first + (q - 1) * 3)
    return start, _add_months(start, 3)


def resolve_dates(text: str, today: date) -> tuple[date, date] | None:
    """Half-open [start, end) range for the date expression in `text`, if any."""
    t = text.lower()
    fiscal = bool(re.search(r"\b(fy|fiscal)\b", t))
    if m := re.search(r"\blast (\d+) (day|week|month)s?\b", t):
        n, unit = int(m.group(1)), m.group(2)
        end = today + timedelta(days=1)
        if unit == "month":
            return _add_months(date(today.year, today.month, 1), -n), end
        return today - timedelta(days=n * (7 if unit == "week" else 1)), end
    if re.search(r"\b(last|previous) month\b", t):
        s = _add_months(date(today.year, today.month, 1), -1)
        return s, _add_months(s, 1)
    if re.search(r"\bthis month\b", t):
        s = date(today.year, today.month, 1)
        return s, _add_months(s, 1)
    if re.search(r"\b(last|previous) quarter\b", t):
        cq = (today.month - 1) // 3
        year, q = (today.year, cq) if cq else (today.year - 1, 4)
        return _quarter_range(year, q, False)
    if re.search(r"\bthis quarter\b", t):
        return _quarter_range(today.year, (today.month - 1) // 3 + 1, False)
    if re.search(r"\b(last|previous) year\b", t):
        return date(today.year - 1, 1, 1), date(today.year, 1, 1)
    if re.search(r"\bthis year\b", t):
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    if m := re.search(r"\bfy\s?(\d{2,4})\s*q([1-4])\b", t):
        y = int(m.group(1))
        y = y + 2000 if y < 100 else y
        return _quarter_range(y - 1, int(m.group(2)), True)
    if m := re.search(r"\bq([1-4])(?:\s+(?:of\s+)?(?:fy)?\s*(\d{2,4}))?\b", t):
        y = int(m.group(2)) if m.group(2) else today.year
        y = y + 2000 if y < 100 else y
        if fiscal:
            y -= 1  # FY2026 Q1 starts April 2025
        return _quarter_range(y, int(m.group(1)), fiscal)
    if m := re.search(r"\bfy\s?(\d{2,4})\b|\bfiscal year (\d{2,4})\b", t):
        y = int(m.group(1) or m.group(2))
        y = y + 2000 if y < 100 else y
        s = date(y - 1, FISCAL_YEAR_START_MONTH, 1)
        return s, _add_months(s, 12)
    month_re = "|".join(sorted(MONTHS, key=len, reverse=True))
    if m := re.search(
        rf"\b(?:from|between)\s+({month_re})\s+(?:to|and|through|till)\s+({month_re})\b", t
    ):
        a, b = MONTHS[m.group(1)], MONTHS[m.group(2)]
        ya = today.year if a <= today.month else today.year - 1
        yb = ya if b >= a else ya + 1
        return _month_start(ya, a), _month_start(yb, b + 1)
    for m in re.finditer(rf"\b({month_re})\b(?:\s+(\d{{4}}))?", t):
        word, yr = m.group(1), m.group(2)
        if word == "may" and not yr and not re.search(r"\b(in|of|for|during|since)\s+may\b", t):
            continue  # "may" as a verb
        mon = MONTHS[word]
        year = int(yr) if yr else (today.year if mon <= today.month else today.year - 1)
        return _month_start(year, mon), _month_start(year, mon + 1)
    if m := re.search(r"\b(?:in|year|during|for)\s+(20\d{2})\b", t):
        y = int(m.group(1))
        return date(y, 1, 1), date(y + 1, 1, 1)
    return None


def _match_values(text: str, column: str, aliases: dict[str, str]) -> list[tuple[str, float]]:
    """Canonical values of `column` mentioned in `text`, with a confidence each."""
    norm = _norm(text)
    padded = f" {norm} "
    found: dict[str, float] = {}
    for alias, canon in aliases.items():
        if f" {alias} " in padded:
            found[canon] = ALIAS
    for value in column_values()[column]:
        if f" {_norm(value)} " in padded:
            found[value] = EXACT
    if not found:  # tolerate typos on single/short vocabulary words
        words = norm.split()
        targets = {_norm(v): v for v in column_values()[column]} | {
            a: c for a, c in aliases.items() if " " not in a
        }
        for key, value in targets.items():
            if " " not in key and len(key) >= 5:
                if difflib.get_close_matches(key, words, n=1, cutoff=0.82):
                    found[value] = FUZZY
    return list(found.items())


def extract(query: str, today: date) -> Entities:
    t = _norm(query)
    ent = Entities()

    for pattern, col in METRIC_WORDS:
        if re.search(pattern, t):
            ent.metric, ent.metric_conf = col, EXACT
            break
    ent.count_requested = bool(re.search(COUNT_WORDS, t))
    for pattern, agg in AGG_WORDS:
        if re.search(pattern, t):
            ent.agg = agg
            break

    dim_re = "|".join(DIMENSION_WORDS)
    for m in re.finditer(
        rf"\b(?:by|per|each|every|across|wise|for each|which|compare|top \d+|bottom \d+)"
        rf"\s+(?:the\s+)?({dim_re})\b",
        t,
    ):
        dim = DIMENSION_WORDS[m.group(1)]
        if dim not in ent.dimensions:
            ent.dimensions.append(dim)
    for m in re.finditer(rf"\b(?:top|bottom)\s+\d+\s+({dim_re})\b|\b({dim_re})\s+(?:wise)\b", t):
        dim = DIMENSION_WORDS[m.group(1) or m.group(2)]
        if dim not in ent.dimensions:
            ent.dimensions.append(dim)
    # granularity only counts as a time bucket ("monthly", "per week"), not inside
    # a date phrase like "last month"
    if dm := re.search(r"\b(daily|weekly|monthly|quarterly|yearly|annual|annually)\b", t):
        ent.granularity = GRANULARITY_WORDS[
            dm.group(1).removesuffix("ly") if dm.group(1) == "annually" else dm.group(1)
        ]
    elif gm := re.search(
        r"\b(?:by|per|each|every|over|across)\s+(?:the\s+)?(day|week|month|quarter|year)s?\b", t
    ):
        ent.granularity = GRANULARITY_WORDS[gm.group(1)]

    if tm := re.search(r"\b(top|bottom)\s+(\d+)\b", t):
        ent.top_n, ent.bottom = int(tm.group(2)), tm.group(1) == "bottom"
    if hm := re.search(r"\bnext\s+(\d+)\s+(?:day|week|month|quarter|year)s?\b", t):
        ent.horizon = int(hm.group(1))

    ent.plants = [
        p.value
        for p in dict.fromkeys(
            PLANT_ALIASES[w] for w in re.findall(r"[a-z]+", t) if w in PLANT_ALIASES
        )
    ]

    for column, aliases in (
        ("origin_warehouse", WAREHOUSE_ALIASES),
        ("carrier", CARRIER_ALIASES),
    ):
        for value, conf in _match_values(t, column, aliases):
            ent.filters.append(IntentFilter(column=column, operator=FilterOperator.EQ, value=value))
            ent.filter_conf[f"{column}={value}"] = conf
    # destination city: "to Boston" / "in Boston" (city vocabulary is the destination column)
    for value, conf in _match_values(t, "destination_city", {}):
        ent.filters.append(
            IntentFilter(column="destination_city", operator=FilterOperator.EQ, value=value)
        )
        ent.filter_conf[f"destination_city={value}"] = conf
    # status vs SLA: "sla"/"on time" talk about sla_status, a bare "delayed" about tracking status
    sla = bool(re.search(r"\bsla\b|\bon time\b|\bon-time\b|\bbreach", t))
    if re.search(r"\bon time\b|\bon-time\b", t):
        ent.filters.append(
            IntentFilter(column="sla_status", operator=FilterOperator.EQ, value="On Time")
        )
        ent.filter_conf["sla_status=On Time"] = EXACT
    if re.search(r"\bdelayed\b|\blate\b|\bbreach", t):
        col = "sla_status" if sla else "current_status"
        ent.filters.append(IntentFilter(column=col, operator=FilterOperator.EQ, value="Delayed"))
        ent.filter_conf[f"{col}=Delayed"] = EXACT
    for value, conf in _match_values(t, "current_status", STATUS_ALIASES):
        if value != "Delayed":
            ent.filters.append(
                IntentFilter(column="current_status", operator=FilterOperator.EQ, value=value)
            )
            ent.filter_conf[f"current_status={value}"] = conf

    if re.search(r"\bpromised\b", t):
        ent.time_column = "promised_delivery_date"
    elif re.search(r"\b(actual delivery|delivered (?:in|on|during))\b", t):
        ent.time_column = "actual_delivery_date"
    ent.date_range = resolve_dates(query, today)
    if ent.date_range:
        start, end = ent.date_range
        ent.filters.append(
            IntentFilter(
                column=ent.time_column, operator=FilterOperator.GTE, value=start.isoformat()
            )
        )
        ent.filters.append(
            IntentFilter(column=ent.time_column, operator=FilterOperator.LT, value=end.isoformat())
        )
        ent.filter_conf["date_range"] = ALIAS
    # a dimension named in "by X" is grouping, not filtering; dedupe identical filters
    seen: set[tuple] = set()
    unique = []
    for f in ent.filters:
        key = (f.column, f.operator, str(f.value))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    ent.filters = unique
    return ent
