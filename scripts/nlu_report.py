"""Writes docs/nlu-calibration.md (T-21) and docs/nlu-latency.md (T-26) from real runs."""

import platform
import statistics
import time
from datetime import date
from pathlib import Path

from nlu.evaluation import calibration_table, evaluate, load_dataset
from nlu.parser import parse

DOCS = Path(__file__).resolve().parent.parent / "docs"
today = date(2026, 9, 15)

res = evaluate()
lines = [
    "# NLU calibration (T-21)",
    "",
    f"Rule parser on the {res.total} hand-labeled queries: intent accuracy "
    f"{res.intent_accuracy:.3f}, entity F1 {res.entity_f1:.3f}.",
    "",
    "A parse counts as correct only if intent and every entity match. A calibrated score has",
    "observed accuracy close to its confidence.",
    "",
    "| confidence bin | queries | observed accuracy |",
    "|---|---|---|",
]
for label, n, acc in calibration_table(res):
    lines.append(f"| {label} | {n} | {acc:.3f} |")
lines += [
    "",
    "The 0.0-0.2 bin holds the out-of-scope queries, which get confidence 0 by design.",
    "Caveat: the labeled set and the parser share one author and vocabulary, so these",
    "numbers are optimistic for unseen phrasing. Held-out checks against the hosted model are in",
    "docs/nlu-groq-prototype.md.",
]
(DOCS / "nlu-calibration.md").write_text("\n".join(lines) + "\n")

queries = [r["query"] for r in load_dataset()]
for q in queries[:5]:
    parse(q, today)  # warm-up (loads the vocabulary)
times = []
for i in range(500):
    q = queries[i % len(queries)]
    start = time.perf_counter()
    parse(q, today)
    times.append((time.perf_counter() - start) * 1000)
times.sort()
pct = lambda p: times[min(len(times) - 1, int(len(times) * p))]  # noqa: E731
lat = [
    "# NLU latency and SLA (T-26)",
    "",
    f"500 queries through the rule parser on {platform.platform()} ({platform.machine()}), "
    f"Python {platform.python_version()}.",
    "",
    f"- p50 {statistics.median(times):.3f} ms",
    f"- p95 {pct(0.95):.3f} ms",
    f"- p99 {pct(0.99):.3f} ms",
    "",
    "## SLA",
    "",
    "- Rule parser: p95 under 50 ms (enforced by tests/test_nlu_latency.py).",
    "- Hosted-model path (Groq): p95 under 3 s per parse; measured latency in",
    "  docs/nlu-groq-prototype.md. The confirm client's own timeout is budgeted inside this.",
]
(DOCS / "nlu-latency.md").write_text("\n".join(lat) + "\n")
print("p50/p95/p99 ms:", *(round(v, 3) for v in (statistics.median(times), pct(0.95), pct(0.99))))
