# Load test results (T-95)

- Date: 2026-11-08
- Machine: Apple M3 (MacBook Air), `Darwin 24.6.0 arm64`
- Command: `uv run python loadtest/run_loadtest.py` (300 queries per scenario, cycling the labeled queries that are not out of scope; the three plant databases are built once, VGU on SQLite)
- Target peak is concurrency 4; concurrency 8 is 2x peak.

| Concurrency | p50 ms | p95 ms | p99 ms | Queries/s | Wall time | Statuses | Exceptions |
|---|---|---|---|---|---|---|---|
| 1 (baseline) | 39.7 | 89.6 | 92.8 | 21.5 | 13.9 s | ok 298, needs_confirmation 2 | 0 |
| 4 (target) | 41.5 | 95.1 | 127.3 | 83.5 | 3.6 s | ok 298, needs_confirmation 2 | 0 |
| 8 (2x) | 67.1 | 217.4 | 290.6 | 94.5 | 3.2 s | ok 298, needs_confirmation 2 | 0 |

## Pass criteria

- Zero uncaught exceptions at concurrency 8: **pass** (0).
- No hang: **pass** (each run finished in under 14 s).
- p95 at concurrency 4 under 2000 ms: **pass** (95.1 ms).

The two `needs_confirmation` results are labeled queries the parser is not confident about; the pipeline asks the user, which is correct behavior, not a failure.

## What limits throughput

- Throughput stops growing between 4 and 8 workers (83.5 to 94.5 queries/s) while p95 more than doubles. The workers are Python threads in one process, so they share one interpreter lock; the work is mostly CPU in code generation and result handling, which does not run in parallel.
- Each query opens a fresh read-only database connection in the sandbox, which adds a fixed cost per query.
- The concurrency 1 run went first and includes warm-up (imports, first-time caches), so its queries/s understates steady state and the 4x gain at concurrency 4 is partly warm-up, not pure parallelism. I did not run a second baseline to separate the two.

## Not covered

- All three plants ran on local embedded engines (VGU on SQLite, not PostgreSQL), on one laptop. A networked database, real data volumes beyond these 10,000 invoices, or separate processes were not tested.
- The Groq language-model path was not exercised (the rule-based parser handled these queries).
