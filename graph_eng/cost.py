"""Per-node cost estimation (T-43): row counts from the catalog and simple
selectivity rules. Accurate to roughly an order of magnitude, which is enough to
compare plans."""

from __future__ import annotations

from dag.dependencies import produces
from dag.model import Dag, Node, NodeType
from graph_eng.toposort import toposort
from plantdb.catalog import get_table
from plantdb.vocab import column_values, date_span

DEFAULT_RANGE_SELECTIVITY = 0.33


def _distinct(column: str) -> int | None:
    values = column_values().get(column)
    return len(values) if values else None


def filter_selectivity(node: Node) -> float:
    p = node.params
    column, op = p["column"], p["operator"]
    if op == "eq":
        d = _distinct(column)
        return 1.0 / d if d else 0.01
    if op == "ne":
        d = _distinct(column)
        return 1.0 - (1.0 / d) if d else 0.99
    if column.endswith("_date") or column.endswith("_timestamp"):
        return DEFAULT_RANGE_SELECTIVITY  # half of a bounded range is refined in estimate()
    return DEFAULT_RANGE_SELECTIVITY


def estimate_rows(dag: Dag) -> dict[str, int]:
    by_id = {n.id: n for n in dag.nodes}
    incoming: dict[str, list[str]] = {n.id: [] for n in dag.nodes}
    for e in dag.edges:
        incoming[e.to_node].append(e.from_node)
    order = toposort([n.id for n in dag.nodes], [(e.from_node, e.to_node) for e in dag.edges])
    rows: dict[str, int] = {}
    cols: dict[str, set[str]] = {}
    lo, hi = date_span()
    for nid in order:
        node, ins = by_id[nid], incoming[nid]
        upstream = set().union(*(cols[i] for i in ins)) if ins else set()
        cols[nid] = produces(node, upstream)
        match node.node_type:
            case NodeType.SOURCE:
                rows[nid] = get_table(node.params["source"]).row_count
            case NodeType.FILTER:
                sel = filter_selectivity(node)
                if node.params["operator"] in ("gte", "lt", "gt", "lte"):
                    sel = 0.5  # one side of a range; the other side halves it again
                rows[nid] = max(1, int(rows[ins[0]] * sel))
            case NodeType.JOIN:
                rows[nid] = min(rows[i] for i in ins)  # key-to-key, 1:1 in this dataset
            case NodeType.AGGREGATE:
                groups = 1
                for g in node.params["group_by"]:
                    groups *= _distinct(g) or 12
                rows[nid] = max(1, min(rows[ins[0]], groups))
            case NodeType.LIMIT:
                rows[nid] = min(rows[ins[0]], node.params["count"])
            case NodeType.FORECAST:
                rows[nid] = rows[ins[0]] + node.params["horizon"]
            case _:
                rows[nid] = rows[ins[0]] if ins else 0
    _ = (lo, hi)
    return rows
