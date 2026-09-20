import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ir.grammar import allowed_ir_op_values  # noqa: E402
from schemas.validate_ir import (  # noqa: E402
    SchemaValidationError,
    load_schema,
    validate,
    validate_or_raise,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "schemas" / "examples"

VALID_EXAMPLES = [
    "valid_ir_aggregation.json",
    "valid_ir_join.json",
    "valid_ir_rank.json",
]
MALFORMED_SCHEMA_EXAMPLE = "malformed_ir_bad_operator.json"
MALFORMED_STRUCTURAL_EXAMPLE = "malformed_ir_dangling_edge.json"
MALFORMED_UNSUPPORTED_OP_EXAMPLE = "malformed_ir_unsupported_op.json"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text())


class TestIrSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()

    def test_schema_declares_draft_2020_12(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_op_enum_matches_grammar(self):
        """T-14 depends on T-56: this is the drift guard that proves it.

        If someone adds an op to ir/grammar.py and forgets to update the
        schema (or vice versa), this test fails loudly instead of the two
        silently drifting apart.
        """
        schema_values = set(self.schema["$defs"]["node"]["properties"]["op"]["enum"])
        grammar_values = set(allowed_ir_op_values())
        self.assertEqual(schema_values, grammar_values)

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

    def test_dangling_edge_fails_with_readable_error(self):
        """Passes the JSON Schema layer (both endpoints are plain strings)
        but is caught by T-56's structural checks on top of it."""
        instance = _load(MALFORMED_STRUCTURAL_EXAMPLE)
        errors = validate(instance, self.schema)
        self.assertTrue(errors, "dangling edge should have produced at least one error")
        self.assertTrue(any("does-not-exist" in e for e in errors))

    def test_dangling_edge_raises_with_message(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_or_raise(_load(MALFORMED_STRUCTURAL_EXAMPLE), self.schema)
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_invented_unsupported_operation_is_rejected(self):
        """T-14's explicit acceptance criterion: an invented op is rejected."""
        instance = _load(MALFORMED_UNSUPPORTED_OP_EXAMPLE)
        errors = validate(instance, self.schema)
        self.assertTrue(errors, "an unsupported op should have produced at least one error")
        self.assertTrue(any("transform" in e for e in errors))

    def test_missing_required_field_is_caught(self):
        broken = _load("valid_ir_aggregation.json")
        del broken["edges"]
        errors = validate(broken, self.schema)
        self.assertTrue(any("edges" in e for e in errors))

    def test_join_key_type_mismatch_is_caught(self):
        broken = _load("valid_ir_join.json")
        broken["nodes"][1]["params"]["columns"][0]["type"] = "integer"
        broken["nodes"][2]["params"]["right_key"]["type"] = "integer"
        errors = validate(broken, self.schema)
        self.assertTrue(any("type mismatch" in e for e in errors))

    def test_aggregate_result_type_mismatch_is_caught(self):
        broken = _load("valid_ir_aggregation.json")
        broken["nodes"][2]["params"]["op"] = "count"
        # result_type is still "float" from the fixture, but count needs integer.
        errors = validate(broken, self.schema)
        self.assertTrue(any("result_type" in e for e in errors))

    def test_cycle_is_caught(self):
        broken = _load("valid_ir_aggregation.json")
        broken["edges"].append({"from_node": "n3", "to_node": "n2"})
        errors = validate(broken, self.schema)
        self.assertTrue(any("cycle" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
