"""CAG: deterministic context assembly (T-49, T-52, T-53).

Lookup and template injection only, with no model calls. `assemble_context`
is a pure function: the same DAG always yields the same context. Only the
schema slice a node touches is included (never the whole schema).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from cag.templates import TEMPLATES, Template, select_template
from dag.dependencies import window_alias
from dag.model import Dag, Node, NodeType
from plantdb.catalog import JOIN_KEY, SCHEMA_VERSION, TABLES, owner_table


@dataclass(frozen=True)
class NodeContext:
    node_id: str
    schema_slice: dict[str, dict[str, str]]  # table -> {column: ir type}
    template_id: str
    template_version: int


def needed_columns(dag: Dag) -> dict[str, list[str]]:
    """Columns each source table must provide: referenced columns, plus the join key
    when more than one table is involved."""
    sources = [n.params["source"] for n in dag.nodes if n.node_type is NodeType.SOURCE]
    derived = {
        window_alias(n.params["column"], n.params["granularity"])
        for n in dag.nodes
        if n.node_type is NodeType.WINDOW
    }
    wanted: dict[str, list[str]] = {t: [] for t in sources}

    def want(column: str) -> None:
        if column in derived:
            return
        table = owner_table(column) if column != JOIN_KEY else sources[0]
        if table in wanted and column not in wanted[table]:
            wanted[table].append(column)

    if len(sources) > 1:
        for t in sources:
            wanted[t].append(JOIN_KEY)
    for node in dag.nodes:
        p = node.params
        match node.node_type:
            case NodeType.FILTER | NodeType.WINDOW:
                want(p["column"])
            case NodeType.AGGREGATE:
                for c in [*p["group_by"], p["metric"]]:
                    want(c)
            case NodeType.SORT:
                want(p["by"])
            case NodeType.FORECAST:
                want(p["metric"])
            case NodeType.OUTPUT:
                for c in p["columns"]:
                    want(c)
    for t, cols in wanted.items():
        if not cols:
            cols.append(JOIN_KEY)
    # catalog order for stable output
    return {t: [c for c in TABLES[t].columns if c in cols] for t, cols in wanted.items()}


def _node_template(node: Node, target: str) -> Template | None:
    """The template a node renders with. SQL folds sort and limit into the final
    SELECT, so they have none; SQL has no forecast template (raises)."""
    if target == "sql" and node.node_type in (NodeType.SORT, NodeType.LIMIT):
        return None
    op = "select" if node.node_type is NodeType.SOURCE else node.node_type.value
    return select_template(op, target)


def assemble_context(
    dag: Dag, target: str = "sql", dialect: str = "sqlite"
) -> dict[str, NodeContext]:
    slices = needed_columns(dag)
    out: dict[str, NodeContext] = {}
    for node in dag.nodes:
        if node.node_type is NodeType.SOURCE:
            table = node.params["source"]
            schema = {table: {c: TABLES[table].columns[c].value for c in slices[table]}}
        else:
            schema = {}
        tpl = _node_template(node, target)
        out[node.id] = NodeContext(
            node.id, schema, tpl.id if tpl else "", tpl.version if tpl else 0
        )
    return out


_CACHE: dict[str, dict[str, NodeContext]] = {}


def assemble_cached(
    dag: Dag, target: str = "sql", dialect: str = "sqlite"
) -> dict[str, NodeContext]:
    """Cache keyed on (schema version, DAG signature, template versions), so any
    version bump invalidates old entries automatically."""
    versions = {t.id: t.version for t in TEMPLATES.values()}
    payload = json.dumps(
        [
            SCHEMA_VERSION,
            dag.model_dump(mode="json", exclude={"trace_id"}),
            target,
            dialect,
            versions,
        ],
        sort_keys=True,
    )
    key = hashlib.sha256(payload.encode()).hexdigest()
    if key not in _CACHE:
        _CACHE[key] = assemble_context(dag, target, dialect)
    return _CACHE[key]


def clear_cache() -> None:
    _CACHE.clear()
