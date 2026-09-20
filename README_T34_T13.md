# T-34 + T-13 — handoff notes

T-13 explicitly depends on T-34 ("waits on T-34 (node/edge data model)"),
so both are included here, built in that order — same pattern as
[[T-17 + T-12]](README_T12.md).

## What's here

```
dag/
  model.py                       # T-34: NodeType enum, per-node-type
                                  #   params models, Node/Edge, and Dag
                                  #   with graph-level structural checks
schemas/
  dag.schema.json                 # T-13: JSON Schema, draft 2020-12
  validate_dag.py                 # validator: JSON Schema layer, then
                                  #   dag.model.Dag for graph invariants
  examples/
    valid_dag_aggregation.json    # source -> filter -> aggregate -> output
    valid_dag_join.json           # two sources -> join -> output
    valid_dag_rank.json           # source -> aggregate -> sort -> limit -> output
    malformed_dag_bad_operator.json      # schema-layer failure
    malformed_dag_dangling_edge.json     # structural-layer failure
tests/
  test_dag_model.py               # T-34 acceptance test
  test_dag_schema.py              # T-13 acceptance test
```

## Two validation layers, not one

`dag.schema.json` (T-13) validates per-object shape: field types, enums,
and each `node_type`'s `params` shape via `if`/`then` branches keyed on
`node_type`. It cannot express graph-level invariants — a JSON Schema
instance check has no way to know that an edge's `to_node` refers to a
real node, or that the graph has no cycles.

Those live in `dag.model.Dag` (T-34) instead: unique node ids, edges that
resolve to real nodes, no self-loops, no cycles, `source` nodes with no
incoming edges, exactly one `output` node with no outgoing edges, and
`join` nodes with exactly a `left`- and `right`-roled incoming edge.

`schemas/validate_dag.py` runs both, in order — the JSON Schema pass
first (so a `Dag.model_validate()` failure never has to explain a type
mismatch), and only runs the T-34 structural checks once the shape is
already sound:

```
$ python3 schemas/validate_dag.py schemas/examples/*.json
PASS  schemas/examples/malformed_dag_bad_operator.json      <- would read FAIL
      - $['nodes'][1]['params']['operator']: 'before' is not one of [...]
PASS  schemas/examples/malformed_dag_dangling_edge.json     <- would read FAIL
      - edge references unknown to_node: 'does-not-exist'
PASS  schemas/examples/valid_dag_aggregation.json
PASS  schemas/examples/valid_dag_join.json
PASS  schemas/examples/valid_dag_rank.json
```
(Full run of both test files: `python3 -m unittest discover -s tests -v`
— 36 tests, all passing; 24 of those are T-34/T-13's.)

## Drift guard worth knowing about

`test_node_type_enum_matches_model` compares `dag.schema.json`'s
`node_type` enum against `dag.model.allowed_node_type_values()` and fails
if they diverge — the same role
[[T-17 + T-12]](README_T12.md)'s `test_intent_enum_matches_taxonomy` plays
for `intent_type`. If a new node type is ever added, update
`dag/model.py` first; this test then points at exactly where the schema
is now out of sync.

## Why no offline JSON Schema fallback here

T-12's validator shipped a hand-rolled fallback for a sandbox with no
network access. That's no longer a constraint: `jsonschema` is a real
`pyproject.toml` dependency now, so `schemas/validate_dag.py` uses
`jsonschema.Draft202012Validator` directly — nothing to fall back to,
and nothing to keep in sync with a second, partial implementation.

## Next task

T-35 (parsed intent -> DAG) is the natural next step: it compiles a
`ParsedIntent` (T-12) into a `Dag` (T-34/T-13), one template per
`IntentType` (T-17) as noted in `nlu/taxonomy.py`'s module docstring —
e.g. `rank` -> `source -> aggregate -> sort -> limit -> output`, matching
`schemas/examples/valid_dag_rank.json` here.
