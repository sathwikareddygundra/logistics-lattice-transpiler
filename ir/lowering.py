"""DAG -> IR (T-57): total mapping, with column types from the catalog."""

from __future__ import annotations

from dag.model import Dag, NodeType
from ir.grammar import AggregateOp, ColumnRef, Edge, Ir, IrOp, IrType, Node
from plantdb.catalog import column_type, get_table


class UnmappedNodeTypeError(ValueError):
    pass


_OP_FOR_NODE_TYPE = {
    NodeType.SOURCE: IrOp.SELECT,
    NodeType.FILTER: IrOp.FILTER,
    NodeType.AGGREGATE: IrOp.AGGREGATE,
    NodeType.SORT: IrOp.SORT,
    NodeType.LIMIT: IrOp.LIMIT,
    NodeType.OUTPUT: IrOp.OUTPUT,
}


def _ref(table: str, column: str) -> dict:
    return ColumnRef(table=table, column=column, type=column_type(table, column)).model_dump(
        mode="json"
    )


def dag_to_ir(dag: Dag) -> Ir:
    table = next(n.params["source"] for n in dag.nodes if n.node_type is NodeType.SOURCE)
    nodes: list[Node] = []
    for node in dag.nodes:
        if node.node_type not in _OP_FOR_NODE_TYPE:
            raise UnmappedNodeTypeError(
                f"DAG node type {node.node_type.value!r} has no IR lowering yet (node {node.id!r})"
            )
        p = node.params
        match node.node_type:
            case NodeType.SOURCE:
                cols = [_ref(table, c) for c in get_table(table).columns]
                params: dict = {"table": table, "columns": cols}
            case NodeType.FILTER:
                col_type = column_type(table, p["column"])
                params = {
                    "column": _ref(table, p["column"]),
                    "operator": p["operator"],
                    "value": {"value": p["value"], "type": col_type.value},
                }
            case NodeType.AGGREGATE:
                metric_type = column_type(table, p["metric"])
                op = AggregateOp(p["op"])
                if op is AggregateOp.COUNT:
                    result = IrType.INTEGER
                elif op in (AggregateOp.SUM, AggregateOp.AVG):
                    result = IrType.FLOAT
                else:
                    result = metric_type
                params = {
                    "group_by": [_ref(table, c) for c in p["group_by"]],
                    "metric": _ref(table, p["metric"]),
                    "op": op.value,
                    "result_type": result.value,
                }
            case NodeType.SORT:
                params = {"by": _ref(table, p["by"]), "direction": p["direction"]}
            case NodeType.LIMIT:
                params = {"count": p["count"]}
            case _:  # OUTPUT
                params = {"columns": [_ref(table, c) for c in p["columns"]]}
        nodes.append(Node(id=node.id, op=_OP_FOR_NODE_TYPE[node.node_type], params=params))

    edges = [Edge(from_node=e.from_node, to_node=e.to_node) for e in dag.edges]
    return Ir(trace_id=dag.trace_id, nodes=nodes, edges=edges)
