"""Build the fine-tuning set: question -> JSON intent (the ParsedIntent fields).

Every row is generated from a slot specification, so the label is correct by construction
and does not depend on the rule parser. Questions are rendered through many phrasings;
some phrasings are held out of training and go only into the validation file, to measure
generalization to wording the model never saw.

Run: uv run python finetune/build_dataset.py
Writes finetune/data/{train,val}.jsonl (chat format) and finetune/data/manifest.json.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plantdb.vocab import column_values  # noqa: E402

OUT = Path(__file__).parent / "data"
SEED = 7
TODAYS = [
    date(2026, 9, 15),
    date(2026, 9, 1),
    date(2026, 8, 20),
    date(2026, 10, 5),
    date(2026, 7, 12),
]
PLANTS = ["MCW", "YCW", "VGU"]
DATE_COL = "dispatch_date"

# metric column -> (surface phrases, aggregations that make sense)
METRICS: dict[str, tuple[list[str], list[str]]] = {
    "freight_cost_usd": (
        ["freight cost", "shipping cost", "freight spend", "freight charges", "transport cost"],
        ["sum", "avg", "max", "min"],
    ),
    "shipment_weight_kg": (
        ["shipment weight", "weight", "total weight", "kg shipped", "cargo weight"],
        ["sum", "avg", "max", "min"],
    ),
    "total_tat_hours": (
        [
            "turnaround time",
            "TAT",
            "turn around time",
            "delivery time",
            "dispatch to delivery time",
            "transit time",
            "time to deliver",
        ],
        ["avg", "max", "min"],
    ),
    "loading_time_mins": (
        ["loading time", "load time", "time spent loading"],
        ["avg", "max", "min"],
    ),
    "unloading_time_mins": (
        ["unloading time", "unload time", "time spent unloading"],
        ["avg", "max", "min"],
    ),
    "invoice_number": (
        ["shipments", "invoices", "deliveries", "consignments"],
        ["count"],
    ),
}
AGG_WORDS = {
    "sum": ["total", "sum of", "overall", "combined"],
    "avg": ["average", "mean", "avg", "typical"],
    "max": ["highest", "maximum", "max", "peak"],
    "min": ["lowest", "minimum", "min", "smallest"],
}
DIMS = {
    "carrier": ["carrier", "transporter", "logistics provider"],
    "origin_warehouse": ["warehouse", "origin warehouse", "origin", "depot"],
    "destination_city": ["destination city", "city", "destination"],
    "current_status": ["status", "shipment status", "current status"],
    "sla_status": ["SLA status", "SLA outcome"],
}
GRAN = {
    "day": ["daily", "per day", "by day"],
    "week": ["weekly", "per week", "by week"],
    "month": ["monthly", "per month", "by month"],
    "quarter": ["quarterly", "per quarter", "by quarter"],
}
VALUE_ALIASES = {
    ("current_status", "Delayed"): ["delayed", "late", "behind schedule"],
    ("current_status", "In Transit"): ["in transit", "on the road", "en route"],
    ("current_status", "Delivered"): ["delivered", "completed"],
    ("current_status", "Out for Delivery"): ["out for delivery"],
    ("current_status", "Customs Hold"): ["held at customs", "customs hold", "stuck in customs"],
    ("sla_status", "On Time"): ["on time", "within SLA", "met SLA"],
    ("sla_status", "Delayed"): ["SLA delayed", "breached SLA", "missed SLA"],
}
FILTER_DIMS = ["carrier", "origin_warehouse", "destination_city", "current_status", "sla_status"]
SELECT_COLS = {
    "filter": [
        "invoice_number",
        "dispatch_date",
        "origin_warehouse",
        "destination_city",
        "carrier",
    ],
    "join": ["invoice_number", "dispatch_date", "origin_warehouse", "destination_city", "carrier"],
}
TRACKING_OR_TAT = {"current_status", "sla_status"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]  # fmt: skip
OUT_OF_SCOPE = [
    "optimise my delivery routes", "what is the weather in Chicago", "delete all shipments",
    "update the carrier for invoice INV-2026-00001", "who is the best driver", "what is the fuel cost per mile",
    "show me the profit margin", "write me a poem about trucks", "what is the HSN code for ball bearings",
    "how many employees work at the Dallas warehouse", "book a truck for tomorrow", "what is the stock price of FedEx",
    "predict the winner of the world cup", "translate this invoice to French", "show the driver salary table",
    "email the carrier about delays", "what is the capital of France", "give me customer complaints by city",
    "how much did we spend on warehouse rent", "reset the database", "show me vehicle fuel efficiency",
    "what is the CO2 emission per shipment", "which supplier gave the best price", "cancel invoice 123",
    "tell me a joke", "show employee attendance", "what is the exchange rate of USD to INR",
    "plan a route from Boston to Miami", "how many packages did we return", "show inventory levels by SKU",
]  # fmt: skip


def surface(dim: str, value: str, rng: random.Random) -> str:
    aliases = VALUE_ALIASES.get((dim, value))
    if aliases:
        return rng.choice(aliases)
    s = value.replace("_WH", "").replace("_", " ")
    return s.lower() if rng.random() < 0.35 else s


def typo(word: str, rng: random.Random) -> str:
    if len(word) < 5:
        return word
    i = rng.randrange(1, len(word) - 2)
    kind = rng.choice(["drop", "swap", "dup"])
    if kind == "drop":
        return word[:i] + word[i + 1 :]
    if kind == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    return word[:i] + word[i] + word[i:]


# --- time expressions ---------------------------------------------------------
def month_range(y: int, m: int) -> tuple[str, str]:
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def time_spec(today: date, rng: random.Random) -> tuple[str, str, str]:
    """Returns (phrase, start, end) with end exclusive."""
    kind = rng.choice(
        ["month", "month_year", "last_month", "q", "last30", "range", "this_month", "last_q"]
    )
    if kind in ("month", "month_year"):
        m = rng.choice([6, 7, 8])
        s, e = month_range(2026, m)
        return (f"in {MONTHS[m - 1]}" + (" 2026" if kind == "month_year" else ""), s, e)
    if kind == "last_month":
        y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        s, e = month_range(y, m)
        return (rng.choice(["last month", "in the previous month"]), s, e)
    if kind == "this_month":
        s, e = month_range(today.year, today.month)
        return ("this month", s, e)
    if kind == "q":
        q = rng.choice([2, 3])
        s, e = date(2026, 3 * q - 2, 1).isoformat(), date(2026, 3 * q + 1, 1).isoformat()
        return (f"in Q{q} 2026", s, e)
    if kind == "last_q":
        cq = (today.month - 1) // 3 + 1
        y, q = (today.year, cq - 1) if cq > 1 else (today.year - 1, 4)
        first = date(y, 3 * q - 2, 1)
        after = date(y + (q == 4), (3 * q) % 12 + 1, 1)
        return ("last quarter", first.isoformat(), after.isoformat())
    if kind == "last30":
        return (
            "for the last 30 days",
            (today - timedelta(days=30)).isoformat(),
            (today + timedelta(days=1)).isoformat(),
        )
    a, b = rng.choice([(6, 7), (7, 8), (6, 8)])
    s = date(2026, a, 1).isoformat()
    e = month_range(2026, b)[1]
    return (f"from {MONTHS[a - 1]} to {MONTHS[b - 1]}", s, e)


def date_filters(start: str, end: str) -> list[dict]:
    return [
        {"column": DATE_COL, "operator": "gte", "value": start},
        {"column": DATE_COL, "operator": "lt", "value": end},
    ]


# --- one example --------------------------------------------------------------
class Ctx:
    def __init__(self, rng: random.Random, heldout: bool):
        self.rng, self.heldout = rng, heldout
        self.today = rng.choice(TODAYS)

    def pick_template(self, templates: list[str]) -> str:
        """Last two templates of each list are held out of training."""
        pool = templates[-2:] if self.heldout else templates[:-2]
        return self.rng.choice(pool)


def pick_metric(rng: random.Random, aggs: list[str] | None = None) -> tuple[str, str, str]:
    col = rng.choice(list(METRICS))
    phrases, ok_aggs = METRICS[col]
    agg = rng.choice([a for a in ok_aggs if not aggs or a in aggs] or ok_aggs)
    return col, agg, rng.choice(phrases)


def metric_phrase(col: str, agg: str, phrase: str, rng: random.Random) -> str:
    if col == "invoice_number":
        return rng.choice([f"number of {phrase}", f"count of {phrase}", f"how many {phrase}"])
    return f"{rng.choice(AGG_WORDS[agg])} {phrase}"


def maybe_filter(ctx: Ctx, used: set[str], p: float = 0.45) -> tuple[str, dict] | None:
    rng = ctx.rng
    if rng.random() > p:
        return None
    dim = rng.choice([d for d in FILTER_DIMS if d not in used])
    value = rng.choice(column_values()[dim])
    word = surface(dim, value, rng)
    if rng.random() < 0.06:
        word = typo(word, rng)
    used.add(dim)
    return word, {"column": dim, "operator": "eq", "value": value}


def maybe_time(ctx: Ctx, p: float = 0.4) -> tuple[str, list[dict]] | None:
    if ctx.rng.random() > p:
        return None
    phrase, s, e = time_spec(ctx.today, ctx.rng)
    return phrase, date_filters(s, e)


def maybe_plant(ctx: Ctx, p: float = 0.2) -> tuple[str, str] | None:
    if ctx.rng.random() > p:
        return None
    plant = ctx.rng.choice(PLANTS)
    return ctx.rng.choice([f"for {plant}", f"at {plant}", f"in plant {plant}"]), plant


def gen_aggregation(ctx: Ctx) -> tuple[str, dict]:
    rng = ctx.rng
    col, agg, ph = pick_metric(rng)
    mp = metric_phrase(col, agg, ph, rng)
    out: dict = {"intent_type": "aggregation", "metric": col, "agg": agg}
    used: set[str] = set()
    group = rng.choice(list(DIMS)) if rng.random() < 0.35 else None
    if group:
        used.add(group)
        out["group_by"] = [group]
    filt = maybe_filter(ctx, used)
    tm = maybe_time(ctx)
    pl = maybe_plant(ctx)
    filters = ([filt[1]] if filt else []) + (tm[1] if tm else [])
    if filters:
        out["filters"] = filters
    if pl:
        out["plants"] = [pl[1]]
    templates = [
        "{m}{g}{f}{t}{p}", "what is the {m}{g}{f}{t}{p}", "show me the {m}{g}{f}{t}{p}",
        "give me {m}{g}{f}{t}{p}", "{m}{f}{t}{p}{g}", "can you tell me the {m}{g}{f}{t}{p}",
        "i need the {m}{f}{g}{t}{p}", "calculate {m}{g}{f}{t}{p}",
    ]  # fmt: skip
    tpl = ctx.pick_template(templates)
    q = tpl.format(
        m=mp,
        g=f" {rng.choice(['by', 'per', 'for each'])} {rng.choice(DIMS[group])}" if group else "",
        f=f" for {filt[0]}" if filt and rng.random() < 0.5 else (f" {filt[0]}" if filt else ""),
        t=f" {tm[0]}" if tm else "",
        p=f" {pl[0]}" if pl else "",
    )
    if filt and col == "invoice_number":
        q = q.replace(f" {filt[0]}", f" {filt[0]}")
    return q, out


def gen_rank(ctx: Ctx) -> tuple[str, dict]:
    rng = ctx.rng
    col, agg, ph = pick_metric(rng, ["sum", "avg", "count"])
    dim = rng.choice(["carrier", "origin_warehouse", "destination_city"])
    top = rng.random() < 0.7
    n = rng.choice([1, 2, 3, 3, 5, 5, 10])
    out: dict = {
        "intent_type": "rank", "metric": col, "agg": agg, "group_by": [dim],
        "sort_direction": "desc" if top else "asc", "limit": n,
    }  # fmt: skip
    tm = maybe_time(ctx, 0.3)
    used = {dim}
    filt = maybe_filter(ctx, used, 0.25)
    filters = ([filt[1]] if filt else []) + (tm[1] if tm else [])
    if filters:
        out["filters"] = filters
    mp = (
        ph
        if col == "invoice_number" and agg == "count"
        else f"{rng.choice(AGG_WORDS[agg]) if agg != 'count' else 'number of'} {ph}"
    )
    d = rng.choice(DIMS[dim])
    plural = d[:-1] + "ies" if d.endswith("y") else d + "s"
    word = "top" if top else rng.choice(["bottom", "lowest"])
    suffix = f"{(' ' + tm[0]) if tm else ''}{(' for ' + filt[0]) if filt else ''}"
    if n == 1:
        sup = rng.choice(["highest", "most"]) if top else rng.choice(["lowest", "least"])
        templates = [
            f"which {d} has the {sup} {mp}{suffix}", f"what is the {sup} {d} by {mp}{suffix}",
            f"{d} with the {sup} {mp}{suffix}", f"name the {d} with {sup} {mp}{suffix}",
            f"find the {d} that has {sup} {mp}{suffix}", f"tell me which {d} gets the {sup} {mp}{suffix}",
        ]  # fmt: skip
    else:
        templates = [
            f"{word} {n} {plural} by {mp}{suffix}", f"show the {word} {n} {plural} by {mp}{suffix}",
            f"rank {plural} by {mp}{suffix} and show the {word} {n}", f"list {word} {n} {plural} by {mp}{suffix}",
            f"give me the {word} {n} {plural} ranked by {mp}{suffix}", f"{word} {n} {plural} in terms of {mp}{suffix}",
        ]  # fmt: skip
    return ctx.pick_template(templates), out


def gen_trend(ctx: Ctx) -> tuple[str, dict]:
    rng = ctx.rng
    col, agg, ph = pick_metric(rng, ["sum", "avg", "count"])
    gran = rng.choice(list(GRAN))
    out: dict = {
        "intent_type": "trend", "metric": col, "agg": agg, "granularity": gran,
        "sort_direction": "asc", "time_column": DATE_COL,
    }  # fmt: skip
    used: set[str] = set()
    group = rng.choice(["carrier", "origin_warehouse"]) if rng.random() < 0.15 else None
    if group:
        used.add(group)
        out["group_by"] = [group]
    filt = maybe_filter(ctx, used, 0.35)
    tm = maybe_time(ctx, 0.25) if gran in ("day", "week") else None
    pl = maybe_plant(ctx, 0.2)
    filters = ([filt[1]] if filt else []) + (tm[1] if tm else [])
    if filters:
        out["filters"] = filters
    if pl:
        out["plants"] = [pl[1]]
    mp = ph if agg == "count" and col == "invoice_number" else f"{AGG_WORDS[agg][0]} {ph}"
    g = rng.choice(GRAN[gran])
    gw = {"day": "daily", "week": "weekly", "month": "monthly", "quarter": "quarterly"}[gran]
    tail = f"{(' for ' + filt[0]) if filt else ''}{(' ' + tm[0]) if tm else ''}{(' ' + pl[0]) if pl else ''}"
    tail += f" by {rng.choice(DIMS[group])}" if group else ""
    templates = [
        f"{gw} {mp} trend{tail}", f"{mp} {g}{tail}", f"how has {mp} changed over time {g}{tail}",
        f"show the trend of {mp} {g}{tail}", f"{mp} over time {g}{tail}", f"plot {mp} {g}{tail}",
        f"{gw} {mp}{tail}", f"time series of {mp} {g}{tail}",
    ]  # fmt: skip
    return ctx.pick_template(templates), out


def gen_forecast(ctx: Ctx) -> tuple[str, dict]:
    rng = ctx.rng
    col, agg, ph = pick_metric(rng, ["sum", "avg", "count"])
    n = rng.choice([1, 2, 3, 3, 4, 6])
    out: dict = {
        "intent_type": "forecast", "metric": col, "agg": agg, "granularity": "month",
        "horizon": n, "sort_direction": "asc", "time_column": DATE_COL,
    }  # fmt: skip
    used: set[str] = set()
    filt = maybe_filter(ctx, used, 0.3)
    pl = maybe_plant(ctx, 0.2)
    if filt:
        out["filters"] = [filt[1]]
    if pl:
        out["plants"] = [pl[1]]
    mp = ph if agg == "count" and col == "invoice_number" else f"{AGG_WORDS[agg][0]} {ph}"
    when = (
        rng.choice([f"next {n} months", f"for the next {n} months", f"over the coming {n} months"])
        if n > 1
        else rng.choice(["next month", "for next month"])
    )
    tail = f"{(' for ' + filt[0]) if filt else ''}{(' ' + pl[0]) if pl else ''}"
    verb = rng.choice(["forecast", "predict", "project", "estimate"])
    templates = [
        f"{verb} {mp}{tail} {when}", f"{verb} the {mp}{tail} {when}", f"what will the {mp}{tail} be {when}",
        f"what is the expected {mp}{tail} {when}", f"{when}: {verb} {mp}{tail}", f"give me a {verb} of {mp}{tail} {when}",
    ]  # fmt: skip
    return ctx.pick_template(templates), out


def gen_comparison(ctx: Ctx) -> tuple[str, dict]:
    rng = ctx.rng
    col, agg, ph = pick_metric(rng, ["sum", "avg", "count"])
    mp = ph if agg == "count" and col == "invoice_number" else f"{AGG_WORDS[agg][0]} {ph}"
    mode = rng.choice(["plants", "all_plants", "values", "dim"])
    out: dict = {"intent_type": "comparison", "metric": col, "agg": agg}
    tm = maybe_time(ctx, 0.2)
    tail = f" {tm[0]}" if tm else ""
    if tm:
        out["filters"] = tm[1]
    if mode == "plants":
        ps = rng.sample(PLANTS, rng.choice([2, 2, 3]))
        out |= {"compare_by_plant": True, "plants": sorted(ps)}
        names = ", ".join(ps[:-1]) + f" and {ps[-1]}"
        templates = [
            f"compare {names} {mp}{tail}", f"{names} {mp}{tail} comparison", f"compare {mp} between {names}{tail}",
            f"how does {mp} differ between {names}{tail}", f"{mp} {names} side by side{tail}",
            f"{ps[0]} versus {ps[1]} {mp}{tail}" if len(ps) == 2 else f"compare {mp} across {names}{tail}",
        ]  # fmt: skip
        if len(ps) == 3:
            templates = [t for t in templates if "versus" not in t] + [
                f"{names} {mp}{tail} compared"
            ] * 2
    elif mode == "all_plants":
        out["compare_by_plant"] = True
        templates = [
            f"compare {mp} across plants{tail}", f"{mp} by plant{tail}", f"plant wise {mp}{tail}",
            f"how do the plants compare on {mp}{tail}", f"{mp} per plant{tail}", f"break down {mp} by plant{tail}",
        ]  # fmt: skip
    elif mode == "values":
        dim = rng.choice(["carrier", "origin_warehouse", "destination_city"])
        a, b = sorted(rng.sample(list(column_values()[dim]), 2))
        out |= {"group_by": [dim], "keep_values": {dim: [a, b]}}
        sa, sb = surface(dim, a, rng), surface(dim, b, rng)
        templates = [
            f"compare {sa} and {sb} {mp}{tail}", f"{sa} versus {sb} {mp}{tail}", f"{sa} vs {sb} {mp}{tail}",
            f"how does {sa} stack up against {sb} on {mp}{tail}", f"{mp}: {sa} compared with {sb}{tail}",
            f"compare {mp} between {sa} and {sb}{tail}",
        ]  # fmt: skip
    else:
        dim = rng.choice(["carrier", "origin_warehouse", "destination_city"])
        out["group_by"] = [dim]
        d = rng.choice(DIMS[dim])
        templates = [
            f"compare {d}s by {mp}{tail}", f"{mp} comparison across {d}s{tail}", f"compare {mp} for each {d}{tail}",
            f"how do {d}s compare on {mp}{tail}", f"{d} wise {mp}{tail}", f"compare all {d}s on {mp}{tail}",
        ]  # fmt: skip
    return ctx.pick_template(templates), out


def gen_listing(ctx: Ctx) -> tuple[str, dict]:
    rng = ctx.rng
    used: set[str] = set()
    n_filters = rng.choice([1, 1, 2])
    parts, filters = [], []
    for _ in range(n_filters):
        f = maybe_filter(ctx, used, 1.0)
        assert f
        parts.append(f)
        filters.append(f[1])
    tm = maybe_time(ctx, 0.3)
    if tm:
        filters += tm[1]
    kind = "join" if any(f["column"] in TRACKING_OR_TAT for f in filters) else "filter"
    cols = (
        SELECT_COLS[kind]
        + (["current_status"] if "current_status" in used else [])
        + (["sla_status"] if "sla_status" in used else [])
    )
    out: dict = {
        "intent_type": kind,
        "filters": filters,
        "select_columns": list(dict.fromkeys(cols)),
        "limit": 20,
    }
    words = " ".join(p[0] for p in parts)
    tail = f" {tm[0]}" if tm else ""
    noun = rng.choice(["shipments", "deliveries", "consignments"])
    templates = [
        f"show {words} {noun}{tail}", f"list {words} {noun}{tail}", f"{noun} that are {words}{tail}",
        f"give me all {words} {noun}{tail}", f"which {noun} are {words}{tail}", f"find {words} {noun}{tail}",
        f"display the {words} {noun}{tail}", f"i want to see {words} {noun}{tail}",
    ]  # fmt: skip
    return ctx.pick_template(templates), out


def gen_oos(ctx: Ctx) -> tuple[str, dict]:
    return ctx.rng.choice(OUT_OF_SCOPE), {"intent_type": "out_of_scope"}


GENERATORS = [
    (gen_aggregation, 30), (gen_rank, 17), (gen_trend, 14), (gen_forecast, 8),
    (gen_comparison, 13), (gen_listing, 12), (gen_oos, 6),
]  # fmt: skip


def decorate(q: str, rng: random.Random) -> str:
    q = " ".join(q.split())
    r = rng.random()
    if r < 0.15:
        q = q.lower()
    elif r < 0.25:
        q = q[:1].upper() + q[1:]
    if rng.random() < 0.2:
        q += "?"
    if rng.random() < 0.06:
        q = rng.choice(["please ", "hey, ", "quick question: "]) + q
    return q


def system_prompt(today: date) -> str:
    values = "\n".join(f"- {c}: {', '.join(v)}" for c, v in sorted(column_values().items()))
    return (
        "Convert the logistics question into ONE JSON intent object. Reply with JSON only.\n"
        "Tables (joined on invoice_number): dispatch(invoice_number, dispatch_date, origin_warehouse, "
        "destination_city, carrier, shipment_weight_kg, freight_cost_usd); tracking(invoice_number, "
        "checkpoint_timestamp, current_status, last_known_location, driver_id); turnaround_time(invoice_number, "
        "promised_delivery_date, actual_delivery_date, loading_time_mins, unloading_time_mins, total_tat_hours, "
        "sla_status).\nValid values:\n" + values + "\nPlants: MCW, YCW, VGU.\n"
        "intent_type: aggregation|join|filter|forecast|comparison|trend|rank|out_of_scope. "
        f"Date ranges are gte/lt filters on dispatch_date. Today is {today.isoformat()}."
    )


def build(n_train: int, n_val: int) -> tuple[list[dict], list[dict], dict]:
    rng = random.Random(SEED)
    labeled = {
        json.loads(line)["query"].lower().strip(" ?")
        for line in (ROOT / "nlu/data/labeled_queries.jsonl").read_text().splitlines()
        if line.strip()
    }
    funcs = [g for g, w in GENERATORS for _ in range(w)]
    seen: set[str] = set()
    train: list[dict] = []
    val: list[dict] = []
    guard = 0
    while (len(train) < n_train or len(val) < n_val) and guard < (n_train + n_val) * 50:
        guard += 1
        heldout = len(val) < n_val and (
            len(train) >= n_train or rng.random() < n_val / (n_train + n_val)
        )
        ctx = Ctx(rng, heldout)
        q, target = rng.choice(funcs)(ctx)
        q = decorate(q, rng)
        key = q.lower().strip(" ?")
        if key in seen or key in labeled:
            continue
        seen.add(key)
        row = {
            "messages": [
                {"role": "system", "content": system_prompt(ctx.today)},
                {"role": "user", "content": q},
                {"role": "assistant", "content": json.dumps(target, sort_keys=True)},
            ],
            "meta": {
                "intent": target["intent_type"],
                "today": ctx.today.isoformat(),
                "heldout_phrasing": heldout,
            },
        }
        (val if heldout else train).append(row)
    counts: dict[str, dict[str, int]] = {"train": {}, "val": {}}
    for name, rows in (("train", train), ("val", val)):
        for r in rows:
            counts[name][r["meta"]["intent"]] = counts[name].get(r["meta"]["intent"], 0) + 1
    return train, val, counts


def main() -> None:
    train, val, counts = build(6000, 600)
    OUT.mkdir(exist_ok=True)
    for name, rows in (("train", train), ("val", val)):
        (OUT / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (OUT / "manifest.json").write_text(
        json.dumps(
            {"seed": SEED, "rows": {"train": len(train), "val": len(val)}, "by_intent": counts},
            indent=1,
        )
    )
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
