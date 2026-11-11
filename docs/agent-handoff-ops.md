# Handoff prompt: ops, load test and docs (independent of the main build)

Copy everything below the line into a fresh agent session. Time budget: about 2 hours in total.

---

You are working on the repo `logistics-lattice-transpiler` (Python 3.11+, uv, pytest, ruff, mypy). It is an NL-to-SQL/Python transpiler: question in English -> SQL/pandas code per plant database -> sandboxed run -> merged answer. Another agent is rewriting the core (folders `nlu/ dag/ ir/ ast_/ codegen/ cag/ plan/ plantdb/ sandbox/ confirm/ graph_eng/ feedback/`, plus `pipeline.py`, `schemas/`, `tests/*.py`, `dashboard/`). You own ONLY the files listed per work package below. Do not edit anything else, even to "fix" it. If you think something outside your files is broken, write it in your final report instead.

## Setup (5 min)

1. `cd ~/logistics-lattice-transpiler`
2. Work in a separate worktree so you never touch the other agent's working directory:
   `git fetch origin && git worktree add ../lattice-ops -b feature/ops-handoff origin/feature/T-slice-end-to-end && cd ../lattice-ops`
3. `uv sync` then confirm the baseline is green: `uv run ruff check . && uv run mypy . && uv run pytest -q` (expect about 120 tests passing).
4. Never read, print or commit `.env` or any API key. You do not need a Groq key or network access for any of this.
5. The public API you may rely on (stable, do not change it):
   - `from plantdb.plants import build_plant_databases, Plant, PROFILES` -> `build_plant_databases(tmp_dir)` returns `{Plant: Path}` for the three plant databases (MCW, YCW, VGU).
   - `from pipeline import answer` -> `answer(query: str, databases: dict[Plant, Path], today: date | None = None) -> PipelineResult` with `.status` in {ok, partial, needs_slot, needs_confirmation, out_of_scope, failed}, `.frame` (pandas DataFrame or None), `.branches` (list of per-plant runs with `.ms`, `.error`, `.error_stage`).
   - Labeled queries: `nlu/data/labeled_queries.jsonl` (one JSON per line: `query`, `intent`, `entities`). Use rows whose `intent` is not `out_of_scope`. Pass `today=date(2026, 9, 15)`.
   - Log noise: `answer()` prints structlog JSON lines to stdout. In your scripts, silence it with `structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(50))` before running.

## Work package A: documentation (about 25 min). Files you own: `README.md`, `CONTRIBUTING.md`, `docs/ARCHITECTURE.md`

- `README.md`: what the project is (2 paragraphs), the pipeline line `schema -> NLU -> confirm -> DAG -> graph_eng -> CAG -> IR -> AST -> codegen -> sandbox`, setup (`uv sync`), how to run the tests/linters, a worked example (copy a real query and its generated SQL by running `answer()` yourself; paste the real output), repo map (one line per top-level folder, read the code to get it right), and a "status" section that links to `docs/PROJECT_PLAN.md`.
- `docs/ARCHITECTURE.md`: one section per stage (purpose, input type, output type, key module), a data-flow diagram in a fenced text block, the multi-plant design (one branch per plant, local aggregation, merge in `plan/federation.py`), and the determinism rule (everything after confirm is a pure function).
- `CONTRIBUTING.md`: keep the existing branch-naming and PR-template content; add: how to run the full check (`uv run ruff check . && uv run mypy . && uv run pytest -q`), how to rebuild golden/snapshot files if a test says to, and the rule "never commit `.env`".
- Done when: every command and code path you mention exists (verify each by running or opening it), no TODO placeholders, ruff/mypy/pytest still pass.

## Work package B: load test, task T-95 (about 35 min). Files you own: `loadtest/run_loadtest.py`, `docs/loadtest-results.md`

- Write `loadtest/run_loadtest.py` (plain script, run with `uv run python loadtest/run_loadtest.py`). It builds the plant databases once in a temp dir, loads the non-out-of-scope labeled queries, and runs them through `answer()` with a `ThreadPoolExecutor` at a given concurrency, recording per-query wall time, status and any exception.
- Run three scenarios, each with 300 queries (cycle the dataset): concurrency 1 (baseline), 4 (target), 8 (2x target). Report for each: p50/p95/p99 latency in ms, queries per second, count of statuses, count of exceptions.
- Pass criteria to check and state explicitly in the doc: zero uncaught exceptions at 8, no hang (the whole run finishes), p95 at concurrency 4 under 2000 ms. If something fails, record exactly what and why; do not change any file outside your two.
- Put the results, the machine (run `uname -a` and `sysctl -n machdep.cpu.brand_string`), the date, and the exact command in `docs/loadtest-results.md`. Numbers must come from your actual run, never invented.
- Done when: the doc exists with real numbers for all three scenarios and a short "what limits throughput" paragraph based on what you observed (for example the sandbox opening a fresh database connection per query).

## Work package C: ops package, tasks T-96 to T-100 (about 60 min). Files you own: everything under `ops/`, `tests/ops/`, `docs/rollout-plan.md`, `docs/runbook.md`

Create the package `ops/` with an `__init__.py`. Pure library code with no imports from `pipeline`, `nlu`, `dag`, `ir`, `ast_`, `codegen`, `cag`, `plan`, `sandbox` (the main agent will wire it in later). Put tests in `tests/ops/` (add `tests/ops/__init__.py` only if pytest needs it). Use the fixed failure-category names below everywhere:

`syntax_error, semantic_mismatch, intent_mismatch, timeout, resource_limit, permission, schema_drift`

1. `ops/metrics.py` (T-98 support): a small in-process registry (no third-party dependency): `Counter`, `Histogram` (fixed buckets in ms), labels as a dict, thread-safe, plus `render_prometheus() -> str` (valid Prometheus text exposition format) and `snapshot() -> dict`. Required metric names: `lattice_stage_latency_ms{stage}` (histogram), `lattice_queries_total{status}`, `lattice_confirm_triggered_total`, `lattice_failures_total{category}` (category from the fixed list; reject unknown categories with a `ValueError`).
2. `ops/rollout.py` (T-97): constants, each with a docstring saying where the number comes from: `ROLLOUT_ORDER = ("MCW", "YCW", "VGU")`, advance-gate thresholds (minimum queries, max failure rate, max p95), and the rollback trigger reusing the T-86 rule: a result whose actual row count differs from the estimate by 10x or more blocks promotion (`ROW_COUNT_MISMATCH_FACTOR = 10`). Add `def may_advance(snapshot, plant) -> tuple[bool, list[str]]` returning the reasons.
3. `ops/alerts.py` (T-99): `AlertRule` dataclass and `evaluate(snapshot) -> list[Alert]`. Page-worthy thresholds must be derived from the constants in `ops/rollout.py`, not separate literals. Tests must include a synthetic breach: build a snapshot over the threshold and assert the alert fires; a snapshot just under the threshold must not fire.
4. `ops/drift.py` (T-96): `schema_fingerprint(db_path, engine)` for `sqlite` and `duckdb` (tables -> columns -> declared types, hashed, deterministic); `check_drift(prod_fp, staging_fp, max_lag)` returning a result object with the added/removed/changed columns; `alert_on_drift(...)` returning an `Alert` when the drift exceeds `max_lag` changed tables. Test with temporary SQLite databases you create in the test (ALTER TABLE ADD COLUMN to simulate drift). Duckdb test uses a temporary file.
5. `ops/grafana/lattice-dashboard.json` (T-98): a valid Grafana dashboard JSON with panels for per-stage latency (p50/p95/p99 from the histogram), confirm-trigger rate, and failures by category (use all seven categories), plus the rollout gate metrics. Add a test that loads the JSON and asserts every metric name used in its panel queries exists in `ops.metrics` (so the dashboard cannot reference a metric nobody emits).
6. `docs/rollout-plan.md` (T-97): rollout order MCW then YCW then VGU; for each step the advance-gate metrics and numeric thresholds (import them from `ops/rollout.py` conceptually; the doc must state the same numbers as the constants, and a test must assert the doc contains each constant's value); the rollback trigger and the concrete rollback procedure.
7. `docs/runbook.md` (T-100): one entry per failure category from the fixed list. Each entry: symptom (what the user or alert shows), likely causes, diagnosis steps (specific commands/queries, for example how to find the trace_id in the JSON logs and grep it), remediation, and escalation. Written for someone who did not build the system. No jargon without explanation. A test asserts there is exactly one entry per category and none is empty.
- Done when: `uv run pytest -q tests/ops` passes, `uv run ruff check . && uv run mypy .` pass for your files, and the Prometheus output parses (check it with a regex in a test; do not add a dependency).

## Rules for all packages

- Commit after each package with a message like `ops: <what> (T-xx)`; end each commit message with the line `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Push the branch (`git push -u origin feature/ops-handoff`) after each package. Do not open a PR and do not merge. Do not rebase onto or touch the branch `feature/T-slice-end-to-end`.
- Do not add dependencies to `pyproject.toml` (if you truly need one, stop and say so in the report).
- If `uv run pytest -q` shows failures in files you do not own, report them; do not fix them.

## Final report (reply in this exact format)

```
PACKAGE A: done | partial | not done  -> files changed, commit hash
PACKAGE B: ...                         -> real numbers: c=1 p95=..ms, c=4 p95=..ms, c=8 p95=..ms, exceptions=..
PACKAGE C: ...                         -> list the 5 modules + 2 docs, test count
Full check output: ruff <pass/fail>, mypy <pass/fail>, pytest <N passed, M failed>
Problems found outside my files: <bullets, or "none">
Deviations from this prompt: <bullets, or "none">
```
