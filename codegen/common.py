from __future__ import annotations

from dataclasses import dataclass, field

from ast_.nodes import AstDocument, Node
from graph_eng.toposort import toposort


class UnsupportedAstError(ValueError):
    """AST shape or op that a generator does not handle. Raised loudly,
    never approximated."""


@dataclass(frozen=True)
class CodegenHints:
    """Knobs a retry can turn when the first attempt failed (T-90)."""

    quote_all_identifiers: bool = False


@dataclass
class GeneratedCode:
    text: str
    target: str
    dialect: str
    provenance: list[tuple[str, str, int]] = field(default_factory=list)  # node, template, version
    columns: list[str] = field(default_factory=list)  # output column names


def ordered_nodes(doc: AstDocument) -> list[Node]:
    by_id = {n.id: n for n in doc.nodes}
    order = toposort([n.id for n in doc.nodes], [(e.from_node, e.to_node) for e in doc.edges])
    return [by_id[i] for i in order]


def header_comment(query: str, prefix: str) -> str:
    return f"{prefix} Query: {' '.join(query.split())}"
