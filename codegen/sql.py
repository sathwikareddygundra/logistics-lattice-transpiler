"""AST -> SQL (T-76): one CTE per relational node, formatted with sqlglot.

Sort and limit fold into the final SELECT (a CTE's row order is not
guaranteed to survive). Dialect-specific pieces (time buckets, identifier
quoting) come from the versioned template library.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.tokens import Tokenizer

from ast_.nodes import AstDocument, AstOp, AstTarget
from cag.templates import select_template
from codegen.common import (
    CodegenHints,
    GeneratedCode,
    UnsupportedAstError,
    header_comment,
    ordered_nodes,
)

OPERATORS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
JOIN_KEYWORDS = {"inner": "INNER", "left": "LEFT", "right": "RIGHT", "outer": "FULL OUTER"}
_RESERVED = {k for k in Tokenizer.KEYWORDS if k.isalpha()}


def quote(name: str, hints: CodegenHints) -> str:
    if hints.quote_all_identifiers or name.upper() in _RESERVED:
        return '"' + name.replace('"', '""') + '"'
    return name


def literal(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


class _State:
    def __init__(self, var: str, columns: list[str], metric_alias: dict[str, str] | None = None):
        self.var = var
        self.columns = columns
        self.metric_alias = metric_alias or {}
        self.sort: list[tuple[str, str]] = []
        self.limit: int | None = None

    def resolve(self, column: str) -> str:
        if column in self.columns:
            return column
        if column in self.metric_alias:
            return self.metric_alias[column]
        raise UnsupportedAstError(f"column {column!r} is not available here: {self.columns}")

    def inherit(self, var: str, columns: list[str]) -> _State:
        new = _State(var, columns, self.metric_alias)
        new.sort, new.limit = self.sort, self.limit
        return new


def generate_sql(
    doc: AstDocument, query: str, dialect: str = "sqlite", hints: CodegenHints | None = None
) -> GeneratedCode:
    hints = hints or CodegenHints()
    if doc.target is not AstTarget.SQL:
        raise UnsupportedAstError(f"expected a sql-target AST, got {doc.target.value!r}")

    q = lambda name: quote(name, hints)  # noqa: E731
    states: dict[str, _State] = {}
    ctes: list[str] = []
    provenance: list[tuple[str, str, int]] = []
    incoming: dict[str, list] = {}
    for e in doc.edges:
        incoming.setdefault(e.to_node, []).append(e)

    def note(node_id: str, tpl_id: str, version: int) -> None:
        provenance.append((node_id, tpl_id, version))

    final: _State | None = None
    out_columns: list[str] = []
    final_sql = ""
    for node in ordered_nodes(doc):
        p, var = node.params, node.var
        prev = states[incoming[node.id][0].from_node] if node.id in incoming else None
        match node.op:
            case AstOp.SELECT:
                tpl = select_template("select", "sql")
                cols = [c["column"] for c in p["columns"]]
                body = tpl.render(columns=", ".join(q(c) for c in cols), table=q(p["table"]))
                states[node.id] = _State(var, cols)
            case AstOp.FILTER:
                assert prev is not None
                tpl = select_template("filter", "sql")
                body = tpl.render(
                    prev=prev.var,
                    column=q(p["column"]["column"]),
                    operator=OPERATORS[p["operator"]],
                    value=literal(p["value"]["value"]),
                )
                states[node.id] = prev.inherit(var, prev.columns)
            case AstOp.JOIN:
                tpl = select_template("join", "sql")
                roles = {e.role.value: states[e.from_node] for e in incoming[node.id]}
                left, right = roles["left"], roles["right"]
                key = p["left_key"]["column"]
                extra = [c for c in right.columns if c not in left.columns]
                select_list = ", ".join(["l.*", *(f"r.{q(c)}" for c in extra)])
                body = tpl.render(
                    select_list=select_list,
                    left=left.var,
                    right=right.var,
                    join_kw=JOIN_KEYWORDS[p["how"]],
                    key=q(key),
                )
                states[node.id] = _State(var, [*left.columns, *extra])
            case AstOp.WINDOW:
                assert prev is not None
                gran = p["granularity"]
                alias = f"{p['column']['column']}_{gran}"
                bucket_tpl = select_template("bucket", "sql", dialect, gran)
                tpl = select_template("window", "sql")
                note(node.id, bucket_tpl.id, bucket_tpl.version)
                body = tpl.render(
                    bucket=bucket_tpl.render(col=q(p["column"]["column"])),
                    alias=q(alias),
                    prev=prev.var,
                )
                states[node.id] = prev.inherit(var, [*prev.columns, alias])
            case AstOp.AGGREGATE:
                assert prev is not None
                tpl = select_template("aggregate", "sql")
                metric = p["metric"]["column"]
                alias = f"{p['op']}_{metric}"
                groups = [c["column"] for c in p["group_by"]]
                select_list = ", ".join(
                    [*(q(g) for g in groups), f"{p['op'].upper()}({q(metric)}) AS {q(alias)}"]
                )
                group_by = f" GROUP BY {', '.join(q(g) for g in groups)}" if groups else ""
                body = tpl.render(select_list=select_list, prev=prev.var, group_by=group_by)
                states[node.id] = _State(var, [*groups, alias], {metric: alias})
            case AstOp.SORT:
                assert prev is not None
                st = prev.inherit(prev.var, prev.columns)
                st.sort = [*st.sort, (st.resolve(p["by"]["column"]), p["direction"].upper())]
                states[node.id] = st
                continue
            case AstOp.LIMIT:
                assert prev is not None
                st = prev.inherit(prev.var, prev.columns)
                st.limit = p["count"]
                states[node.id] = st
                continue
            case AstOp.OUTPUT:
                assert prev is not None
                tpl = select_template("output", "sql")
                cols = [prev.resolve(c["column"]) for c in p["columns"]]
                order = (
                    " ORDER BY " + ", ".join(f"{q(c)} {d}" for c, d in prev.sort)
                    if prev.sort
                    else ""
                )
                lim = f" LIMIT {prev.limit}" if prev.limit is not None else ""
                final_sql = tpl.render(
                    columns=", ".join(q(c) for c in cols), prev=prev.var, order_by=order, limit=lim
                )
                note(node.id, tpl.id, tpl.version)
                out_columns = cols
                final = prev
                continue
            case _:
                raise UnsupportedAstError(
                    f"sql codegen does not support op {node.op.value!r} (node {node.id!r})"
                )
        ctes.append(f"{var} AS ({body})")
        note(node.id, tpl.id, tpl.version)

    if final is None:
        raise UnsupportedAstError("AST has no output node")
    raw = f"WITH {', '.join(ctes)} {final_sql}"
    formatted = _format(raw, dialect)
    return GeneratedCode(
        text=f"{header_comment(query, '--')}\n{formatted}\n",
        target="sql",
        dialect=dialect,
        provenance=provenance,
        columns=out_columns,
    )


def _format(sql: str, dialect: str) -> str:
    """Validate with sqlglot (raises on syntax errors) and pretty-print."""
    tree = sqlglot.parse_one(sql, read=dialect)
    if not isinstance(tree, exp.Select):
        raise UnsupportedAstError("generated SQL is not a single SELECT")
    return tree.sql(dialect=dialect, pretty=True)
