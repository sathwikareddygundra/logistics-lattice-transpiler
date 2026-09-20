"""
T-56 — IR grammar.

Defines what an IR document actually is: a typed, language-agnostic
vocabulary of operations (select, filter, join, aggregate, window, sort,
limit, forecast, output) over typed operands (columns and literals).

Why IR exists as its own layer (the ADR requested by T-56's "How", filed
in full at docs/T-56-ir-grammar-adr.md): the DAG (T-34) is task-shaped --
its nodes describe *what operation to run* over opaque params. The AST
(T-63, not yet built) will be language-shaped -- its nodes describe
*how a specific target language expresses* an operation. IR sits between
them: every operand here carries an explicit IrType, so type mismatches
(an incompatible join key, a non-numeric aggregate input) are represented
in the grammar itself rather than discovered by generated code at
runtime. That's "language-agnostic typed reasoning": IR doesn't know or
care whether it will end up as pandas or SQL, but it does know that a
DATE column can't be joined against a STRING column.

Every DAG (T-34) node type has a corresponding IrOp here:
  dag source    -> ir select     (produces typed columns from a table)
  dag filter    -> ir filter
  dag join      -> ir join
  dag aggregate -> ir aggregate
  dag window    -> ir window
  dag sort      -> ir sort
  dag limit     -> ir limit
  dag forecast  -> ir forecast
  dag output    -> ir output

T-14's JSON Schema (schemas/ir.schema.json) mirrors this grammar as the
wire contract, the same relationship T-13's dag.schema.json has with
dag/model.py.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal as TypingLiteral

from pydantic import BaseModel, Field, model_validator


class IrOp(StrEnum):
    SELECT = "select"
    FILTER = "filter"
    JOIN = "join"
    AGGREGATE = "aggregate"
    WINDOW = "window"
    SORT = "sort"
    LIMIT = "limit"
    FORECAST = "forecast"
    OUTPUT = "output"


class IrType(StrEnum):
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"


class ComparisonOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


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


LiteralValue = str | int | float | bool


class ColumnRef(BaseModel):
    table: str = Field(min_length=1)
    column: str = Field(min_length=1)
    type: IrType


class Literal(BaseModel):
    value: LiteralValue
    type: IrType


class SelectParams(BaseModel):
    table: str = Field(min_length=1)
    columns: list[ColumnRef] = Field(min_length=1)


class FilterParams(BaseModel):
    column: ColumnRef
    operator: ComparisonOperator
    value: Literal

    @model_validator(mode="after")
    def _value_type_matches_column(self) -> FilterParams:
        if self.value.type is not self.column.type:
            raise ValueError(
                f"filter value type {self.value.type.value!r} does not match "
                f"column {self.column.table}.{self.column.column}'s type "
                f"{self.column.type.value!r}"
            )
        return self


class JoinParams(BaseModel):
    left_key: ColumnRef
    right_key: ColumnRef
    how: JoinType = JoinType.INNER

    @model_validator(mode="after")
    def _keys_are_type_compatible(self) -> JoinParams:
        if self.left_key.type is not self.right_key.type:
            raise ValueError(
                f"join key type mismatch: {self.left_key.table}.{self.left_key.column} "
                f"is {self.left_key.type.value!r} but "
                f"{self.right_key.table}.{self.right_key.column} is "
                f"{self.right_key.type.value!r}"
            )
        return self


class AggregateParams(BaseModel):
    group_by: list[ColumnRef] = Field(default_factory=list)
    metric: ColumnRef
    op: AggregateOp
    result_type: IrType

    @model_validator(mode="after")
    def _result_type_matches_op(self) -> AggregateParams:
        if self.op is AggregateOp.COUNT:
            expected = IrType.INTEGER
        elif self.op in (AggregateOp.SUM, AggregateOp.AVG):
            expected = IrType.FLOAT
        else:  # MIN, MAX
            expected = self.metric.type
        if self.result_type is not expected:
            raise ValueError(
                f"aggregate op {self.op.value!r} on "
                f"{self.metric.table}.{self.metric.column} must produce "
                f"result_type {expected.value!r}, got {self.result_type.value!r}"
            )
        return self


class WindowParams(BaseModel):
    column: ColumnRef
    granularity: Granularity

    @model_validator(mode="after")
    def _column_is_temporal(self) -> WindowParams:
        if self.column.type not in (IrType.DATE, IrType.DATETIME):
            raise ValueError(
                f"window column {self.column.table}.{self.column.column} must be "
                f"date or datetime, got {self.column.type.value!r}"
            )
        return self


class SortParams(BaseModel):
    by: ColumnRef
    direction: SortDirection = SortDirection.ASC


class LimitParams(BaseModel):
    count: int = Field(gt=0)


class ForecastParams(BaseModel):
    metric: ColumnRef
    horizon: int = Field(gt=0)
    method: str = "linear"


class OutputParams(BaseModel):
    columns: list[ColumnRef] = Field(default_factory=list)


_PARAMS_BY_OP: dict[IrOp, type[BaseModel]] = {
    IrOp.SELECT: SelectParams,
    IrOp.FILTER: FilterParams,
    IrOp.JOIN: JoinParams,
    IrOp.AGGREGATE: AggregateParams,
    IrOp.WINDOW: WindowParams,
    IrOp.SORT: SortParams,
    IrOp.LIMIT: LimitParams,
    IrOp.FORECAST: ForecastParams,
    IrOp.OUTPUT: OutputParams,
}


class Node(BaseModel):
    id: str = Field(min_length=1)
    op: IrOp
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _params_match_op(self) -> Node:
        params_cls = _PARAMS_BY_OP[self.op]
        try:
            validated = params_cls.model_validate(self.params)
        except Exception as exc:  # pydantic.ValidationError or our own ValueError
            raise ValueError(
                f"node {self.id!r} ({self.op.value}): invalid params -- {exc}"
            ) from exc
        self.params = validated.model_dump(mode="json")
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
    op-specific edge arity. Mirrors dag.model.structural_errors -- kept as
    a separate implementation since IR is deliberately its own layer, not
    a thin wrapper around the DAG's graph logic."""
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
        if node.op is IrOp.SELECT and incoming[node.id]:
            errors.append(f"select node {node.id!r} must not have incoming edges")
        elif node.op is not IrOp.SELECT and not incoming[node.id]:
            errors.append(f"non-select node {node.id!r} has no incoming edges")

        if node.op is IrOp.OUTPUT and outgoing[node.id]:
            errors.append(f"output node {node.id!r} must not have outgoing edges")

        if node.op is IrOp.JOIN:
            join_edges = incoming[node.id]
            roles = sorted(edge.role.value for edge in join_edges if edge.role is not None)
            if len(join_edges) != 2 or roles != ["left", "right"]:
                errors.append(
                    f"join node {node.id!r} must have exactly two incoming edges, "
                    "roled 'left' and 'right'"
                )

    output_nodes = [node for node in nodes if node.op is IrOp.OUTPUT]
    if len(output_nodes) != 1:
        errors.append(f"ir document must have exactly one output node, found {len(output_nodes)}")

    if not errors and _has_cycle(nodes_by_id, outgoing):
        errors.append("ir document contains a cycle")

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


class Ir(BaseModel):
    schema_version: TypingLiteral["1.0.0"] = "1.0.0"
    trace_id: str = Field(min_length=1)
    nodes: list[Node] = Field(min_length=1)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structurally_valid(self) -> Ir:
        errors = structural_errors(self.nodes, self.edges)
        if errors:
            raise ValueError("; ".join(errors))
        return self


def allowed_ir_op_values() -> list[str]:
    """The exact enum values T-14's JSON Schema must expose for op."""
    return [member.value for member in IrOp]
