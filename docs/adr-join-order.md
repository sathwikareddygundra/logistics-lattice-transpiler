# ADR: join order (T-44)

**Decision:** left-deep join trees only; the smallest estimated input is joined first
(`graph_eng/optimize.reorder_joins`, estimates from `graph_eng/cost.py`).

**Why not bushy trees:** the schema is three small tables joined on one key, so a bushy plan
would not change which rows are touched. Left-deep plans are simple to generate, print and
reason about. Revisit if tables with different keys or large size differences are added.

**Safety:** filters are pushed below the join first, so estimates already reflect the reduced
inputs; semantic equivalence is checked by `tests/test_dag_graph.py`.
