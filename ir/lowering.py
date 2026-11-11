"""DAG + CAG context -> IR (T-57). Total: every node type maps or raises."""

from __future__ import annotations

from cag.context import needed_columns
from dag.dependencies import window_alias
from dag.model import Dag, EdgeRole, NodeType
from ir.grammar import AggregateOp, ColumnRef, Edge, Ir, IrOp, IrType, Node
from ir.grammar import EdgeRole as IrEdgeRole
from plantdb.catalog import JOIN_KEY, column_type, owner_table


class UnmappedNodeTypeError(ValueError):
    pass


_OP_FOR_NODE_TYPE = {
    NodeType.SOURCE: IrOp.SELECT,
    NodeType.FILTER: IrOp.FILTER,
    NodeType.JOIN: IrOp.JOIN,
    NodeType.AGGREGATE: IrOp.AGGREGATE,
    NodeType.WINDOW: IrOp.WINDOW,
    NodeType.SORT: IrOp.SORT,
    NodeType.LIMIT: IrOp.LIMIT,
    NodeType.FORECAST: IrOp.FORECAST,
    NodeType.OUTPUT: IrOp.OUTPUT,
}


def _source_table(dag: Dag, join_id: str, role: EdgeRole) -> str:
    """The table feeding one side of a join, looking through pushed-down filters."""
    by_id = {n.id: n for n in dag.nodes}
    edge = next(e for e in dag.edges if e.to_node == join_id and e.role is role)
    node = by_id[edge.from_node]
    while node.node_type is not NodeType.SOURCE:
        if node.node_type is not NodeType.FILTER:
            raise UnmappedNodeTypeError(
                f"join {join_id!r}: {role.value} input must be a source or filtered source "
                "(left-deep joins only)"
            )
        node = by_id[next(e.from_node for e in dag.edges if e.to_node == node.id)]
    return str(node.params["source"])


def dag_to_ir(dag: Dag) -> Ir:
    slices = needed_columns(dag)  # CAG: only the schema each source needs
    sources = [n for n in dag.nodes if n.node_type is NodeType.SOURCE]
    hub = sources[0].params["source"]
    derived: dict[str, str] = {}  # derived column -> table of its base column
    for n in dag.nodes:
        if n.node_type is NodeType.WINDOW:
            col = n.params["column"]
            derived[window_alias(col, n.params["granularity"])] = owner_table(col)

    def ref(column: str) -> dict:
        if column in derived:
            r = ColumnRef(table=derived[column], column=column, type=IrType.STRING)
        else:
            table = hub if column == JOIN_KEY else owner_table(column)
            r = ColumnRef(table=table, column=column, type=column_type(table, column))
        return r.model_dump(mode="json")

    ir_nodes: list[Node] = []
    for node in dag.nodes:
        if node.node_type not in _OP_FOR_NODE_TYPE:
            raise UnmappedNodeTypeError(
                f"DAG node type {node.node_type.value!r} has no IR lowering (node {node.id!r})"
            )
        p = node.params
        match node.node_type:
            case NodeType.SOURCE:
                table = p["source"]
                params: dict = {
                    "table": table,
                    "columns": [
                        ColumnRef(table=table, column=c, type=column_type(table, c)).model_dump(
                            mode="json"
                        )
                        for c in slices[table]
                    ],
                }
            case NodeType.FILTER:
                col = ref(p["column"])
                params = {
                    "column": col,
                    "operator": p["operator"],
                    "value": {"value": p["value"], "type": col["type"]},
                }
            case NodeType.JOIN:
                right_table = _source_table(dag, node.id, EdgeRole.RIGHT)
                params = {
                    "left_key": ref(p["on"]),
                    "right_key": ColumnRef(
                        table=right_table, column=p["on"], type=column_type(right_table, p["on"])
                    ).model_dump(mode="json"),
                    "how": p["how"],
                }
            case NodeType.AGGREGATE:
                metric = ref(p["metric"])
                op = AggregateOp(p["op"])
                if op is AggregateOp.COUNT:
                    result = IrType.INTEGER
                elif op in (AggregateOp.SUM, AggregateOp.AVG):
                    result = IrType.FLOAT
                else:
                    result = IrType(metric["type"])
                params = {
                    "group_by": [ref(c) for c in p["group_by"]],
                    "metric": metric,
                    "op": op.value,
                    "result_type": result.value,
                }
            case NodeType.WINDOW:
                params = {"column": ref(p["column"]), "granularity": p["granularity"]}
            case NodeType.SORT:
                params = {"by": ref(p["by"]), "direction": p["direction"]}
            case NodeType.LIMIT:
                params = {"count": p["count"]}
            case NodeType.FORECAST:
                params = {
                    "metric": ref(p["metric"]),
                    "horizon": p["horizon"],
                    "method": p["method"],
                }
            case _:  # OUTPUT
                params = {"columns": [ref(c) for c in p["columns"]]}
        ir_nodes.append(Node(id=node.id, op=_OP_FOR_NODE_TYPE[node.node_type], params=params))

    edges = [
        Edge(
            from_node=e.from_node,
            to_node=e.to_node,
            role=IrEdgeRole(e.role.value) if e.role else None,
        )
        for e in dag.edges
    ]
    return Ir(trace_id=dag.trace_id, nodes=ir_nodes, edges=edges)
