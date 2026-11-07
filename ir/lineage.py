"""Column availability along a document's edges (shared by IR and AST checks)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from graph_eng.toposort import toposort


def available_columns(nodes: Sequence[Any], edges: Sequence[Any]) -> dict[str, set[str]]:
    """Columns each node can see as input (the union of its inputs' outputs)."""
    by_id = {n.id: n for n in nodes}
    incoming: dict[str, list[str]] = {n.id: [] for n in nodes}
    for e in edges:
        incoming[e.to_node].append(e.from_node)
    produced: dict[str, set[str]] = {}
    visible: dict[str, set[str]] = {}
    for nid in toposort([n.id for n in nodes], [(e.from_node, e.to_node) for e in edges]):
        node = by_id[nid]
        seen: set[str] = (
            set().union(*(produced[i] for i in incoming[nid])) if incoming[nid] else set()
        )
        visible[nid] = seen
        p = node.params
        match str(node.op.value):
            case "select":
                produced[nid] = {c["column"] for c in p["columns"]}
            case "window":
                produced[nid] = seen | {f"{p['column']['column']}_{p['granularity']}"}
            case "aggregate":
                produced[nid] = {c["column"] for c in p["group_by"]} | {p["metric"]["column"]}
            case "forecast":
                produced[nid] = seen | {"kind"}
            case "output":
                produced[nid] = {c["column"] for c in p["columns"]}
            case _:
                produced[nid] = seen
    return visible
