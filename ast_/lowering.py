"""IR -> AST (T-64): identity op/params mapping plus a bound variable name."""

from __future__ import annotations

from ast_.nodes import AstDocument, AstTarget, Node
from ir.grammar import Ir


def ir_to_ast(ir: Ir, target: AstTarget) -> AstDocument:
    nodes = [
        Node(id=n.id, op=n.op, var=f"df{i}", params=n.params)
        for i, n in enumerate(ir.nodes, start=1)
    ]
    return AstDocument(
        trace_id=ir.trace_id,
        target=target,
        nodes=nodes,
        edges=[e.model_copy() for e in ir.edges],
    )
