"""
T-13 — validator for dag.schema.json.

Two layers, same readable-error philosophy as T-12's validator:
  1. JSON Schema (Draft 2020-12) checks per-object shape: field types,
     enums, and each node_type's params shape (via the if/then branches
     in dag.schema.json).
  2. dag.model.Dag (T-34) checks graph-level invariants a JSON Schema
     instance check can't express: unique node ids, edges that reference
     real nodes, acyclicity, and node-type-specific edge arity (e.g. a
     join needs exactly a 'left' and a 'right' incoming edge).

`jsonschema` is a hard dependency of this project (pyproject.toml), so
unlike T-12's validator there is no offline fallback path here.

Usage:
    python3 validate_dag.py path/to/instance.json [more.json ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import jsonschema  # noqa: E402
from pydantic import ValidationError as PydanticValidationError  # noqa: E402

from dag.model import Dag  # noqa: E402

SCHEMA_PATH = Path(__file__).parent / "dag.schema.json"


class SchemaValidationError(Exception):
    """Raised with a readable, path-qualified message."""


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate(instance: dict, schema: dict | None = None) -> list[str]:
    """Returns a list of readable error messages; empty list means valid.

    Runs JSON Schema validation first. Only if that passes does it also
    run T-34's graph-level structural checks -- those assume well-shaped
    nodes/edges, which the JSON Schema pass already guarantees.
    """
    schema = schema if schema is not None else load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    messages = []
    for err in schema_errors:
        path = "$" + "".join(f"[{p!r}]" if isinstance(p, str) else f"[{p}]" for p in err.path)
        messages.append(f"{path}: {err.message}")
    if messages:
        return messages

    try:
        Dag.model_validate(instance)
    except PydanticValidationError as exc:
        messages.append(str(exc))

    return messages


def validate_or_raise(instance: dict, schema: dict | None = None) -> None:
    errors = validate(instance, schema)
    if errors:
        raise SchemaValidationError("; ".join(errors))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 validate_dag.py file1.json [file2.json ...]")
        raise SystemExit(2)

    schema = load_schema()
    exit_code = 0
    for file_arg in sys.argv[1:]:
        instance = json.loads(Path(file_arg).read_text())
        errors = validate(instance, schema)
        if errors:
            exit_code = 1
            print(f"FAIL  {file_arg}")
            for e in errors:
                print(f"      - {e}")
        else:
            print(f"PASS  {file_arg}")
    raise SystemExit(exit_code)
