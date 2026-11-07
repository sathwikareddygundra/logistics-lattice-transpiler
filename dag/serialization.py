"""Lossless, diff-friendly DAG (de)serialization (T-38): sorted keys, stable order."""

from __future__ import annotations

import json

from dag.model import Dag


def to_json(dag: Dag) -> str:
    data = dag.model_dump(mode="json")
    data["nodes"] = sorted(data["nodes"], key=lambda n: _natural(n["id"]))
    data["edges"] = sorted(
        data["edges"], key=lambda e: (_natural(e["from_node"]), _natural(e["to_node"]))
    )
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def from_json(text: str) -> Dag:
    return Dag.model_validate(json.loads(text))


def _natural(node_id: str) -> tuple:
    import re

    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", node_id))
