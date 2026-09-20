# T-63 + T-15 — handoff notes

T-15 explicitly depends on T-63 ("wait until T-63 (target AST
definition) exists"), so both are included here, built in that order --
same pattern as [[T-17 + T-12]](README_T12.md),
[[T-34 + T-13]](README_T34_T13.md), and [[T-56 + T-14]](README_T56_T14.md).

## What's here

```
ast_/
  nodes.py                         # T-63: AstTarget enum, AstOp (= T-56's
                                    #   IrOp, reused unchanged), Node
                                    #   (adds `var`), AstDocument (adds
                                    #   `target`), structural checks
docs/
  T-63-target-ast-adr.md           # ADR: one shared AST grammar with
                                    #   adapters, not two separate ones
schemas/
  ast.schema.json                  # T-15: JSON Schema, draft 2020-12,
                                    #   one schema for both targets
  validate_ast.py                  # validator: JSON Schema layer, then
                                    #   ast_.nodes.AstDocument
  examples/
    valid_ast_python_aggregation.json   # target=python
    valid_ast_sql_aggregation.json      # same shape, target=sql
    valid_ast_sql_join.json             # two selects -> join -> output
    malformed_ast_bad_operator.json     # schema-layer failure
    malformed_ast_duplicate_var.json    # structural-layer failure
tests/
  test_ast_nodes.py                # T-63 acceptance test
  test_ast_schema.py               # T-15 acceptance test
```

## The key decision: one grammar, not two

Full reasoning in `docs/T-63-target-ast-adr.md`. Short version: a
`filter` is a `filter` whether it renders as `df.query(...)` or a SQL
`WHERE` clause -- the operation and its typed operands don't change with
the target, only the rendering does (T-70/T-76's job, not this
grammar's). So `AstDocument` reuses T-56's `IrOp` vocabulary and typed
params **unchanged**, and adds exactly two things IR doesn't have:

- `target` (`python` | `sql`) at the document level -- a document never
  mixes targets.
- `var` on every node -- the name its result is bound to. This is the
  actual "language-shaped" part T-63 asked for: IR is a data-flow graph
  with no notion of sequential, named statements; an AST is exactly that
  sequence.

Because the op vocabulary is literally shared (`AstOp` is `IrOp`, see
`ast_/nodes.py`'s `from ir.grammar import IrOp as AstOp`), "every IR
operation has a defined mapping to AST nodes in both targets" (T-63's
acceptance criterion) is the identity mapping -- proven by
`test_ast_op_vocabulary_matches_ir_exactly` and by
`valid_ast_python_aggregation.json` / `valid_ast_sql_aggregation.json`
being the exact same node/edge shape with only `target` differing.

## Two validation layers, same shape as T-13/T-14

`ast.schema.json` validates per-object shape. Graph-level invariants
(unique node ids, edges resolving to real nodes, acyclicity, join edge
arity) plus one AST doesn't share with IR -- **unique `var` bindings**,
since two statements can't bind the same name -- live in
`ast_.nodes.AstDocument`. `schemas/validate_ast.py` runs both:

```
$ python3 schemas/validate_ast.py schemas/examples/*.json
PASS  schemas/examples/valid_ast_python_aggregation.json
PASS  schemas/examples/valid_ast_sql_aggregation.json
PASS  schemas/examples/valid_ast_sql_join.json
FAIL  schemas/examples/malformed_ast_bad_operator.json      <- schema layer
      - $['nodes'][1]['params']['operator']: 'before' is not one of [...]
FAIL  schemas/examples/malformed_ast_duplicate_var.json     <- structural layer
      - duplicate var binding: 't1'
```
(Full run: `uv run pytest -q` -- 90 tests, all passing; 22 of those are
T-63/T-15's.)

## Drift guard worth knowing about

`test_op_enum_matches_nodes` compares `ast.schema.json`'s `op` enum
against `ast_.nodes.allowed_ast_op_values()`, the same role the drift
guards play in every prior handoff (T-12/T-17, T-13/T-34, T-14/T-56).

## Scope note -- what's deliberately NOT here

T-63's "Done when" only requires the ADR and that every IR operation
maps to an AST node in both targets -- not an actual IR -> AST lowering
pass (T-64, which needs Phase 8's T-57/T-58 to exist first) or golden
ASTs produced by one (T-68, gated behind that same chain). The examples
here are hand-authored, the same way T-56/T-14's and T-34/T-13's were.

## Next task

T-16 (version every schema, write the breaking-change policy) is now
fully unblocked: T-12 through T-15 all exist. That's the natural next
step -- formalizing the `schema_version` field already present on all
four documents (`parsed_intent`, `dag`, `ir`, `ast`) into an actual
policy, rather than continuing to front-load schema contracts for
phases (6-9) that still have no real implementation behind them.
