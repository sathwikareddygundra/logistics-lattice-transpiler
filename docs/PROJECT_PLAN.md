# Project Plan: Rules, Phases, Requirements

Source: *Logistics Lattice Transpiler: a beginner's build guide* (T-1 to T-100). This doc condenses it into working rules, a phase map with gates, and the requirements and open decisions to settle before executing. Task IDs match the guide. Read the guide for per-task "How" steps.

Goal: a tested, monitored NL-to-SQL/Python transpiler for logistics data.

Pipeline: `schema -> NLU -> confirm -> DAG -> graph_eng -> CAG -> IR -> AST -> codegen -> sandbox`

The NLU and confirm stages are the only probabilistic ones (LLM). Everything from DAG onward is deterministic compiler work.

---

## 1. Ruleset

### Workflow
1. One branch per task or tightly coupled task pair: `feature/T-<n>-<slug>`. Merge to `main` by PR only; never push to `main`.
2. PR description: what changed, which task ID, how it was tested (see CONTRIBUTING.md).
3. Work phases in order; inside a phase, numeric order unless a task says "Depends on" or "Wait until".
4. A task is finished only when its "Done when" check passes. That check is the acceptance test, so write it as an automated test where possible.
5. CI must be green (ruff, mypy, pytest, secrets-scan) before merge. Never merge with a skipped or weakened check.

### Architecture rules
6. **Determinism after confirm.** DAG, graph_eng, CAG, IR, AST and codegen are pure functions: same input gives byte-identical output. No network or LLM calls (T-52, T-55 enforce this with tests).
7. **Total mappings.** Every DAG-to-IR, IR-to-AST and node-to-template step must handle every type. An unmapped type raises immediately; never drop it silently or fall back to "close enough" (T-51, T-57, T-64).
8. **Typed errors, never bare exceptions.** Unknown plant, version, template or node type each raise a specific typed error. Error messages name the offending object (`table.column`, cycle path, node id).
9. **Golden artifacts are the regression net.** Frozen golden DAG/IR/AST (D-2) and golden execution results (D-1) gate CI at every layer. Drift fails the build.
10. **Optimizations must prove equivalence.** Any optimizer pass is idempotent and checked by the semantic-equivalence suite (T-47). "Faster" never ships if results differ.
11. **Contracts are versioned.** Every JSON schema carries a `version`; changes follow the breaking-change policy (docs/T-16-schema-versioning-policy.md). Templates and cache keys are versioned too (T-53, T-54).
12. **Generated code never touches production.** Execution is sandboxed with read-only or replica credentials, hard timeout and row cap (T-81, T-83).
13. **Thread `trace_id` explicitly** through every stage as an argument, not global state. Each stage logs stage, trace_id, duration and outcome as JSON (T-6, T-87).

### Quality and safety rules
14. No secrets in code or git. Config comes from environment variables or a secret manager; missing required config fails at startup with a readable message (T-8). Only `.env.example` is tracked.
15. All timeouts, thresholds and retry caps are named constants or typed config, never magic numbers (T-5, T-29, T-32, T-92).
16. All retries are bounded. Each loop (confirm re-prompt, codegen retry, intent retry) is covered by a test that forces the cap and checks termination; T-92 puts a shared budget across them.
17. PII is stripped or hashed before any interaction or failure data is stored (T-33, T-93).
18. Prefer the simplest approach that meets the "Done when" check. Record non-obvious choices as ADRs in `docs/`: NLU approach (T-18), CAG boundary (T-48), AST grammar (T-63), Python library (T-69), join-tree shape (T-44).
19. Don't build ahead. A schema task that says "wait until T-xx" waits.
20. Tag generated code with provenance: original NL query, template versions (T-54, T-73, T-79).

### Quality gates to wire into CI
| Gate | Threshold | Task |
|---|---|---|
| NLU intent accuracy | >= 85% | T-25 |
| NLU entity F1 | >= 0.9 | T-19, T-25 |
| NLU latency | p95 within written SLA | T-26 |
| Golden DAG / IR / AST snapshots | exact match | T-40, T-62, T-68 |
| Generated Python and SQL vs frozen results | row-for-row match | T-74, T-80 |
| End-to-end golden suite (all plants) | all pass | T-94 |
| Template body changed without version bump | fail | T-54 |
| CAG repeat runs and no-LLM guard | identical, guard passes | T-52, T-55 |

---

## 2. Phases

Status reflects the earlier experimental repo work, which is a starting point only and may be reworked (see section 4).

| # | Phase | Tasks | Output | Status |
|---|---|---|---|---|
| 1 | Project and infrastructure | T-1 to T-8 | monorepo, uv lockfile, branching, Groq client, logging, CI, env configs | Mostly done (some T-6/T-8/T-9 work is on unmerged branches) |
| 2 | Schema and data contracts | T-9 to T-16 | source inventory, canonical models, registry, JSON schemas, versioning | T-9 to T-11, T-13 to T-16 done. T-12 (intent schema) is on its own branch, waiting on T-17 |
| 3 | NLU | T-17 to T-26 | intent taxonomy, extraction, slot-filling, confidence, prompts, labeled set, latency SLA | Not started (T-17 on a branch) |
| 4 | Confirm-intent (Groq) | T-27 to T-33 | paraphrase, threshold routing, yes/no hook, bounded re-prompt, training-data log | Not started |
| 5 | DAG constructor | T-34 to T-40 | intent-to-DAG compiler, dependency inference, cycle check, serialization, multi-plant branches | T-34 done. Rest not started |
| 6 | Graph engineering | T-41 to T-47 | optimizer passes, topo sort, cost model, join order, predicate push-down, equivalence tests | Not started |
| 7 | CAG | T-48 to T-55 | schema-aware context, template library and selection, cache, versioning, determinism proof | Not started |
| 8 | IR lowering | T-56 to T-62 | IR grammar, DAG+CAG to IR, type-check, registry validation, plant quirks, golden tests | T-56 done. Rest not started |
| 9 | AST builder | T-63 to T-68 | target AST, IR to AST, well-formedness, AST optimizer, golden tests | T-63 done. Rest not started |
| 10 | Python codegen | T-69 to T-74 | templates, generation, imports, formatting, provenance, golden execution tests | Not started |
| 11 | SQL codegen | T-75 to T-80 | dialect matrix, generation, quirks, sqlfluff, golden execution on real engines | Not started |
| 12 | Sandbox and validation | T-81 to T-88 | isolated execution, static checks, timeout and row limits, diagnostics, shape and cost checks | Not started |
| 13 | Feedback and retry | T-89 to T-93 | failure taxonomy, routing to codegen or confirm, shared retry cap, failure logging | Not started |
| 14 | Integration and deploy | T-94 to T-100 | end-to-end suite, load test, staging, canary rollout, dashboards, alerts, runbook | Not started |

### Dependency spine (critical path)
T-17 intent taxonomy -> T-12 intent schema -> T-18/T-19 NLU -> T-34/T-35 DAG -> T-56/T-57 IR -> T-63/T-64 AST -> T-69/T-70 and T-75/T-76 codegen -> T-81 sandbox -> T-94 end-to-end.

Cross-cutting prerequisites that block many tasks:
- **D-2 golden artifacts** (hand-authored DAG/IR/AST per intent and plant). Needed by T-35, T-40, T-62, T-68.
- **D-1 golden execution results** (frozen reference outputs). Needed by T-74, T-80, T-88, T-94.
- **T-25 labeled query set** (>= 100 queries). Needed by T-18, T-19, T-21, T-26.
- **T-9 plus T-75 database access and dialects.** Needed by T-43, T-60, T-77, T-80, T-81.

### Phase entry and exit
- Enter a phase only when the previous phase's "Done when" checks are green on `main`.
- Exit a phase with its golden or CI gate wired in, an ADR written where the guide calls for one, and `docs/` updated.

---

## 3. Requirements

### Tooling
- Python 3.11+ (repo pins a version in `.python-version`), git, uv, Docker (sandbox and staging).
- Dev tools in CI: ruff, mypy, pytest. Later: hypothesis (property tests T-37, T-47), a mutation tester (T-47), black/ruff format (T-72), sqlglot and sqlfluff (T-76, T-78).

### Accounts and access
- Groq API key (T-5, T-28), hosted-LLM path per T-4 ADR.
- Read-only or replica credentials for the source databases (T-9, T-81). Production write access must never be granted.
- Hosting for dashboards and alerting (T-98, T-99).
- Domain expert time: reviewing few-shot examples (T-23), paraphrase wording (T-27), and the on-call runbook drill (T-100).

### Data and content to produce
- >= 100 hand-labeled NL queries across all intents (T-25).
- >= 10 domain few-shot examples per intent (T-23).
- Golden sets D-1 and D-2 for every (intent x plant).
- Dialect matrix per plant: engine and version (T-75).
- Schema inventory with a known-gaps list (T-9, to be redone on the synthetic plant databases).

---

## 4. Decisions

### Resolved
- **Scope:** build all 100 tasks in the guide. The earlier repo work (T-1 to T-16 and the CSV-based schema work) was experimentation, so it is a starting point, not a constraint. We may rework it where it conflicts with the guide.
- **No real plant data.** MCW, YCW and VGU are built as **synthetic plant databases** that we generate: the same logistics domain, but deliberately different table/column names and SQL engines per plant. That gives T-9, T-60, T-75, T-77, T-80 and T-97 something real to run against.
- **Compute:** the Mac handles everything CPU-bound; Modal (or another hosted GPU) is used only for GPU-heavy work. See section 5.

### Proposed (confirm or change)
| Item | Proposal | Task |
|---|---|---|
| Plant engines | YCW = DuckDB, VGU = SQLite (embedded, no install; start here). MCW = PostgreSQL added later via Homebrew (Docker is not installed on this Mac) | T-75 |
| Python target library | pandas (polars if data gets large) | T-69 |
| NLU approach | Hosted Groq with structured output first. Fine-tune only if the T-25 gates can't be met | T-18 |
| Confirm interface | CLI plus a small HTTP endpoint | T-30 |
| Dashboards and alerts | Grafana and Prometheus in Docker, or a hosted equivalent | T-98, T-99 |
| Golden sets D-1/D-2 | We author them from the synthetic plant data, for 2-3 intents first | all gates |

### Still open
1. **Golden sets (D-1, D-2).** No task-card documents exist, so we author them ourselves from the synthetic plant data.
2. **Groq model and budget.** Confirm the key and rate limits cover the T-25 and T-26 runs (500 queries).
3. **Hosted GPU provider.** Modal is the default here.
4. **Scale.** 100 tasks across 14 phases; phases 3 to 6 carry the most risk. Build a thin end-to-end slice first (one intent, one plant, Python only) to prove the spine, then widen each phase.

---

## 5. Compute plan

Most of the pipeline is plain Python and runs on a Mac. Only a few tasks can use a GPU, and none need one if NLU stays on hosted Groq.

| Work | Task | Where it runs |
|---|---|---|
| Code, unit and golden tests, ruff, mypy | most tasks | Mac / GitHub Actions |
| Property tests and mutation testing | T-37, T-47 | Mac (CPU, slow but fine) |
| Synthetic plant databases, SQL engines | T-9, T-75, T-80, T-81 | Mac with Docker |
| Groq API calls (NLU, confirm) | T-5, T-18 to T-33 | Hosted, no GPU |
| Fine-tuning a small open model (only if chosen in T-18) | T-18, T-21 | **Modal GPU** (e.g. A10G or L4) |
| Self-hosted inference and latency benchmarks (only if self-hosting) | T-26 | **Modal GPU** |
| Load test at 2x peak | T-95 | Modal CPU containers or a cloud box |

Rules for hosted compute:
- Keep Modal code in `infra/modal/`; the main pipeline never imports it, so the project runs without a GPU.
- Credentials (Modal token, Groq key) stay in env vars or Modal secrets, never in git.
- Set budget and timeout limits on every GPU job; start with small models and short runs.
- Check in training configs and metrics, not model weights.

---

## 6. Suggested next steps
1. Confirm the proposed items above.
2. Reset the repo baseline: decide what to keep from the experiment branches, and merge or drop the rest so `main` is clean.
3. Generate the three synthetic plant databases (T-9 redone on real engines).
4. Start Phase 3 with T-17 (taxonomy), since T-12, T-25 and T-35 depend on it.
5. In parallel, author D-2 golden artifacts for two or three intents.
