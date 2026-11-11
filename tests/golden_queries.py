"""One representative query per intent family; the golden files are generated from these."""

GOLDEN_QUERIES = {
    "agg_sum_group": "total freight cost by carrier in August 2026",
    "agg_join_avg": "average TAT by carrier",
    "agg_count_filter": "how many delayed shipments",
    "rank_top": "top 3 destinations by freight cost",
    "rank_count": "which carrier has the most delayed shipments",
    "trend_month": "monthly weight trend",
    "trend_week_filter": "weekly freight cost for DHL",
    "forecast": "forecast freight cost next 2 months",
    "compare_plants": "compare MCW and YCW freight cost",
    "compare_values": "compare DHL and FedEx freight cost",
    "list_filter": "list shipments from Chicago in July 2026",
    "list_join": "show delayed shipments from Atlanta",
}
GOLDEN_TODAY = (2026, 9, 15)
