# T-56 + T-14 — handoff notes

T-14 explicitly depends on T-56 ("wait until T-56 (IR grammar) exists"),
so both are included here, built in that order -- same pattern as
[[T-17 + T-12]](README_T12.md) and [[T-34 + T-13]](README_T34_T13.md).

## What's here

```
ir/
  grammar.py                      # T-56: IrOp enum, typed ColumnRef/
                                   #   Literal operands, per-op params
                                   #   models, Node/Edge, and Ir with
                                   #   graph-level + typed structural
                                   #   checks
docs/
  T-56-ir-grammar-adr.md          # ADR: why IR is its own layer,
                                   #   distinct from the DAG and the AST
schemas/
  ir.schema.json                  # T-14: JSON Schema, draft 2020-12
  validate_ir.py                  # validator: JSON Schema layer, then
                                   #   ir.grammar.Ir for structural +
                                   #   typed checks
  examples/
    valid_ir_aggregation.json     # select -> filter -> aggregate -> output
    valid_ir_join.json            # two selects -> join -> output
    valid_ir_rank.json            # select -> aggregate -> sort -> limit -> output
    malformed_ir_bad_operator.json       # schema-layer failure
    malformed_ir_dangling_edge.json      # structural-layer failure
    malformed_ir_unsupported_op.json     # invented op, rejected by the enum
tests/
  test_ir_grammar.py              # T-56 acceptance test
  test_ir_schema.py               # T-14 acceptance test
```

## Why IR needed a third layer (short version)

See `docs/T-56-ir-grammar-adr.md` for the full reasoning. In short: the
DAG (T-34) is task-shaped (opaque `params`), the AST (T-63, not yet
built) will be language-shaped. IR is where every operand carries an
explicit `IrType`, so type mismatches are caught in the grammar itself:

- `JoinParams` rejects a join between mismatched key types.
- `AggregateParams` requires `result_type` to match what the op actually
  produces (`count` -> integer, `sum`/`avg` -> float, `min`/`max` -> the
  metric's own type).
- `WindowParams` requires its column to be date/datetime.
- `FilterParams` requires the literal's type to match the column's type.

This is deliberately narrower than T-58 (general IR type-checking across
a whole document) -- these are per-node invariants, the same scope T-34's
`Node` validator had for the DAG, one level up in richness.

## Two validation layers, same shape as T-13

`ir.schema.json` validates per-object shape (field types, enums, each
`op`'s `params` shape via `if`/`then`). Graph-level invariants (unique
node ids, edges resolving to real nodes, acyclicity, join edge arity)
and the typed checks above live in `ir.grammar.Ir` instead.
`schemas/validate_ir.py` runs both, JSON Schema first:

```
$ python3 schemas/validate_ir.py schemas/examples/*.json
PASS  schemas/examples/valid_ir_aggregation.json
PASS  schemas/examples/valid_ir_join.json
PASS  schemas/examples/valid_ir_rank.json
FAIL  schemas/examples/malformed_ir_bad_operator.json      <- schema layer
      - $['nodes'][1]['params']['operator']: 'before' is not one of [...]
FAIL  schemas/examples/malformed_ir_dangling_edge.json     <- structural layer
      - edge references unknown to_node: 'does-not-exist'
FAIL  schemas/examples/malformed_ir_unsupported_op.json    <- T-14's own criterion
      - $['nodes'][1]['op']: 'transform' is not one of [...]
```
(Full run: `uv run pytest -q` -- 68 tests, all passing; 23 of those are
T-56/T-14's.)

## Drift guard worth knowing about

`test_op_enum_matches_grammar` compares `ir.schema.json`'s `op` enum
against `ir.grammar.allowed_ir_op_values()`, the same role
`test_node_type_enum_matches_model` plays for T-13/T-34 and
`test_intent_enum_matches_taxonomy` plays for T-12/T-17.

## Scope note -- what's deliberately NOT here

T-56's "Done when" only requires that every DAG (T-34) node type has a
corresponding IR representation and that the ADR is written -- it does
not require an actual DAG+CAG -> IR lowering pass (that's T-57) or golden
IR documents produced by one (that's T-62, gated behind Phase 6/7 work
that doesn't exist yet: T-41-T-55). The examples here are hand-authored
to exercise the grammar and schema, the same way T-13's examples were
hand-authored rather than waiting on T-35's compiler or T-38's
serializer.

## Next task

T-15 (JSON Schema for AST nodes) has the same shape of dependency: it
explicitly waits on T-63 (target AST definition), which itself waits on
T-56 existing (done here) but is otherwise Phase 9 -- several phases of
real pipeline work away. As with T-13's handoff, the natural next step
is either T-16 (versioning/breaking-change policy, now covering
T-12-T-15 once T-15 exists) or moving into the actual pipeline-stage work
(Phase 3 NLU onward) rather than continuing to front-load schema
contracts for phases that don't have implementations yet.
