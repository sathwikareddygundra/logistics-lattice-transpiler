# Project Index

Logistics Lattice Transpiler — an NL-to-SQL/Python transpiler pipeline for logistics data (MCW, YCW, VGU plants).

Pipeline: `schema -> NLU -> confirm -> DAG -> graph_eng -> CAG -> IR -> AST -> codegen -> sandbox`

Branch: `feature/T-16-schema-versioning-policy`. Python (see `.python-version`), managed with `uv` (`pyproject.toml`, `uv.lock`). Deps: httpx, jsonschema, pydantic-settings, structlog.

## Implemented stages

| Path | Ticket | What it holds |
|---|---|---|
| [schemas/canonical.py](schemas/canonical.py) | T-10 | Typed domain models: `Shipment`, `TrackingEvent`, `TurnaroundRecord`, enums (`Warehouse`, `Carrier`, `ShipmentStatus`, `SlaStatus`) |
| [schemas/loaders.py](schemas/loaders.py) | T-10 | CSV loaders producing validated canonical models |
| [schemas/registry.py](schemas/registry.py) | T-11 | `SchemaRegistry`: resolves (source, version) to a canonical model, cached |
| [dag/model.py](dag/model.py) | T-34 | DAG `Node`/`Edge`/`Dag` models, node types, structural invariants (no cycles, valid edges) |
| [ir/grammar.py](ir/grammar.py) | T-56 | Typed, language-agnostic IR: `IrOp`, `IrType`, per-op params, `Ir` document |
| [ast_/nodes.py](ast_/nodes.py) | T-63 | Target AST: reuses IR ops, adds `target` (python/sql) and `var` |
| [common/groq_client.py](common/groq_client.py) | T-5 | `GroqClient` with retry, backoff, 3s timeout |
| [config.py](config.py) | | `Settings` (pydantic-settings), `Environment` dev/staging/prod |
| [logging_config.py](logging_config.py) | | structlog setup |

## JSON schemas (wire contracts) — `schemas/`

- [dag.schema.json](schemas/dag.schema.json) (T-13), [ir.schema.json](schemas/ir.schema.json) (T-14), [ast.schema.json](schemas/ast.schema.json) (T-15)
- Validators: [validate_dag.py](schemas/validate_dag.py), [validate_ir.py](schemas/validate_ir.py), [validate_ast.py](schemas/validate_ast.py)
- Source schema docs: [dispatch.json](schemas/dispatch.json), [tracking.json](schemas/tracking.json), [turnaround_time.json](schemas/turnaround_time.json); overview in [schemas/README.md](schemas/README.md) (T-9)
- `schemas/examples/`: `valid_*` and `malformed_*` fixtures for dag, ir, ast

## Placeholder packages (only `__init__.py`)

`nlu/`, `confirm/`, `graph_eng/`, `cag/`, `codegen/`, `sandbox/` — future pipeline stages.

## Docs

- [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md)
- Per-ticket READMEs: [T-34/T-13](README_T34_T13.md), [T-56/T-14](README_T56_T14.md), [T-63/T-15](README_T63_T15.md)
- ADRs / decisions in `docs/`: [T-4 compute decision](docs/T-4-compute-decision.md), [T-56 IR grammar](docs/T-56-ir-grammar-adr.md), [T-63 target AST](docs/T-63-target-ast-adr.md), [T-16 schema versioning policy](docs/T-16-schema-versioning-policy.md)

## Tests — `tests/`

`test_ast_nodes`, `test_ast_schema`, `test_canonical_schema`, `test_dag_model`, `test_dag_schema`, `test_groq_client`, `test_ir_grammar`, `test_ir_schema`, `test_schema_registry`, `test_schema_versions`, `test_smoke`. CSV fixtures in `tests/fixtures/` (dispatch, tracking, turnaround_time).

## Config and tooling

- Env: `.env.example` (template), `.env`, `.env.dev`, `.env.staging`, `.env.prod` (local; all but `.env.example` are gitignored)
- CI: [.github/workflows/ci.yml](.github/workflows/ci.yml)
- Ignored/generated: `.venv/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`

## Notes

- Several `__pycache__/*.pyc` files are tracked in git; consider removing them from version control.
