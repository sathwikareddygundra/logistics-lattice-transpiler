"""
T-12 — validator for parsed_intent.schema.json.

Uses the real `jsonschema` library (Draft 2020-12) when it's installed --
that's the intended, standard path once you `uv add jsonschema` /
`poetry add jsonschema` per T-2 and run this in a networked environment.

Falls back to a small hand-rolled validator when `jsonschema` isn't
available (e.g. this offline sandbox), covering exactly the keyword
subset parsed_intent.schema.json actually uses: type, enum, const,
required, additionalProperties, properties, items, $ref/$defs, minimum,
maximum, minLength, format(uuid). This is NOT a general JSON Schema
implementation -- don't reuse it for T-13/T-14/T-15's schemas without
extending it, or just install `jsonschema` there too.

Usage:
    python3 validate_parsed_intent.py path/to/instance.json [more.json ...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "parsed_intent.schema.json"

try:
    import jsonschema

    _HAVE_JSONSCHEMA = True
except ImportError:
    _HAVE_JSONSCHEMA = False


class SchemaValidationError(Exception):
    """Raised with a readable, path-qualified message."""


# --------------------------------------------------------------------------
# Real path: the standard `jsonschema` library.
# --------------------------------------------------------------------------
def _validate_with_jsonschema(instance: dict, schema: dict) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    messages = []
    for err in errors:
        path = "$" + "".join(f"[{p!r}]" if isinstance(p, str) else f"[{p}]" for p in err.path)
        messages.append(f"{path}: {err.message}")
    return messages


# --------------------------------------------------------------------------
# Fallback path: minimal hand-rolled validator (offline sandbox only).
# --------------------------------------------------------------------------
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_PY_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _matches_type(value, type_spec) -> bool:
    types = type_spec if isinstance(type_spec, list) else [type_spec]
    for t in types:
        if t == "number":
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return True
        elif t == "integer":
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return True
        elif t in _PY_TYPE_MAP:
            if isinstance(value, _PY_TYPE_MAP[t]) and not (
                t != "boolean" and isinstance(value, bool)
            ):
                return True
    return False


def _resolve(schema: dict, defs: dict) -> dict:
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/$defs/"), f"unsupported $ref: {ref}"
        return defs[ref[len("#/$defs/") :]]
    return schema


def _validate_minimal(instance, schema, defs, path, errors: list[str]) -> None:
    schema = _resolve(schema, defs)

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: {instance!r} does not equal const {schema['const']!r}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} is not one of {schema['enum']!r}")

    if "type" in schema and not _matches_type(instance, schema["type"]):
        errors.append(f"{path}: {instance!r} is not of type {schema['type']!r}")
        return  # further checks would be nonsensical on a type mismatch

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: string is shorter than minLength {schema['minLength']}")
        if schema.get("format") == "uuid" and not _UUID_RE.match(instance):
            errors.append(f"{path}: {instance!r} is not a valid uuid")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} is less than the minimum of {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} is greater than the maximum of {schema['maximum']}")

    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property {req!r}")
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(props)
            for key in sorted(extra):
                errors.append(f"{path}[{key!r}]: additional property {key!r} is not allowed")
        for key, value in instance.items():
            if key in props:
                _validate_minimal(value, props[key], defs, f"{path}[{key!r}]", errors)

    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            _validate_minimal(item, schema["items"], defs, f"{path}[{i}]", errors)


def _validate_with_minimal(instance: dict, schema: dict) -> list[str]:
    defs = schema.get("$defs", {})
    errors: list[str] = []
    _validate_minimal(instance, schema, defs, "$", errors)
    return errors


# --------------------------------------------------------------------------
# Public entry point.
# --------------------------------------------------------------------------
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate(instance: dict, schema: dict | None = None) -> list[str]:
    """Returns a list of readable error messages; empty list means valid."""
    schema = schema if schema is not None else load_schema()
    if _HAVE_JSONSCHEMA:
        return _validate_with_jsonschema(instance, schema)
    return _validate_with_minimal(instance, schema)


def validate_or_raise(instance: dict, schema: dict | None = None) -> None:
    errors = validate(instance, schema)
    if errors:
        raise SchemaValidationError("; ".join(errors))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 validate_parsed_intent.py file1.json [file2.json ...]")
        raise SystemExit(2)

    engine = "jsonschema" if _HAVE_JSONSCHEMA else "minimal fallback (offline sandbox)"
    print(f"validation engine: {engine}\n")

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
