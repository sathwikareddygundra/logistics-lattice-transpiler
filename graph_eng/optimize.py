"""DAG optimization passes (T-41, T-44, T-45). Every pass is idempotent and
semantics-preserving (checked by tests/test_graph_equivalence.py).

Join strategy (T-44 decision): left-deep trees only. They are simple to generate
and to read, and with three small tables a bushy tree would not change the plan.
The smallest estimated input is joined first.
"""

from __future__ import annotations

from dag.dependencies import produces
from dag.model import Dag, Edge, EdgeRole, Node, NodeType
from graph_eng.cost import estimate_rows
from graph_eng.toposort import toposort
from plantdb.catalog import JOIN_KEY


def _rebuild(dag: Dag, nodes: list[Node], edges: list[Edge]) -> Dag:
    return Dag(trace_id=dag.trace_id, nodes=nodes, edges=edges)


def prune_dead(dag: Dag) -> Dag:
    """Drop every node that cannot reach the output."""
    out = next(n.id for n in dag.nodes if n.node_type is NodeType.OUTPUT)
    parents: dict[str, list[str]] = {}
    for e in dag.edges:
        parents.setdefault(e.to_node, []).append(e.from_node)
    keep, stack = set(), [out]
    while stack:
        cur = stack.pop()
        if cur not in keep:
            keep.add(cur)
            stack.extend(parents.get(cur, []))
    return _rebuild(
        dag,
        [n for n in dag.nodes if n.id in keep],
        [e for e in dag.edges if e.from_node in keep and e.to_node in keep],
    )


def merge_identical_sources(dag: Dag) -> Dag:
    """Fetch each table once: sources with identical params collapse into the first."""
    first: dict[str, str] = {}
    redirect: dict[str, str] = {}
    for n in dag.nodes:
        if n.node_type is NodeType.SOURCE:
            key = str(sorted(n.params.items()))
            if key in first:
                redirect[n.id] = first[key]
            else:
                first[key] = n.id
    if not redirect:
        return dag
    edges = []
    for e in dag.edges:
        edges.append(
            Edge(from_node=redirect.get(e.from_node, e.from_node), to_node=e.to_node, role=e.role)
        )
    return _rebuild(dag, [n for n in dag.nodes if n.id not in redirect], edges)


def _columns(dag: Dag) -> dict[str, set[str]]:
    by_id = {n.id: n for n in dag.nodes}
    ins: dict[str, list[str]] = {n.id: [] for n in dag.nodes}
    for e in dag.edges:
        ins[e.to_node].append(e.from_node)
    cols: dict[str, set[str]] = {}
    for nid in toposort([n.id for n in dag.nodes], [(e.from_node, e.to_node) for e in dag.edges]):
        upstream = set().union(*(cols[i] for i in ins[nid])) if ins[nid] else set()
        cols[nid] = produces(by_id[nid], upstream)
    return cols


def push_down_filters(dag: Dag) -> Dag:
    """Move each filter below the join onto the single side that carries its column."""
    nodes = list(dag.nodes)
    edges = list(dag.edges)
    while True:
        cur = _rebuild(dag, nodes, edges)
        by_id = {n.id: n for n in cur.nodes}
        cols = _columns(cur)
        moved = False
        for f in [n for n in cur.nodes if n.node_type is NodeType.FILTER]:
            col = f.params["column"]
            parent_edge = next(e for e in edges if e.to_node == f.id)
            parent = by_id[parent_edge.from_node]
            if parent.node_type is not NodeType.JOIN or col == JOIN_KEY:
                continue
            sides = [e for e in edges if e.to_node == parent.id and col in cols[e.from_node]]
            if len(sides) != 1:
                continue
            side = sides[0]
            new_edges = []
            for e in edges:
                if e is parent_edge:
                    continue
                if e is side:
                    new_edges.append(Edge(from_node=side.from_node, to_node=f.id))
                    new_edges.append(Edge(from_node=f.id, to_node=parent.id, role=side.role))
                elif e.from_node == f.id:
                    new_edges.append(Edge(from_node=parent.id, to_node=e.to_node, role=e.role))
                else:
                    new_edges.append(e)
            edges = new_edges
            moved = True
            break
        if not moved:
            return _rebuild(dag, nodes, edges)


def reorder_joins(dag: Dag) -> Dag:
    """Rebuild the left-deep join chain with the smallest estimated inputs first."""
    joins = [n for n in dag.nodes if n.node_type is NodeType.JOIN]
    if not joins:
        return dag
    rows = estimate_rows(dag)
    join_ids = {j.id for j in joins}
    leaves = sorted(
        {e.from_node for e in dag.edges if e.to_node in join_ids and e.from_node not in join_ids},
        key=lambda i: (rows[i], i),
    )
    order = [
        i
        for i in toposort([n.id for n in dag.nodes], [(e.from_node, e.to_node) for e in dag.edges])
        if i in join_ids
    ]
    new_join_edges: list[Edge] = []
    left = leaves[0]
    for jid, right in zip(order, leaves[1:], strict=True):
        new_join_edges += [
            Edge(from_node=left, to_node=jid, role=EdgeRole.LEFT),
            Edge(from_node=right, to_node=jid, role=EdgeRole.RIGHT),
        ]
        left = jid
    kept = [e for e in dag.edges if e.to_node not in join_ids]
    return _rebuild(dag, list(dag.nodes), kept + new_join_edges)


def optimize(dag: Dag) -> Dag:
    return prune_dead(reorder_joins(push_down_filters(merge_identical_sources(dag))))
