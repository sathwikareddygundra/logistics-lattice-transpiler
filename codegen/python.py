"""AST -> pandas Python (T-70). Output defines `run(read_sql)` returning a DataFrame.

Imports are injected only for what the generated code uses (T-71), a header
carries the original query (T-73), each statement is tagged with its AST node,
and the finished text goes through `ruff format` as the last step (T-72).
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys

from ast_.nodes import AstDocument, AstOp, AstTarget
from cag.templates import select_template
from codegen.common import (
    CodegenHints,
    GeneratedCode,
    UnsupportedAstError,
    header_comment,
    ordered_nodes,
)
from plan.forecast import _linear_forecast

OPERATORS = {"eq": "==", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
PANDAS_AGG = {"sum": "sum", "count": "count", "avg": "mean", "min": "min", "max": "max"}
HOW = {"inner": "inner", "left": "left", "right": "right", "outer": "outer"}


class _Frame:
    def __init__(self, var: str, columns: list[str], alias: dict[str, str] | None = None):
        self.var, self.columns, self.alias = var, columns, alias or {}

    def resolve(self, column: str) -> str:
        if column in self.columns:
            return column
        if column in self.alias:
            return self.alias[column]
        raise UnsupportedAstError(f"column {column!r} is not available here: {self.columns}")


def format_python(code: str) -> str:
    out = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--stdin-filename", "generated.py", "-"],
        input=code,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def generate_python(
    doc: AstDocument, query: str, dialect: str = "any", hints: CodegenHints | None = None
) -> GeneratedCode:
    if doc.target is not AstTarget.PYTHON:
        raise UnsupportedAstError(f"expected a python-target AST, got {doc.target.value!r}")

    frames: dict[str, _Frame] = {}
    body: list[str] = []
    provenance: list[tuple[str, str, int]] = []
    incoming: dict[str, list] = {}
    for e in doc.edges:
        incoming.setdefault(e.to_node, []).append(e)
    uses_pd = uses_forecast = False
    last: _Frame | None = None
    out_columns: list[str] = []

    for node in ordered_nodes(doc):
        p, var = node.params, node.var
        prev = frames[incoming[node.id][0].from_node] if node.id in incoming else None
        match node.op:
            case AstOp.SELECT:
                tpl = select_template("select", "python")
                cols = [c["column"] for c in p["columns"]]
                line = tpl.render(var=var, columns=", ".join(cols), table=p["table"])
                frames[node.id] = _Frame(var, cols)
            case AstOp.FILTER:
                assert prev is not None
                tpl = select_template("filter", "python")
                line = tpl.render(
                    var=var,
                    prev=prev.var,
                    column=repr(p["column"]["column"]),
                    operator=OPERATORS[p["operator"]],
                    value=repr(p["value"]["value"]),
                )
                frames[node.id] = _Frame(var, prev.columns, prev.alias)
            case AstOp.JOIN:
                tpl = select_template("join", "python")
                roles = {e.role.value: frames[e.from_node] for e in incoming[node.id]}
                left, right = roles["left"], roles["right"]
                key = p["left_key"]["column"]
                extra = [c for c in right.columns if c not in left.columns]
                line = tpl.render(
                    var=var,
                    left=left.var,
                    right=right.var,
                    right_cols=repr([key, *extra]),
                    key=repr(key),
                    how=repr(HOW[p["how"]]),
                )
                frames[node.id] = _Frame(var, [*left.columns, *extra])
            case AstOp.WINDOW:
                assert prev is not None
                uses_pd = True
                gran = p["granularity"]
                alias = f"{p['column']['column']}_{gran}"
                btpl = select_template("bucket", "python", granularity=gran)
                tpl = select_template("window", "python")
                provenance.append((node.id, btpl.id, btpl.version))
                line = tpl.render(
                    var=var,
                    prev=prev.var,
                    alias=alias,
                    bucket=btpl.render(prev=prev.var, col=repr(p["column"]["column"])),
                )
                frames[node.id] = _Frame(var, [*prev.columns, alias], prev.alias)
            case AstOp.AGGREGATE:
                assert prev is not None
                metric = p["metric"]["column"]
                alias = f"{p['op']}_{metric}"
                groups = [c["column"] for c in p["group_by"]]
                fn = PANDAS_AGG[p["op"]]
                if groups:
                    tpl = select_template("aggregate", "python")
                    line = tpl.render(
                        var=var,
                        prev=prev.var,
                        group=repr(groups),
                        metric=repr(metric),
                        fn=fn,
                        alias=repr(alias),
                    )
                else:
                    uses_pd = True
                    tpl = select_template("aggregate_scalar", "python")
                    line = tpl.render(
                        var=var, prev=prev.var, metric=repr(metric), fn=fn, alias=repr(alias)
                    )
                frames[node.id] = _Frame(var, [*groups, alias], {metric: alias})
            case AstOp.SORT:
                assert prev is not None
                tpl = select_template("sort", "python")
                by = prev.resolve(p["by"]["column"])
                line = tpl.render(
                    var=var, prev=prev.var, by=repr([by]), asc=repr(p["direction"] == "asc")
                )
                frames[node.id] = _Frame(var, prev.columns, prev.alias)
            case AstOp.LIMIT:
                assert prev is not None
                tpl = select_template("limit", "python")
                line = tpl.render(var=var, prev=prev.var, count=p["count"])
                frames[node.id] = _Frame(var, prev.columns, prev.alias)
            case AstOp.FORECAST:
                assert prev is not None
                uses_pd = uses_forecast = True
                if p["method"] != "linear":
                    raise UnsupportedAstError(f"forecast method {p['method']!r} is not supported")
                tpl = select_template("forecast", "python")
                value = prev.resolve(p["metric"]["column"])
                period = prev.columns[0]
                line = tpl.render(
                    var=var,
                    prev=prev.var,
                    period=repr(period),
                    value=repr(value),
                    horizon=p["horizon"],
                )
                frames[node.id] = _Frame(var, [period, value, "kind"], prev.alias)
            case AstOp.OUTPUT:
                assert prev is not None
                tpl = select_template("output", "python")
                cols = [prev.resolve(c["column"]) for c in p["columns"]]
                if "kind" in prev.columns:
                    cols.append("kind")
                line = tpl.render(var=var, prev=prev.var, columns=repr(cols))
                frames[node.id] = _Frame(var, cols)
                out_columns = cols
                last = frames[node.id]
            case _:
                raise UnsupportedAstError(
                    f"python codegen does not support op {node.op.value!r} (node {node.id!r})"
                )
        body.append(f"    # {node.id} {node.op.value}")
        body.append(f"    {line}")
        provenance.append((node.id, tpl.id, tpl.version))

    if last is None:
        raise UnsupportedAstError("AST has no output node")
    lines = [header_comment(query, "#")]
    if uses_pd:
        lines.append("import pandas as pd")
    if uses_forecast:
        lines += ["", inspect.getsource(_linear_forecast).rstrip()]
    lines += ["", "", "def run(read_sql):", *body, f"    return {last.var}", ""]
    code = format_python("\n".join(lines))
    ast.parse(code)
    return GeneratedCode(
        text=code, target="python", dialect=dialect, provenance=provenance, columns=out_columns
    )
