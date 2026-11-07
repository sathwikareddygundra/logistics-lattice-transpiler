"""Stable, readable AST rendering (T-67)."""

from __future__ import annotations

from ast_.nodes import AstDocument
from ir.pretty import _params


def render_ast(doc: AstDocument) -> str:
    inputs: dict[str, list[str]] = {}
    for e in doc.edges:
        tag = e.from_node + (f"[{e.role.value}]" if e.role else "")
        inputs.setdefault(e.to_node, []).append(tag)
    lines = [f"ast v{doc.schema_version} target={doc.target.value}"]
    for n in doc.nodes:
        src = f"  <- {', '.join(sorted(inputs[n.id]))}" if n.id in inputs else ""
        lines.append(f"{n.var} = {n.op.value}: {_params(n.op.value, n.params)}{src}")
    return "\n".join(lines) + "\n"
