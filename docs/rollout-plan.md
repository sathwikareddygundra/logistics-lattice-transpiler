# Rollout plan (T-97)

The numbers below are the constants in [ops/rollout.py](../ops/rollout.py); a test fails if this page and the code disagree.

## Order

1. **MCW** (SQLite)
2. **YCW** (DuckDB)
3. **VGU** (PostgreSQL)

MCW goes first because it is the simplest engine, so problems are cheapest to fix there. VGU goes last because it is a real server with the most moving parts.

## Gate to advance to the next plant

Measure over the live traffic of the plant that is currently rolling out. Every line must hold.

| Metric | Threshold |
|---|---|
| Queries seen | at least 200 |
| Failure rate (`lattice_failures_total` / `lattice_queries_total`) | at most 2% |
| Stage latency p95 (`lattice_stage_latency_ms`) | at most 2000 ms |
| Results whose row count differs from the estimate by 10x or more | 0 |

`ops.rollout.may_advance(snapshot, plant)` returns yes/no plus the reasons.

## Rollback trigger

Roll the plant back if any of these happens:

- A result differs from its row-count estimate by 10x or more (the T-86 rule). This also blocks promotion.
- The failure rate stays above 2% for 15 minutes.
- Any `schema_drift` failure appears (see the runbook).

## Rollback procedure

1. Stop sending questions for that plant: remove it from the list of enabled plants in the service config, and redeploy.
2. Confirm the change: the plant's `lattice_queries_total` stops rising on the dashboard.
3. Collect evidence: take a few `trace_id` values from the failing queries (see [runbook](runbook.md)) and save the matching log lines.
4. Fix, then repeat the gate from the start for that plant. Plants after it in the order stay off until it passes.
