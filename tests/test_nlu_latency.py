"""Latency regression gate for the rule parser (T-26)."""

import time
from datetime import date

from nlu.evaluation import load_dataset
from nlu.parser import parse

RULE_PARSER_P95_SLA_MS = 50.0


def test_rule_parser_p95_within_sla():
    queries = [r["query"] for r in load_dataset()]
    parse(queries[0], date(2026, 9, 15))  # warm-up
    times = []
    for i in range(500):
        start = time.perf_counter()
        parse(queries[i % len(queries)], date(2026, 9, 15))
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    assert times[int(len(times) * 0.95)] < RULE_PARSER_P95_SLA_MS
