"""Static type checking over IR operands (T-58). Errors name the offending node."""

from __future__ import annotations

from dataclasses import dataclass

from ir.grammar import Ir, IrOp, IrType
from ir.lineage import available_columns

NUMERIC = {IrType.INTEGER, IrType.FLOAT}
ORDERABLE = {IrType.INTEGER, IrType.FLOAT, IrType.STRING, IrType.DATE, IrType.DATETIME}


@dataclass(frozen=True)
class TypeIssue:
    node_id: str
    message: str

    def __str__(self) -> str:
        return f"node {self.node_id}: {self.message}"


class IrTypeError(ValueError):
    def __init__(self, issues: list[TypeIssue]) -> None:
        super().__init__("; ".join(str(i) for i in issues))
        self.issues = issues


def _t(col: dict) -> IrType:
    return IrType(col["type"])


def check_ir(ir: Ir) -> list[TypeIssue]:
    issues: list[TypeIssue] = []
    visible = available_columns(ir.nodes, ir.edges)

    def need(node_id: str, col: dict, what: str) -> None:
        if col["column"] not in visible[node_id]:
            issues.append(
                TypeIssue(
                    node_id, f"{what} column {col['table']}.{col['column']} is not available here"
                )
            )

    for n in ir.nodes:
        p = n.params
        match n.op:
            case IrOp.FILTER:
                need(n.id, p["column"], "filter")
                ctype, vtype = _t(p["column"]), IrType(p["value"]["type"])
                if ctype is not vtype:
                    issues.append(
                        TypeIssue(n.id, f"filter value is {vtype.value}, column is {ctype.value}")
                    )
                if p["operator"] in ("gt", "gte", "lt", "lte") and ctype not in ORDERABLE:
                    issues.append(
                        TypeIssue(n.id, f"operator {p['operator']} is not valid on {ctype.value}")
                    )
            case IrOp.JOIN:
                lk, rk = p["left_key"], p["right_key"]
                lt, rt = _t(lk), _t(rk)
                if lt is not rt:
                    left = f"{lk['table']}.{lk['column']} ({lt.value})"
                    right = f"{rk['table']}.{rk['column']} ({rt.value})"
                    issues.append(
                        TypeIssue(n.id, f"join keys {left} and {right} have incompatible types")
                    )
            case IrOp.AGGREGATE:
                need(n.id, p["metric"], "aggregate metric")
                for g in p["group_by"]:
                    need(n.id, g, "group-by")
                mtype = _t(p["metric"])
                if p["op"] in ("sum", "avg") and mtype not in NUMERIC:
                    issues.append(
                        TypeIssue(
                            n.id,
                            f"{p['op']} needs a numeric input but "
                            f"{p['metric']['table']}.{p['metric']['column']} is {mtype.value}",
                        )
                    )
            case IrOp.WINDOW:
                need(n.id, p["column"], "window")
            case IrOp.SORT:
                need(n.id, p["by"], "sort")
            case IrOp.FORECAST:
                need(n.id, p["metric"], "forecast metric")
                if _t(p["metric"]) not in NUMERIC:
                    issues.append(TypeIssue(n.id, "forecast needs a numeric metric"))
            case IrOp.OUTPUT:
                for c in p["columns"]:
                    need(n.id, c, "output")
            case _:
                pass
    return issues


def assert_well_typed(ir: Ir) -> None:
    issues = check_ir(ir)
    if issues:
        raise IrTypeError(issues)
