"""AST well-formedness beyond the structural model checks (T-65): required children,
no dangling column references, no orphaned subtrees. Each violation is named."""

from __future__ import annotations

from ast_.nodes import AstDocument, AstOp
from ir.lineage import available_columns


class AstValidationError(ValueError):
    def __init__(self, violations: list[str]) -> None:
        super().__init__("; ".join(violations))
        self.violations = violations


def ast_violations(doc: AstDocument) -> list[str]:
    out: list[str] = []
    incoming: dict[str, list] = {n.id: [] for n in doc.nodes}
    outgoing: dict[str, list] = {n.id: [] for n in doc.nodes}
    for e in doc.edges:
        incoming[e.to_node].append(e)
        outgoing[e.from_node].append(e)

    for n in doc.nodes:
        if n.op is AstOp.JOIN and len(incoming[n.id]) != 2:
            out.append(f"{n.var}: join needs exactly two inputs, has {len(incoming[n.id])}")
        if n.op not in (AstOp.SELECT, AstOp.JOIN) and len(incoming[n.id]) != 1:
            out.append(f"{n.var}: {n.op.value} needs exactly one input, has {len(incoming[n.id])}")
        if n.op is not AstOp.OUTPUT and not outgoing[n.id]:
            out.append(f"{n.var}: orphaned subtree, nothing consumes its result")

    output = next((n for n in doc.nodes if n.op is AstOp.OUTPUT), None)
    if output is not None:
        reach, stack = set(), [output.id]
        parents = {n.id: [e.from_node for e in incoming[n.id]] for n in doc.nodes}
        while stack:
            cur = stack.pop()
            if cur not in reach:
                reach.add(cur)
                stack.extend(parents[cur])
        out += [f"{n.var}: does not feed the output" for n in doc.nodes if n.id not in reach]

    if not out:
        visible = available_columns(doc.nodes, doc.edges)
        for n in doc.nodes:
            p = n.params
            refs: list[dict] = []
            if n.op is AstOp.FILTER:
                refs = [p["column"]]
            elif n.op is AstOp.AGGREGATE:
                refs = [p["metric"], *p["group_by"]]
            elif n.op in (AstOp.SORT,):
                refs = [p["by"]]
            elif n.op is AstOp.WINDOW:
                refs = [p["column"]]
            elif n.op is AstOp.OUTPUT:
                refs = list(p["columns"])
            out += [
                f"{n.var}: references {c['table']}.{c['column']}, which is not available upstream"
                for c in refs
                if c["column"] not in visible[n.id]
            ]
    return out


def validate_ast(doc: AstDocument) -> None:
    violations = ast_violations(doc)
    if violations:
        raise AstValidationError(violations)
