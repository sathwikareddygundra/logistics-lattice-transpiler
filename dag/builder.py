"""Parsed intent -> draft DAG (T-35, linear-chain templates only for now)."""

from __future__ import annotations

from dag.model import Dag, Edge, Node, NodeType
from nlu.intent import IntentType, ParsedIntent


class UnsupportedIntentError(ValueError):
    pass


def intent_to_dag(intent: ParsedIntent, trace_id: str) -> Dag:
    if intent.intent_type is IntentType.OUT_OF_SCOPE:
        raise UnsupportedIntentError(f"cannot build a DAG for out-of-scope query: {intent.query!r}")
    if intent.table is None or intent.metric is None or intent.agg is None:
        raise UnsupportedIntentError(f"intent is missing table/metric/agg: {intent.query!r}")

    nodes: list[Node] = [Node(id="n1", node_type=NodeType.SOURCE, params={"source": intent.table})]

    def add(node_type: NodeType, params: dict) -> None:
        nodes.append(Node(id=f"n{len(nodes) + 1}", node_type=node_type, params=params))

    for f in intent.filters:
        add(
            NodeType.FILTER,
            {"column": f.column, "operator": f.operator.value, "value": f.value},
        )
    add(
        NodeType.AGGREGATE,
        {"group_by": intent.group_by, "metric": intent.metric, "op": intent.agg.value},
    )
    if intent.sort_direction is not None:
        add(NodeType.SORT, {"by": intent.metric, "direction": intent.sort_direction.value})
    if intent.limit is not None:
        add(NodeType.LIMIT, {"count": intent.limit})
    add(NodeType.OUTPUT, {"columns": [*intent.group_by, intent.metric]})

    edges = [Edge(from_node=a.id, to_node=b.id) for a, b in zip(nodes, nodes[1:], strict=False)]
    return Dag(trace_id=trace_id, nodes=nodes, edges=edges)
