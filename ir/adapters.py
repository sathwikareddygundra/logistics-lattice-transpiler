"""Plant-specific IR adapters (T-60).

Each plant stores the same logical tables under its own physical names. The
adapter rewrites them once, at IR level, so no later stage needs to know
which plant it is generating for.
"""

from __future__ import annotations

from ir.grammar import Ir, IrOp, Node
from plantdb.plants import get_profile


def to_plant_ir(ir: Ir, plant: str) -> Ir:
    names = get_profile(plant).table_names
    nodes = []
    for n in ir.nodes:
        if n.op is IrOp.SELECT:
            params = dict(n.params)
            params["table"] = names[params["table"]]
            n = Node(id=n.id, op=n.op, params=params)
        nodes.append(n)
    return Ir(trace_id=ir.trace_id, nodes=nodes, edges=ir.edges)
