"""Hand-labeled NL query set (T-25). Run to regenerate nlu/data/labeled_queries.jsonl.

Every row is written by hand: query, correct intent, and the entities a correct
parse must contain. Reference date for relative expressions: 2026-09-15.
Entity strings: metric:X agg:X group:X filter:col=val date:col:start..end plant:X
limit:N gran:X horizon:N compare_plants keep:col=val
"""

import json
from pathlib import Path

W, F, T, L, U, N = (
    "shipment_weight_kg", "freight_cost_usd", "total_tat_hours",
    "loading_time_mins", "unloading_time_mins", "invoice_number",
)  # fmt: skip
JUN, JUL, AUG = (
    "date:dispatch_date:2026-06-01..2026-07-01",
    "date:dispatch_date:2026-07-01..2026-08-01",
    "date:dispatch_date:2026-08-01..2026-09-01",
)
rows: list[tuple[str, str, list[str]]] = []


def add(intent: str, q: str, *ents: str) -> None:
    rows.append((q, intent, list(ents)))


def agg(q, metric, op, *rest):
    add("aggregation", q, f"metric:{metric}", f"agg:{op}", *rest)


agg("What is the total freight cost in July 2026?", F, "sum", JUL)
agg("Total shipment weight for August 2026", W, "sum", AUG)
agg("average turnaround time by carrier", T, "avg", "group:carrier")
agg("How many shipments were dispatched in June 2026?", N, "count", JUN)
agg("total freight cost by carrier", F, "sum", "group:carrier")
agg("What's the average loading time?", L, "avg")
agg("average unloading time by origin warehouse", U, "avg", "group:origin_warehouse")
agg("maximum freight cost by destination city", F, "max", "group:destination_city")
agg("minimum shipment weight by carrier", W, "min", "group:carrier")
agg("how many delayed shipments are there", N, "count", "filter:current_status=Delayed")
agg("How many shipments are on time?", N, "count", "filter:sla_status=On Time")
agg("total freight cost for DHL", F, "sum", "filter:carrier=DHL")
agg("average TAT for FedEx in August", T, "avg", "filter:carrier=FedEx", AUG)
agg("total weight shipped from Chicago", W, "sum", "filter:origin_warehouse=Chicago_WH")
agg("number of shipments to Boston", N, "count", "filter:destination_city=Boston")
agg("total freight cost to Seattle last month", F, "sum", "filter:destination_city=Seattle", AUG)
agg("total weight by status", W, "sum", "group:current_status")
agg("count of shipments by sla status", N, "count", "group:sla_status")
agg(
    "average TAT for delayed shipments by carrier",
    T,
    "avg",
    "group:carrier",
    "filter:current_status=Delayed",
)
agg("total freight cost for MCW", F, "sum", "plant:MCW")
agg("average TAT at YCW by carrier", T, "avg", "group:carrier", "plant:YCW")
agg("total weight for VGU in July", W, "sum", "plant:VGU", JUL)
agg("how many shipments did UPS handle in July 2026", N, "count", "filter:carrier=UPS", JUL)
agg(
    "sum of freight cost by origin warehouse in Q3 2026",
    F,
    "sum",
    "group:origin_warehouse",
    "date:dispatch_date:2026-07-01..2026-10-01",
)
agg(
    "total freight cost for the last 30 days", F, "sum", "date:dispatch_date:2026-08-16..2026-09-16"
)
agg("average loading time for Dallas", L, "avg", "filter:origin_warehouse=Dallas_WH")
agg("highest freight cost by carrier", F, "max", "group:carrier")
agg("overall shipment weight", W, "sum")
agg("total freight spend for UPS in August 2026", F, "sum", "filter:carrier=UPS", AUG)
agg("average unloading time to Phoenix", U, "avg", "filter:destination_city=Phoenix")
agg(
    "how many shipments from Atlanta to Houston",
    N,
    "count",
    "filter:origin_warehouse=Atlanta_WH",
    "filter:destination_city=Houston",
)
agg("total weight of customs hold shipments", W, "sum", "filter:current_status=Customs Hold")
agg("number of shipments out for delivery", N, "count", "filter:current_status=Out for Delivery")
agg("total freight cost for JB Hunt", F, "sum", "filter:carrier=JB Hunt")
agg("avg tat by destination city", T, "avg", "group:destination_city")
agg("total cost by warehouse in June", F, "sum", "group:origin_warehouse", JUN)
agg(
    "average weight by carrier for Chicago in July 2026",
    W,
    "avg",
    "group:carrier",
    "filter:origin_warehouse=Chicago_WH",
    JUL,
)
agg(
    "count shipments by carrier in Q2 2026",
    N,
    "count",
    "group:carrier",
    "date:dispatch_date:2026-04-01..2026-07-01",
)
agg(
    "How many XPO shipments were delayed?",
    N,
    "count",
    "filter:carrier=XPO Logistics",
    "filter:current_status=Delayed",
)
agg("total freight cost for FY26", F, "sum", "date:dispatch_date:2025-04-01..2026-04-01")
agg("mean freight cost by carrier", F, "avg", "group:carrier")
agg("total weight from Columbus in August", W, "sum", "filter:origin_warehouse=Columbus_WH", AUG)
agg("average TAT by sla status", T, "avg", "group:sla_status")
agg("total frieght cost for Dalas", F, "sum", "filter:origin_warehouse=Dallas_WH")
agg("avg loading time for fedx", L, "avg", "filter:carrier=FedEx")
agg(
    "how many shipments from Atlanta were late",
    N,
    "count",
    "filter:origin_warehouse=Atlanta_WH",
    "filter:current_status=Delayed",
)


def rank(q, metric, op, dim, n, *rest):
    add("rank", q, f"metric:{metric}", f"agg:{op}", f"group:{dim}", f"limit:{n}", *rest)


rank("top 5 carriers by freight cost", F, "sum", "carrier", 5)
rank("top 3 destination cities by shipment weight", W, "sum", "destination_city", 3)
rank(
    "which carrier has the most delayed shipments",
    N,
    "count",
    "carrier",
    1,
    "filter:current_status=Delayed",
)
rank("bottom 2 warehouses by average TAT", T, "avg", "origin_warehouse", 2)
rank("top 3 cities by number of shipments", N, "count", "destination_city", 3)
rank("which warehouse has the highest freight cost", F, "sum", "origin_warehouse", 1)
rank("which carrier has the lowest average TAT", T, "avg", "carrier", 1)
rank("top 3 carriers by total weight in August", W, "sum", "carrier", 3, AUG)
rank("top 10 destinations by freight cost in July 2026", F, "sum", "destination_city", 10, JUL)
rank("which destination city has the most shipments", N, "count", "destination_city", 1)
rank("bottom 3 carriers by freight cost", F, "sum", "carrier", 3)
rank("top 2 warehouses by weight for MCW", W, "sum", "origin_warehouse", 2, "plant:MCW")


def trend(q, metric, op, gran, *rest):
    add("trend", q, f"metric:{metric}", f"agg:{op}", f"gran:{gran}", *rest)


trend("monthly freight cost trend", F, "sum", "month")
trend("weight trend over time", W, "sum", "month")
trend("daily shipments in August 2026", N, "count", "day", AUG)
trend("weekly freight cost for DHL", F, "sum", "week", "filter:carrier=DHL")
trend("month over month average TAT", T, "avg", "month")
trend("quarterly freight cost", F, "sum", "quarter")
trend("freight cost per month by carrier", F, "sum", "month", "group:carrier")
trend("monthly number of delayed shipments", N, "count", "month", "filter:current_status=Delayed")
trend("trend of average loading time by month", L, "avg", "month")
trend("monthly weight for Chicago", W, "sum", "month", "filter:origin_warehouse=Chicago_WH")
trend("freight cost by month for MCW", F, "sum", "month", "plant:MCW")
trend("weekly average unloading time in July", U, "avg", "week", JUL)


def fc(q, metric, op, n, *rest):
    add("forecast", q, f"metric:{metric}", f"agg:{op}", f"horizon:{n}", "gran:month", *rest)


fc("forecast freight cost for the next 3 months", F, "sum", 3)
fc("predict shipment weight next 2 months", W, "sum", 2)
fc("forecast number of shipments next 3 months", N, "count", 3)
fc("forecast freight cost for DHL next 2 months", F, "sum", 2, "filter:carrier=DHL")
fc("projected weight for the next 6 months", W, "sum", 6)
fc("forecast average TAT next 3 months", T, "avg", 3)
fc("forecast freight cost for MCW", F, "sum", 3, "plant:MCW")
fc("predict shipments for the next 4 months", N, "count", 4)


def cmp_(q, metric, op, *rest):
    add("comparison", q, f"metric:{metric}", f"agg:{op}", *rest)


fc("forecast loading time next 3 months", L, "avg", 3)
fc("predict freight cost for UPS next 3 months", F, "sum", 3, "filter:carrier=UPS")
fc("forecast weight for Chicago next 2 months", W, "sum", 2, "filter:origin_warehouse=Chicago_WH")

cmp_("compare MCW and YCW freight cost", F, "sum", "plant:MCW", "plant:YCW", "compare_plants")
cmp_("compare freight cost across plants", F, "sum", "compare_plants")
cmp_(
    "compare DHL and FedEx freight cost",
    F,
    "sum",
    "group:carrier",
    "keep:carrier=DHL",
    "keep:carrier=FedEx",
)
cmp_(
    "compare average TAT between MCW and VGU", T, "avg", "plant:MCW", "plant:VGU", "compare_plants"
)
cmp_(
    "DHL versus UPS shipments", N, "count", "group:carrier", "keep:carrier=DHL", "keep:carrier=UPS"
)
cmp_(
    "compare Chicago and Dallas weight",
    W,
    "sum",
    "group:origin_warehouse",
    "keep:origin_warehouse=Chicago_WH",
    "keep:origin_warehouse=Dallas_WH",
)
cmp_("compare carriers by freight cost", F, "sum", "group:carrier")
cmp_(
    "compare MCW, YCW and VGU total weight",
    W,
    "sum",
    "plant:MCW",
    "plant:YCW",
    "plant:VGU",
    "compare_plants",
)
cmp_(
    "compare UPS and DHL freight cost",
    F,
    "sum",
    "group:carrier",
    "keep:carrier=UPS",
    "keep:carrier=DHL",
)
cmp_("compare weight between MCW and YCW", W, "sum", "plant:MCW", "plant:YCW", "compare_plants")
add("aggregation", "freight cost by plant", f"metric:{F}", "agg:sum", "compare_plants")

add("filter", "list shipments from Chicago in July 2026", "filter:origin_warehouse=Chicago_WH", JUL)
add("filter", "show FedEx shipments in August", "filter:carrier=FedEx", AUG)
add(
    "filter",
    "display shipments from Dallas to Miami",
    "filter:origin_warehouse=Dallas_WH",
    "filter:destination_city=Miami",
)
add("filter", "show me shipments handled by UPS in June", "filter:carrier=UPS", JUN)
add("filter", "show DHL shipments for MCW", "filter:carrier=DHL", "plant:MCW")
add("join", "show delayed shipments", "filter:current_status=Delayed")
add("join", "show shipments to Boston with driver id", "filter:destination_city=Boston")
add("join", "list DHL shipments with their sla status", "filter:carrier=DHL")
add("join", "show customs hold shipments", "filter:current_status=Customs Hold")
add("join", "list late shipments", "filter:current_status=Delayed")
add(
    "join",
    "show on time shipments from Atlanta",
    "filter:sla_status=On Time",
    "filter:origin_warehouse=Atlanta_WH",
)
add("join", "list shipments in transit", "filter:current_status=In Transit")

add("filter", "list shipments from Atlanta", "filter:origin_warehouse=Atlanta_WH")
add("filter", "show shipments to Seattle in August", "filter:destination_city=Seattle", AUG)
add("filter", "list UPS shipments in July", "filter:carrier=UPS", JUL)
add(
    "filter",
    "show JB Hunt shipments from Dallas",
    "filter:carrier=JB Hunt",
    "filter:origin_warehouse=Dallas_WH",
)
add("filter", "display XPO shipments in June 2026", "filter:carrier=XPO Logistics", JUN)
add(
    "filter",
    "list shipments from Columbus to Denver",
    "filter:origin_warehouse=Columbus_WH",
    "filter:destination_city=Denver",
)
add("join", "show shipments delayed in August", "filter:current_status=Delayed", AUG)
add("join", "list out for delivery shipments", "filter:current_status=Out for Delivery")
add(
    "join",
    "show DHL shipments in transit",
    "filter:carrier=DHL",
    "filter:current_status=In Transit",
)
add(
    "join",
    "list on time shipments from Dallas",
    "filter:sla_status=On Time",
    "filter:origin_warehouse=Dallas_WH",
)
add("join", "show delayed UPS shipments", "filter:current_status=Delayed", "filter:carrier=UPS")

for q in [
    "optimise my delivery routes",
    "what is the HSN code for ball bearings",
    "calculate customs duty for 8482",
    "simulate a 7 day port shutdown",
    "what's the weather in Pune",
    "calculate EOQ for SKU ABC",
    "generate an eway bill",
    "how do I make cement",
    "tell me a joke",
    "who is the CEO",
    "plan routes for 35 dealers using VRP",
    "reorder point for SKU F001",
    "bin packing for 500 cartons",
    "run a monte carlo on lead time",
    "what is GST on freight",
    "hello",
    "send an email to the logistics team",
    "track truck TN09AB1234",
]:
    add("out_of_scope", q)

if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "nlu" / "data" / "labeled_queries.jsonl"
    with out.open("w") as fh:
        for q, intent, ents in rows:
            fh.write(json.dumps({"query": q, "intent": intent, "entities": sorted(ents)}) + "\n")
    print(len(rows), "rows ->", out)
