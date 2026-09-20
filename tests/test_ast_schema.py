import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ast_.nodes import allowed_ast_op_values  # noqa: E402
from schemas.validate_ast import (  # noqa: E402
    SchemaValidationError,
    load_schema,
    validate,
    validate_or_raise,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "schemas" / "examples"

VALID_EXAMPLES = [
    "valid_ast_python_aggregation.json",
    "valid_ast_sql_aggregation.json",
    "valid_ast_sql_join.json",
]
MALFORMED_SCHEMA_EXAMPLE = "malformed_ast_bad_operator.json"
MALFORMED_STRUCTURAL_EXAMPLE = "malformed_ast_duplicate_var.json"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text())


class TestAstSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()

    def test_schema_declares_draft_2020_12(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_op_enum_matches_nodes(self):
        """T-15 depends on T-63: this is the drift guard that proves it.

        If someone adds an op to ast_/nodes.py (or the IR vocabulary it
        reuses) and forgets to update the schema, this test fails loudly
        instead of the two silently drifting apart.
        """
        schema_values = set(self.schema["$defs"]["node"]["properties"]["op"]["enum"])
        node_values = set(allowed_ast_op_values())
        self.assertEqual(schema_values, node_values)

    def test_target_enum_covers_both_codegen_passes(self):
        self.assertEqual(set(self.schema["properties"]["target"]["enum"]), {"python", "sql"})

    def test_valid_examples_pass_validation(self):
        for name in VALID_EXAMPLES:
            with self.subTest(example=name):
                instance = _load(name)
                errors = validate(instance, self.schema)
                self.assertEqual(errors, [], f"{name} should be valid but got: {errors}")

    def test_valid_examples_do_not_raise(self):
        for name in VALID_EXAMPLES:
            with self.subTest(example=name):
                validate_or_raise(_load(name), self.schema)  # should not raise

    def test_schema_is_expressive_enough_for_both_targets(self):
        """T-15's explicit acceptance criterion: the same schema must
        validate equivalent Python- and SQL-target documents without
        workarounds -- proven here by two examples with identical node
        shapes differing only in `target`."""
        python_doc = _load("valid_ast_python_aggregation.json")
        sql_doc = _load("valid_ast_sql_aggregation.json")
        self.assertEqual(validate(python_doc, self.schema), [])
        self.assertEqual(validate(sql_doc, self.schema), [])
        self.assertEqual(
            [n["op"] for n in python_doc["nodes"]],
            [n["op"] for n in sql_doc["nodes"]],
        )

    def test_malformed_operator_fails_with_readable_error(self):
        """Caught by the JSON Schema layer (operator isn't in the enum)."""
        instance = _load(MALFORMED_SCHEMA_EXAMPLE)
        errors = validate(instance, self.schema)
        self.assertTrue(errors, "malformed example should have produced at least one error")

        combined = " ".join(errors)
        self.assertIn("operator", combined)
        self.assertIn("before", combined)

    def test_malformed_operator_raises_with_message(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_or_raise(_load(MALFORMED_SCHEMA_EXAMPLE), self.schema)
        self.assertIn("operator", str(ctx.exception))

    def test_duplicate_var_fails_with_readable_error(self):
        """Passes the JSON Schema layer (var is just a non-empty string)
        but is caught by T-63's structural checks -- the language-shaped
        invariant IR doesn't need (IR has no notion of named bindings)."""
        instance = _load(MALFORMED_STRUCTURAL_EXAMPLE)
        errors = validate(instance, self.schema)
        self.assertTrue(errors, "duplicate var binding should have produced at least one error")
        self.assertTrue(any("duplicate var binding" in e for e in errors))

    def test_duplicate_var_raises_with_message(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_or_raise(_load(MALFORMED_STRUCTURAL_EXAMPLE), self.schema)
        self.assertIn("duplicate var binding", str(ctx.exception))

    def test_missing_required_field_is_caught(self):
        broken = _load("valid_ast_python_aggregation.json")
        del broken["target"]
        errors = validate(broken, self.schema)
        self.assertTrue(any("target" in e for e in errors))

    def test_unknown_target_is_caught(self):
        broken = _load("valid_ast_python_aggregation.json")
        broken["target"] = "rust"
        errors = validate(broken, self.schema)
        self.assertTrue(any("rust" in e for e in errors))

    def test_cycle_is_caught(self):
        broken = _load("valid_ast_python_aggregation.json")
        broken["edges"].append({"from_node": "n3", "to_node": "n2"})
        errors = validate(broken, self.schema)
        self.assertTrue(any("cycle" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
