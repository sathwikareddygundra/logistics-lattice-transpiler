"""AST -> pandas Python (T-70). Output is a `run(conn)` function."""

from __future__ import annotations

import ast

from ast_.nodes import AstDocument, AstOp, AstTarget
from codegen.common import UnsupportedAstError, header_comment, linear_nodes, result_alias

_OPERATORS = {"eq": "==", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_PANDAS_AGG = {"sum": "sum", "count": "count", "avg": "mean", "min": "min", "max": "max"}


def generate_python(doc: AstDocument, query: str) -> str:
    if doc.target is not AstTarget.PYTHON:
        raise UnsupportedAstError(f"expected a python-target AST, got {doc.target.value!r}")

    body: list[str] = []
    prev = ""
    alias = ""
    metric = ""
    for node in linear_nodes(doc):
        p, var = node.params, node.var
        match node.op:
            case AstOp.SELECT:
                cols = ", ".join(c["column"] for c in p["columns"])
                body.append(f'{var} = pd.read_sql_query("SELECT {cols} FROM {p["table"]}", conn)')
            case AstOp.FILTER:
                col = f'{prev}["{p["column"]["column"]}"]'
                body.append(
                    f"{var} = {prev}[{col} {_OPERATORS[p['operator']]} {p['value']['value']!r}]"
                )
            case AstOp.AGGREGATE:
                alias, metric = result_alias(node), p["metric"]["column"]
                fn = _PANDAS_AGG[p["op"]]
                groups = [c["column"] for c in p["group_by"]]
                if groups:
                    body.append(
                        f"{var} = {prev}.groupby({groups!r}, as_index=False)"
                        f'["{metric}"].{fn}().rename(columns={{"{metric}": "{alias}"}})'
                    )
                else:
                    body.append(f'{var} = pd.DataFrame({{"{alias}": [{prev}["{metric}"].{fn}()]}})')
            case AstOp.SORT:
                by = alias if p["by"]["column"] == metric else p["by"]["column"]
                asc = p["direction"] == "asc"
                body.append(f'{var} = {prev}.sort_values("{by}", ascending={asc}, kind="stable")')
            case AstOp.LIMIT:
                body.append(f"{var} = {prev}.head({p['count']})")
            case AstOp.OUTPUT:
                out_cols = [c["column"] if c["column"] != metric else alias for c in p["columns"]]
                body.append(f"{var} = {prev}[{out_cols!r}].reset_index(drop=True)")
            case _:
                raise UnsupportedAstError(f"python codegen does not support op {node.op.value!r}")
        prev = var

    lines = [
        header_comment(query, "#"),
        "import pandas as pd",
        "",
        "",
        "def run(conn):",
        *[f"    {line}" for line in body],
        f"    return {prev}",
        "",
    ]
    code = "\n".join(lines)
    ast.parse(code)  # syntactic validity (T-70)
    return code
