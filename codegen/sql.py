"""AST -> SQL (T-76). Single SELECT; validated with sqlglot."""

from __future__ import annotations

import sqlglot

from ast_.nodes import AstDocument, AstOp, AstTarget
from codegen.common import UnsupportedAstError, header_comment, linear_nodes, result_alias

_OPERATORS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _literal(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def generate_sql(doc: AstDocument, query: str, dialect: str = "sqlite") -> str:
    if doc.target is not AstTarget.SQL:
        raise UnsupportedAstError(f"expected a sql-target AST, got {doc.target.value!r}")

    table = ""
    where: list[str] = []
    group_cols: list[str] = []
    select_expr = ""
    alias = ""
    order = ""
    limit = ""
    for node in linear_nodes(doc):
        p = node.params
        match node.op:
            case AstOp.SELECT:
                table = p["table"]
            case AstOp.FILTER:
                where.append(
                    f"{p['column']['column']} {_OPERATORS[p['operator']]} "
                    f"{_literal(p['value']['value'])}"
                )
            case AstOp.AGGREGATE:
                alias = result_alias(node)
                group_cols = [c["column"] for c in p["group_by"]]
                select_expr = f"{p['op'].upper()}({p['metric']['column']}) AS {alias}"
            case AstOp.SORT:
                by = alias if p["by"]["column"] == doc_metric(doc) else p["by"]["column"]
                order = f"ORDER BY {by} {p['direction'].upper()}"
            case AstOp.LIMIT:
                limit = f"LIMIT {p['count']}"
            case AstOp.OUTPUT:
                pass
            case _:
                raise UnsupportedAstError(f"sql codegen does not support op {node.op.value!r}")

    lines = [header_comment(query, "--")]
    lines.append("SELECT " + ", ".join([*group_cols, select_expr]))
    lines.append(f"FROM {table}")
    if where:
        lines.append("WHERE " + " AND ".join(where))
    if group_cols:
        lines.append("GROUP BY " + ", ".join(group_cols))
    if order:
        lines.append(order)
    if limit:
        lines.append(limit)
    sql = "\n".join(lines) + "\n"
    sqlglot.parse_one(sql, read=dialect)  # raises on syntax errors
    return sql


def doc_metric(doc: AstDocument) -> str:
    agg = next(n for n in doc.nodes if n.op is AstOp.AGGREGATE)
    return str(agg.params["metric"]["column"])
