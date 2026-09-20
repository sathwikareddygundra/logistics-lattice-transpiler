"""
T-14 — validator for ir.schema.json.

Two layers, same readable-error philosophy as T-12/T-13's validators:
  1. JSON Schema (Draft 2020-12) checks per-object shape: field types,
     enums, and each op's params shape (via the if/then branches in
     ir.schema.json).
  2. ir.grammar.Ir (T-56) checks what a JSON Schema instance check can't
     express: graph-level invariants (unique node ids, edges that
     reference real nodes, acyclicity, join edge arity) AND cross-field
     typed-reasoning checks (join key type compatibility, aggregate
     result type, filter value type, window column temporality) -- the
     whole point of IR being a typed layer, per docs/T-56-ir-grammar-adr.md.

Usage:
    python3 validate_ir.py path/to/instance.json [more.json ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import jsonschema  # noqa: E402
from pydantic import ValidationError as PydanticValidationError  # noqa: E402

from ir.grammar import Ir  # noqa: E402

SCHEMA_PATH = Path(__file__).parent / "ir.schema.json"


class SchemaValidationError(Exception):
    """Raised with a readable, path-qualified message."""


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate(instance: dict, schema: dict | None = None) -> list[str]:
    """Returns a list of readable error messages; empty list means valid.

    Runs JSON Schema validation first. Only if that passes does it also
    run T-56's structural and typed checks -- those assume well-shaped
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
        Ir.model_validate(instance)
    except PydanticValidationError as exc:
        messages.append(str(exc))

    return messages


def validate_or_raise(instance: dict, schema: dict | None = None) -> None:
    errors = validate(instance, schema)
    if errors:
        raise SchemaValidationError("; ".join(errors))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 validate_ir.py file1.json [file2.json ...]")
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
