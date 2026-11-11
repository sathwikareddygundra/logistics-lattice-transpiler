# T-63: one shared AST grammar, not two

**Decision:** Python and SQL codegen (Phases 10 and 11) share **one**
AST grammar with target-specific adapters downstream, rather than two
separate grammars.

**Why not two grammars:** A `filter` is a `filter` whether it becomes
`df.query(...)` or a SQL `WHERE` clause -- the *operation* and its typed
operands don't change with the target, only the *rendering* does. Two
parallel grammars would mean two parallel sets of node types to keep in
sync every time an operation's shape changes upstream (in T-56's IR),
for no benefit: nothing about "this is a filter on `origin_warehouse`"
is Python- or SQL-specific.

**What the shared grammar actually is:** `ast_/nodes.py`'s `AstDocument`
reuses T-56's IR vocabulary unchanged -- the same `IrOp` values (aliased
here as `AstOp`) and the same typed per-op params classes
(`SelectParams`, `FilterParams`, `JoinParams`, `AggregateParams`, ...).
It adds exactly two things IR doesn't have, because they only matter
once you're about to emit real source code or SQL text:

- **`target`** (`python` | `sql`) -- a document-level field saying which
  of the two codegen passes (T-70, T-76) this AST is for. A document
  never mixes targets.
- **`var`** on every node -- the name that node's result is bound to
  (`df1 = ...` in Python; a CTE/subquery alias in SQL). IR is a plain
  data-flow graph with no notion of sequential, named statements; an AST
  is exactly that sequence, which is the actual "language-shaped" part
  T-63 asked for.

**Where this stops being shared:** T-70 (AST -> Python) and T-76
(AST -> SQL) are where the same `AstDocument` produces genuinely
different output -- a `filter` node renders as `.query("origin_warehouse
== 'MCW'")` for one target and `WHERE origin_warehouse = 'MCW'` for the
other. That divergence belongs entirely in codegen, not in the grammar.

**Every IR operation's mapping to AST, in both targets:** the identity
mapping. Because the grammar is shared, "does this IR op have an AST
representation in target X" is the same question for every X --
`AstOp` **is** `IrOp` (see `ast_/nodes.py`'s import of `IrOp as AstOp`),
so coverage is total and mechanical rather than something to review node
type by node type.

**Scope note:** T-63 only defines the grammar. The actual IR -> AST
lowering pass (T-64), AST-level optimizations (T-66), and the two
codegen passes themselves (T-69-T-80) are separate, later tasks. The
examples backing T-15's schema are hand-authored to exercise the
grammar, the same way T-56/T-14's were for IR and T-34/T-13's were for
the DAG.
