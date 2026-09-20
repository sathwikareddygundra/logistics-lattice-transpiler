"""
T-63 — target AST definition.

Decision (full reasoning in docs/T-63-target-ast-adr.md): Python and SQL
share **one** AST grammar with target-specific adapters downstream, not
two separate grammars. Concretely, an AstDocument reuses T-56's IR
vocabulary unchanged -- same `op` values (`IrOp`, aliased here as
`AstOp`), same typed per-op params -- and adds exactly two things IR
doesn't have, because they only matter once you're about to emit real
source code or SQL text rather than reason about typed data flow:

  - `target`: which of the two codegen passes (T-70 AST->Python,
    T-76 AST->SQL) this document is for.
  - `var`: the name each node's result is bound to (`df1 = ...` in
    Python; a CTE/subquery alias in SQL) -- ASTs are sequences of named
    statements, which IR (a plain data-flow graph) has no notion of.

Every IR operation therefore has a trivial, identity mapping to an AST
node in both targets: the same `op` and `params` shapes work for either
target, because *what* operation runs doesn't change between IR and AST
-- only *how it's about to be rendered* does, and that's T-70/T-76's job,
not this grammar's.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal as TypingLiteral

from pydantic import BaseModel, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from ir.grammar import AggregateParams as AggregateParams
from ir.grammar import ColumnRef as ColumnRef
from ir.grammar import Edge, EdgeRole
from ir.grammar import FilterParams as FilterParams
from ir.grammar import ForecastParams as ForecastParams
from ir.grammar import IrOp as AstOp
from ir.grammar import JoinParams as JoinParams
from ir.grammar import LimitParams as LimitParams
from ir.grammar import Literal as Literal
from ir.grammar import OutputParams as OutputParams
from ir.grammar import SelectParams as SelectParams
from ir.grammar import SortParams as SortParams
from ir.grammar import WindowParams as WindowParams

__all__ = [
    "AggregateParams",
    "AstDocument",
    "AstOp",
    "AstTarget",
    "ColumnRef",
    "Edge",
    "EdgeRole",
    "FilterParams",
    "ForecastParams",
    "JoinParams",
    "Literal",
    "LimitParams",
    "Node",
    "OutputParams",
    "SelectParams",
    "SortParams",
    "WindowParams",
    "allowed_ast_op_values",
    "structural_errors",
]


class AstTarget(StrEnum):
    PYTHON = "python"
    SQL = "sql"


_PARAMS_BY_OP: dict[AstOp, type[BaseModel]] = {
    AstOp.SELECT: SelectParams,
    AstOp.FILTER: FilterParams,
    AstOp.JOIN: JoinParams,
    AstOp.AGGREGATE: AggregateParams,
    AstOp.WINDOW: WindowParams,
    AstOp.SORT: SortParams,
    AstOp.LIMIT: LimitParams,
    AstOp.FORECAST: ForecastParams,
    AstOp.OUTPUT: OutputParams,
}


class Node(BaseModel):
    id: str = Field(min_length=1)
    op: AstOp
    var: str = Field(min_length=1, description="The name this node's result is bound to.")
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _params_match_op(self) -> Node:
        params_cls = _PARAMS_BY_OP[self.op]
        try:
            validated = params_cls.model_validate(self.params)
        except PydanticValidationError as exc:
            raise ValueError(
                f"node {self.id!r} ({self.op.value}): invalid params -- {exc}"
            ) from exc
        self.params = validated.model_dump(mode="json")
        return self


def structural_errors(nodes: list[Node], edges: list[Edge]) -> list[str]:
    """Graph-level invariants a JSON Schema instance check can't express on
    its own. Mirrors ir.grammar.structural_errors -- kept as a separate
    implementation since Node here is ast_.nodes.Node, not ir.grammar.Node,
    even though the op vocabulary and edge shape are shared."""
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
        if node.op is AstOp.SELECT and incoming[node.id]:
            errors.append(f"select node {node.id!r} must not have incoming edges")
        elif node.op is not AstOp.SELECT and not incoming[node.id]:
            errors.append(f"non-select node {node.id!r} has no incoming edges")

        if node.op is AstOp.OUTPUT and outgoing[node.id]:
            errors.append(f"output node {node.id!r} must not have outgoing edges")

        if node.op is AstOp.JOIN:
            join_edges = incoming[node.id]
            roles = sorted(edge.role.value for edge in join_edges if edge.role is not None)
            if len(join_edges) != 2 or roles != ["left", "right"]:
                errors.append(
                    f"join node {node.id!r} must have exactly two incoming edges, "
                    "roled 'left' and 'right'"
                )

    output_nodes = [node for node in nodes if node.op is AstOp.OUTPUT]
    if len(output_nodes) != 1:
        errors.append(f"ast document must have exactly one output node, found {len(output_nodes)}")

    var_seen: set[str] = set()
    var_dupes: set[str] = set()
    for node in nodes:
        if node.var in var_seen:
            var_dupes.add(node.var)
        var_seen.add(node.var)
    for var in sorted(var_dupes):
        errors.append(f"duplicate var binding: {var!r}")

    if not errors and _has_cycle(nodes_by_id, outgoing):
        errors.append("ast document contains a cycle")

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


class AstDocument(BaseModel):
    schema_version: TypingLiteral["1.0.0"] = "1.0.0"
    trace_id: str = Field(min_length=1)
    target: AstTarget
    nodes: list[Node] = Field(min_length=1)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structurally_valid(self) -> AstDocument:
        errors = structural_errors(self.nodes, self.edges)
        if errors:
            raise ValueError("; ".join(errors))
        return self


def allowed_ast_op_values() -> list[str]:
    """The exact enum values T-15's JSON Schema must expose for op.

    Identical to ir.grammar.allowed_ir_op_values() by design: AST reuses
    IR's op vocabulary unchanged (see module docstring).
    """
    return [member.value for member in AstOp]
