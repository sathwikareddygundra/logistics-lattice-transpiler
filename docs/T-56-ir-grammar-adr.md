# T-56: why IR exists as its own layer

**Decision:** IR is a distinct, typed layer between the DAG (Phase 5) and
the AST (Phase 9), not a thin renaming of either.

**Why a third layer, not two:**

- The **DAG** (T-34) is *task-shaped*. Its nodes say "run a filter here"
  with an opaque `params` dict — enough to describe a plan, not enough to
  catch a type error.
- The **AST** (T-63, later) will be *language-shaped*. Its nodes will say
  "this is a pandas `.query()` call" or "this is a SQL `WHERE` clause" —
  specific to one target, not comparable across targets.
- **IR** is where *language-agnostic typed reasoning* happens. Every
  operand (`ColumnRef`, `Literal`) carries an explicit `IrType`
  (integer, float, string, boolean, date, datetime), so questions like
  "are these join keys compatible?" or "what type does `sum()` produce?"
  are answered once, here, before either target's codegen has to worry
  about them.

Concretely, `ir/grammar.py` bakes in the checks this buys:
- `JoinParams` rejects a join between mismatched key types.
- `AggregateParams` requires the declared `result_type` to match what the
  aggregate op actually produces (`count` → integer, `sum`/`avg` → float,
  `min`/`max` → the metric's own type).
- `WindowParams` requires its column to actually be a date/datetime type.

None of this is full type-checking (that's T-58's job, once it exists —
this only checks the operands *within* one node, not expression chains
across a whole document). But it's why IR can't just be "the DAG with
different field names": the DAG has no notion of column types at all.

**Every DAG (T-34) node type has a corresponding `IrOp`:**

| DAG node type | IR op       |
|----------------|-------------|
| source         | `select`    |
| filter         | `filter`    |
| join           | `join`      |
| aggregate      | `aggregate` |
| window         | `window`    |
| sort           | `sort`      |
| limit          | `limit`     |
| forecast       | `forecast`  |
| output         | `output`    |

**Scope note:** T-56 defines the grammar only. The actual DAG+CAG → IR
lowering pass (T-57) and IR type-checker (T-58) are separate, later
tasks — `ir/grammar.py`'s examples in `schemas/examples/` are
hand-authored to exercise the grammar, not produced by a lowering pass
that doesn't exist yet.
