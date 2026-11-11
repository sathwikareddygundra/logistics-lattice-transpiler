"""AST-level optimization passes (T-66). Each is idempotent and result-preserving:
duplicate/dominated filter removal (constant folding on predicates), collapsing of
stacked sorts and limits, and dead-branch pruning."""

from __future__ import annotations

from ast_.nodes import AstDocument, AstOp, Node
from ir.grammar import Edge

_LOWER = ("gt", "gte")
_UPPER = ("lt", "lte")


def _rebuild(doc: AstDocument, nodes: list[Node], edges: list[Edge]) -> AstDocument:
    return AstDocument(trace_id=doc.trace_id, target=doc.target, nodes=nodes, edges=edges)


def _drop(doc: AstDocument, node_ids: set[str]) -> AstDocument:
    """Remove single-input nodes, reconnecting their input to their consumers."""
    edges = list(doc.edges)
    for nid in node_ids:
        into = next(e for e in edges if e.to_node == nid)
        edges = [
            Edge(from_node=into.from_node, to_node=e.to_node, role=e.role)
            if e.from_node == nid
            else e
            for e in edges
            if e is not into
        ]
    return _rebuild(doc, [n for n in doc.nodes if n.id not in node_ids], edges)


def fold_filters(doc: AstDocument) -> AstDocument:
    """Drop filters that an earlier/later filter on the same column already implies."""
    filters = [n for n in doc.nodes if n.op is AstOp.FILTER]
    drop: set[str] = set()
    seen: dict[tuple, str] = {}
    for n in filters:
        p = n.params
        key = (p["column"]["column"], p["operator"], str(p["value"]["value"]))
        if key in seen:
            drop.add(n.id)  # exact duplicate
        else:
            seen[key] = n.id
    for family, pick in ((_LOWER, max), (_UPPER, min)):
        by_col: dict[tuple[str, str], list[Node]] = {}
        for n in filters:
            if n.id not in drop and n.params["operator"] in family:
                by_col.setdefault((n.params["column"]["column"], n.params["operator"]), []).append(
                    n
                )
        for group in by_col.values():
            if len(group) > 1:
                keep = pick(group, key=lambda n: str(n.params["value"]["value"]))
                drop |= {n.id for n in group if n.id != keep.id}
    return _drop(doc, drop) if drop else doc


def collapse_sorts_and_limits(doc: AstDocument) -> AstDocument:
    """Back-to-back limits keep the smaller count; back-to-back sorts keep the last one."""
    by_id = {n.id: n for n in doc.nodes}
    into = {e.to_node: e.from_node for e in doc.edges if e.role is None}
    drop: set[str] = set()
    for n in doc.nodes:
        up = by_id.get(into.get(n.id, ""))
        if up is None or up.id in drop:
            continue
        if n.op is AstOp.LIMIT and up.op is AstOp.LIMIT:
            if up.params["count"] <= n.params["count"]:
                drop.add(n.id)
            else:
                drop.add(up.id)
        elif n.op is AstOp.SORT and up.op is AstOp.SORT:
            drop.add(up.id)
    return _drop(doc, drop) if drop else doc


def prune_dead_branches(doc: AstDocument) -> AstDocument:
    out = next(n for n in doc.nodes if n.op is AstOp.OUTPUT)
    parents: dict[str, list[str]] = {}
    for e in doc.edges:
        parents.setdefault(e.to_node, []).append(e.from_node)
    keep, stack = set(), [out.id]
    while stack:
        cur = stack.pop()
        if cur not in keep:
            keep.add(cur)
            stack.extend(parents.get(cur, []))
    if len(keep) == len(doc.nodes):
        return doc
    return _rebuild(
        doc,
        [n for n in doc.nodes if n.id in keep],
        [e for e in doc.edges if e.from_node in keep and e.to_node in keep],
    )


def optimize_ast(doc: AstDocument) -> AstDocument:
    return prune_dead_branches(collapse_sorts_and_limits(fold_filters(doc)))
