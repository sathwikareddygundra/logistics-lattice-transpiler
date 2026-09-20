"""
T-34 — DAG node/edge data model.

The canonical Python representation of a query execution plan: a directed
acyclic graph of typed Node objects connected by Edge objects. This is what
T-35 (parsed intent -> DAG) will build, and what T-13's JSON Schema mirrors
as the wire contract between the DAG stage (Phase 5, produces this) and
graph_eng (Phase 5, consumes it).

Every IntentType (T-17) that isn't out_of_scope compiles down to some
combination of these node types:
  aggregation -> source -> [filter] -> aggregate -> output
  join        -> source, source -> join -> output
  filter      -> source -> filter -> output
  comparison  -> source -> aggregate (grouped) -> output
  trend       -> source -> window -> aggregate -> output
  rank        -> source -> aggregate -> sort -> limit -> output
  forecast    -> source -> aggregate -> forecast -> output

Structural invariants -- unique node ids, edges that reference real nodes,
no self-loops, no cycles, and node-type-specific edge shape (a source has
no inputs, an output has no outputs, a join has exactly a left and a right
input) -- are enforced here rather than left to callers, same philosophy as
T-10's Shipment/TrackingEvent resolving T-9's data-quality flags instead of
passing them downstream.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic import ValidationError as PydanticValidationError


class NodeType(StrEnum):
    SOURCE = "source"
    FILTER = "filter"
    JOIN = "join"
    AGGREGATE = "aggregate"
    WINDOW = "window"
    SORT = "sort"
    LIMIT = "limit"
    FORECAST = "forecast"
    OUTPUT = "output"


class FilterOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    BETWEEN = "between"


class JoinType(StrEnum):
    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    OUTER = "outer"


class AggregateOp(StrEnum):
    SUM = "sum"
    COUNT = "count"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class Granularity(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class EdgeRole(StrEnum):
    """Only meaningful for multi-input nodes (currently: join)."""

    LEFT = "left"
    RIGHT = "right"


FilterValue = str | int | float | bool | list[str] | list[int] | list[float]


class SourceParams(BaseModel):
    """`source` is a schemas.registry.Source value (dispatch, tracking,
    turnaround_time), kept as a plain str here to avoid a schemas <-> dag
    import cycle -- schemas/validate_dag.py checks it against the real
    enum at validation time."""

    source: str = Field(min_length=1)


class FilterParams(BaseModel):
    column: str = Field(min_length=1)
    operator: FilterOperator
    value: FilterValue


class JoinParams(BaseModel):
    on: str = Field(min_length=1)
    how: JoinType = JoinType.INNER


class AggregateParams(BaseModel):
    group_by: list[str] = Field(default_factory=list)
    metric: str = Field(min_length=1)
    op: AggregateOp


class WindowParams(BaseModel):
    column: str = Field(min_length=1)
    granularity: Granularity


class SortParams(BaseModel):
    by: str = Field(min_length=1)
    direction: SortDirection = SortDirection.ASC


class LimitParams(BaseModel):
    count: int = Field(gt=0)


class ForecastParams(BaseModel):
    metric: str = Field(min_length=1)
    horizon: int = Field(gt=0)
    method: str = "linear"


class OutputParams(BaseModel):
    columns: list[str] = Field(default_factory=list)


_PARAMS_BY_NODE_TYPE: dict[NodeType, type[BaseModel]] = {
    NodeType.SOURCE: SourceParams,
    NodeType.FILTER: FilterParams,
    NodeType.JOIN: JoinParams,
    NodeType.AGGREGATE: AggregateParams,
    NodeType.WINDOW: WindowParams,
    NodeType.SORT: SortParams,
    NodeType.LIMIT: LimitParams,
    NodeType.FORECAST: ForecastParams,
    NodeType.OUTPUT: OutputParams,
}


class Node(BaseModel):
    id: str = Field(min_length=1)
    node_type: NodeType
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _params_match_node_type(self) -> Node:
        params_cls = _PARAMS_BY_NODE_TYPE[self.node_type]
        try:
            validated = params_cls.model_validate(self.params)
        except PydanticValidationError as exc:
            raise ValueError(
                f"node {self.id!r} ({self.node_type.value}): invalid params -- {exc}"
            ) from exc
        self.params = validated.model_dump()
        return self


class Edge(BaseModel):
    from_node: str = Field(min_length=1)
    to_node: str = Field(min_length=1)
    role: EdgeRole | None = None

    @model_validator(mode="after")
    def _no_self_loop(self) -> Edge:
        if self.from_node == self.to_node:
            raise ValueError(f"edge {self.from_node!r} -> {self.to_node!r} is a self-loop")
        return self


def structural_errors(nodes: list[Node], edges: list[Edge]) -> list[str]:
    """Graph-level invariants a JSON Schema instance check can't express on
    its own: unique ids, edges that reference real nodes, acyclicity, and
    node-type-specific edge arity. Returns readable error messages; an
    empty list means the graph is structurally valid."""
    errors: list[str] = []

    seen: set[str] = set()
    for node in nodes:
        if node.id in seen:
            errors.append(f"duplicate node id: {node.id!r}")
        seen.add(node.id)

    nodes_by_id = {node.id: node for node in nodes}
    for edge in edges:
        if edge.from_node not in nodes_by_id:
            errors.append(f"edge references unknown from_node: {edge.from_node!r}")
        if edge.to_node not in nodes_by_id:
            errors.append(f"edge references unknown to_node: {edge.to_node!r}")

    if errors:
        return errors  # remaining checks assume every edge endpoint resolves

    incoming: dict[str, list[Edge]] = {node_id: [] for node_id in nodes_by_id}
    outgoing: dict[str, list[Edge]] = {node_id: [] for node_id in nodes_by_id}
    for edge in edges:
        incoming[edge.to_node].append(edge)
        outgoing[edge.from_node].append(edge)

    for node in nodes:
        if node.node_type is NodeType.SOURCE and incoming[node.id]:
            errors.append(f"source node {node.id!r} must not have incoming edges")
        elif node.node_type is not NodeType.SOURCE and not incoming[node.id]:
            errors.append(f"non-source node {node.id!r} has no incoming edges")

        if node.node_type is NodeType.OUTPUT and outgoing[node.id]:
            errors.append(f"output node {node.id!r} must not have outgoing edges")

        if node.node_type is NodeType.JOIN:
            roles = sorted(edge.role.value for edge in incoming[node.id] if edge.role is not None)
            if len(incoming[node.id]) != 2 or roles != ["left", "right"]:
                errors.append(
                    f"join node {node.id!r} must have exactly two incoming edges, "
                    "roled 'left' and 'right'"
                )

    output_nodes = [node for node in nodes if node.node_type is NodeType.OUTPUT]
    if len(output_nodes) != 1:
        errors.append(f"dag must have exactly one output node, found {len(output_nodes)}")

    if not errors and _has_cycle(nodes_by_id, outgoing):
        errors.append("dag contains a cycle")

    return errors


def _has_cycle(nodes_by_id: dict[str, Node], outgoing: dict[str, list[Edge]]) -> bool:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(nodes_by_id, WHITE)

    def visit(node_id: str) -> bool:
        color[node_id] = GRAY
        for edge in outgoing[node_id]:
            next_id = edge.to_node
            if color[next_id] == GRAY:
                return True
            if color[next_id] == WHITE and visit(next_id):
                return True
        color[node_id] = BLACK
        return False

    return any(color[node_id] == WHITE and visit(node_id) for node_id in nodes_by_id)


class Dag(BaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    trace_id: str = Field(min_length=1)
    nodes: list[Node] = Field(min_length=1)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structurally_valid(self) -> Dag:
        errors = structural_errors(self.nodes, self.edges)
        if errors:
            raise ValueError("; ".join(errors))
        return self


def allowed_node_type_values() -> list[str]:
    """The exact enum values T-13's JSON Schema must expose for node_type."""
    return [member.value for member in NodeType]
