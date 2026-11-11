"""Stable, readable IR rendering (T-61): same IR, same text, so diffs are meaningful."""

from __future__ import annotations

from ir.grammar import Ir


def _col(c: dict) -> str:
    return f"{c['table']}.{c['column']}:{c['type']}"


def _params(op: str, p: dict) -> str:
    match op:
        case "select":
            return f"{p['table']}[{', '.join(c['column'] for c in p['columns'])}]"
        case "filter":
            return f"{_col(p['column'])} {p['operator']} {p['value']['value']!r}"
        case "join":
            return f"{_col(p['left_key'])} = {_col(p['right_key'])} ({p['how']})"
        case "aggregate":
            groups = ", ".join(_col(c) for c in p["group_by"]) or "-"
            return f"{p['op']}({_col(p['metric'])}) -> {p['result_type']} by [{groups}]"
        case "window":
            return f"{_col(p['column'])} per {p['granularity']}"
        case "sort":
            return f"by {_col(p['by'])} {p['direction']}"
        case "limit":
            return str(p["count"])
        case "forecast":
            return f"{_col(p['metric'])} horizon={p['horizon']} ({p['method']})"
        case _:
            return ", ".join(_col(c) for c in p["columns"])


def render_ir(ir: Ir) -> str:
    inputs: dict[str, list[str]] = {}
    for e in ir.edges:
        tag = e.from_node + (f"[{e.role.value}]" if e.role else "")
        inputs.setdefault(e.to_node, []).append(tag)
    lines = [f"ir v{ir.schema_version}"]
    for n in ir.nodes:
        src = f"  <- {', '.join(sorted(inputs[n.id]))}" if n.id in inputs else ""
        lines.append(f"{n.id} {n.op.value}: {_params(n.op.value, n.params)}{src}")
    return "\n".join(lines) + "\n"
