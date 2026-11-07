"""Live prototype of the hosted-LLM parser on 20 labeled queries (T-18). Writes
docs/nlu-groq-prototype.md. Reads GROQ_API_KEY from the environment or .env."""

import os
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = ROOT / ".env"
if "GROQ_API_KEY" not in os.environ and env.exists():
    for line in env.read_text().splitlines():
        if line.startswith("GROQ_API_KEY="):
            os.environ["GROQ_API_KEY"] = line.split("=", 1)[1].strip()

from common.groq_client import GroqClient, GroqClientError  # noqa: E402
from nlu.evaluation import EVAL_TODAY, entity_set, load_dataset  # noqa: E402
from nlu.groq_parser import MODEL, GroqParseError, parse_with_groq  # noqa: E402

rows = load_dataset()
sample = rows[:: max(1, len(rows) // 20)][:20]
client = GroqClient(timeout=30.0, max_retries=2)
results = []
for row in sample:
    start = time.perf_counter()
    try:
        got = parse_with_groq(row["query"], client, EVAL_TODAY)
        ok_intent = got.intent_type.value == row["intent"]
        exact = ok_intent and entity_set(got) == set(row["entities"])
        note = "" if exact else f"got {got.intent_type.value} {sorted(entity_set(got))}"
    except (GroqClientError, GroqParseError) as exc:
        ok_intent = exact = False
        note = f"error: {str(exc)[:120]}"
    ms = (time.perf_counter() - start) * 1000
    results.append((row["query"], row["intent"], ok_intent, exact, ms, note))
    time.sleep(0.5)

lat = sorted(r[4] for r in results)
lines = [
    f"# NLU prototype: hosted LLM ({MODEL}) vs the rule parser",
    "",
    f"Sample: {len(results)} labeled queries (every nth row of nlu/data/labeled_queries.jsonl).",
    f"- Intent correct: {sum(r[2] for r in results)}/{len(results)}",
    f"- Exact entity match: {sum(r[3] for r in results)}/{len(results)}",
    f"- Latency p50 {statistics.median(lat):.0f} ms, max {lat[-1]:.0f} ms",
    "",
    "| query | want | intent ok | exact | ms | note |",
    "|---|---|---|---|---|---|",
]
for q, intent, ok, exact, ms, note in results:
    lines.append(f"| {q} | {intent} | {ok} | {exact} | {ms:.0f} | {note} |")
out = ROOT / "docs" / "nlu-groq-prototype.md"
out.write_text("\n".join(lines) + "\n")
print(out, sum(r[2] for r in results), sum(r[3] for r in results), len(results))
