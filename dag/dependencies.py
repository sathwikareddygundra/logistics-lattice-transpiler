"""Dependency inference (T-36): edges come from column lineage, not manual wiring."""

from __future__ import annotations

from dag.model import Edge, EdgeRole, Node, NodeType
from plantdb.catalog import JOIN_KEY, get_table


def window_alias(column: str, granularity: str) -> str:
    return f"{column}_{granularity}"


def consumes(node: Node) -> set[str]:
    p = node.params
    match node.node_type:
        case NodeType.FILTER:
            return {p["column"]}
        case NodeType.JOIN:
            return {p["on"]}
        case NodeType.WINDOW:
            return {p["column"]}
        case NodeType.AGGREGATE:
            return {*p["group_by"], p["metric"]}
        case NodeType.SORT:
            return {p["by"]}
        case NodeType.FORECAST:
            return {p["metric"]}
        case NodeType.OUTPUT:
            return set(p["columns"])
        case _:
            return set()


def produces(node: Node, upstream: set[str]) -> set[str]:
    p = node.params
    match node.node_type:
        case NodeType.SOURCE:
            return set(get_table(p["source"]).columns)
        case NodeType.WINDOW:
            return upstream | {window_alias(p["column"], p["granularity"])}
        case NodeType.AGGREGATE:
            return {*p["group_by"], p["metric"]}
        case NodeType.OUTPUT:
            return set(p["columns"])
        case _:
            return upstream  # filter / join(union handled by caller) / sort / limit / forecast


def infer_edges(nodes: list[Node]) -> list[Edge]:
    """Wire `nodes` (given in logical order) by matching consumed columns to the
    most recent open producer. A join takes the two oldest open producers that
    carry its key; every other node takes the latest open producer that carries
    everything it consumes."""
    cols: dict[str, set[str]] = {}
    open_ends: list[str] = []
    edges: list[Edge] = []
    for node in nodes:
        need = consumes(node)
        if node.node_type is NodeType.SOURCE:
            cols[node.id] = produces(node, set())
            open_ends.append(node.id)
            continue
        if node.node_type is NodeType.JOIN:
            carriers = [n for n in open_ends if need <= cols[n]]
            if len(carriers) < 2:
                raise ValueError(f"join {node.id!r} needs two open inputs carrying {sorted(need)}")
            left, right = carriers[0], carriers[1]
            edges += [
                Edge(from_node=left, to_node=node.id, role=EdgeRole.LEFT),
                Edge(from_node=right, to_node=node.id, role=EdgeRole.RIGHT),
            ]
            open_ends = [node.id if n == left else n for n in open_ends if n != right]
            cols[node.id] = cols[left] | cols[right]
            continue
        candidates = [n for n in open_ends if need <= cols[n]]
        if not candidates:
            raise ValueError(
                f"node {node.id!r} ({node.node_type.value}) consumes {sorted(need)} "
                "but no upstream node produces them"
            )
        src = candidates[-1]
        edges.append(Edge(from_node=src, to_node=node.id))
        open_ends = [n for n in open_ends if n != src] + [node.id]
        cols[node.id] = produces(node, cols[src])
    if len(open_ends) != 1:
        raise ValueError(f"dangling branches after wiring: {open_ends}")
    return edges


__all__ = ["JOIN_KEY", "consumes", "infer_edges", "produces", "window_alias"]
