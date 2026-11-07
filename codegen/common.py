from __future__ import annotations

from ast_.nodes import AstDocument, AstOp, Node


class UnsupportedAstError(ValueError):
    """AST shape or op that the current codegen does not handle. Raised
    loudly rather than approximated."""


def linear_nodes(doc: AstDocument) -> list[Node]:
    """Nodes in execution order. Only single-chain ASTs are supported so far."""
    by_id = {n.id: n for n in doc.nodes}
    nxt: dict[str, str] = {}
    for e in doc.edges:
        if e.from_node in nxt:
            raise UnsupportedAstError(f"branching at node {e.from_node!r} is not supported yet")
        nxt[e.from_node] = e.to_node
    start = [n for n in doc.nodes if n.op is AstOp.SELECT]
    if len(start) != 1:
        raise UnsupportedAstError(f"expected exactly one select node, found {len(start)}")
    ordered, cur = [start[0]], start[0].id
    while cur in nxt:
        cur = nxt[cur]
        ordered.append(by_id[cur])
    if len(ordered) != len(doc.nodes):
        raise UnsupportedAstError("AST is not a single linear chain")
    return ordered


def result_alias(node: Node) -> str:
    return f"{node.params['op']}_{node.params['metric']['column']}"


def header_comment(query: str, prefix: str) -> str:
    one_line = " ".join(query.split())
    return f"{prefix} Query: {one_line}"
