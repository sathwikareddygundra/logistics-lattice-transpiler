"""Parsed intent -> draft DAG (T-35): compositional templates per intent."""

from __future__ import annotations

from dag.dependencies import infer_edges, window_alias
from dag.model import Dag, Node, NodeType
from nlu.intent import IntentType, ParsedIntent
from plantdb.catalog import JOIN_KEY, owner_table


class UnsupportedIntentError(ValueError):
    pass


def intent_to_dag(intent: ParsedIntent, trace_id: str, forecast_node: bool = False) -> Dag:
    """Source(s) -> [join chain] -> filters -> [window] -> [aggregate] -> [sort] ->
    [limit] -> output. `forecast_node` adds an explicit forecast step for FORECAST
    intents (otherwise forecasting happens after the cross-plant merge)."""
    if intent.intent_type is IntentType.OUT_OF_SCOPE:
        raise UnsupportedIntentError(f"cannot build a DAG for out-of-scope query: {intent.query!r}")
    if intent.missing_slots:
        raise UnsupportedIntentError(f"intent still has missing slots: {intent.missing_slots}")

    nodes: list[Node] = []

    def add(node_type: NodeType, params: dict) -> str:
        node_id = f"n{len(nodes) + 1}"
        nodes.append(Node(id=node_id, node_type=node_type, params=params))
        return node_id

    for table in intent.tables():
        add(NodeType.SOURCE, {"source": table})
    for _ in intent.tables()[1:]:
        add(NodeType.JOIN, {"on": JOIN_KEY, "how": "inner"})
    # joins must come after all sources in the node list; the lineage pass wires them
    for f in intent.filters:
        add(NodeType.FILTER, {"column": f.column, "operator": f.operator.value, "value": f.value})

    group_by = list(intent.group_by)
    sort_by: str | None = None
    if intent.is_row_listing:
        out_cols = list(intent.select_columns)
        add(NodeType.SORT, {"by": JOIN_KEY, "direction": "asc"})
    else:
        assert intent.metric is not None and intent.agg is not None
        if intent.granularity is not None:
            tcol = intent.time_column or "dispatch_date"
            add(NodeType.WINDOW, {"column": tcol, "granularity": intent.granularity.value})
            bucket = window_alias(tcol, intent.granularity.value)
            group_by = [bucket, *group_by]
            sort_by = bucket
        add(
            NodeType.AGGREGATE,
            {"group_by": group_by, "metric": intent.metric, "op": intent.agg.value},
        )
        out_cols = [*group_by, intent.metric]
        if forecast_node and intent.horizon:
            add(NodeType.FORECAST, {"metric": intent.metric, "horizon": intent.horizon})
        if intent.sort_direction is not None:
            add(
                NodeType.SORT,
                {"by": sort_by or intent.metric, "direction": intent.sort_direction.value},
            )
    if intent.limit is not None and not (forecast_node and intent.horizon):
        add(NodeType.LIMIT, {"count": intent.limit})
    add(NodeType.OUTPUT, {"columns": out_cols})

    return Dag(trace_id=trace_id, nodes=nodes, edges=infer_edges(nodes))


__all__ = ["UnsupportedIntentError", "intent_to_dag", "owner_table"]
