import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dag.model import allowed_node_type_values  # noqa: E402
from schemas.validate_dag import (  # noqa: E402
    SchemaValidationError,
    load_schema,
    validate,
    validate_or_raise,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "schemas" / "examples"

VALID_EXAMPLES = [
    "valid_dag_aggregation.json",
    "valid_dag_join.json",
    "valid_dag_rank.json",
]
MALFORMED_SCHEMA_EXAMPLE = "malformed_dag_bad_operator.json"
MALFORMED_STRUCTURAL_EXAMPLE = "malformed_dag_dangling_edge.json"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text())


class TestDagSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()

    def test_schema_declares_draft_2020_12(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_node_type_enum_matches_model(self):
        """T-13 depends on T-34: this is the drift guard that proves it.

        If someone adds a node type to dag/model.py and forgets to update
        the schema (or vice versa), this test fails loudly instead of the
        two silently drifting apart.
        """
        schema_values = set(self.schema["$defs"]["node"]["properties"]["node_type"]["enum"])
        model_values = set(allowed_node_type_values())
        self.assertEqual(schema_values, model_values)

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
        but is caught by T-34's structural checks on top of it."""
        instance = _load(MALFORMED_STRUCTURAL_EXAMPLE)
        errors = validate(instance, self.schema)
        self.assertTrue(errors, "dangling edge should have produced at least one error")
        self.assertTrue(any("does-not-exist" in e for e in errors))

    def test_dangling_edge_raises_with_message(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_or_raise(_load(MALFORMED_STRUCTURAL_EXAMPLE), self.schema)
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_missing_required_field_is_caught(self):
        broken = _load("valid_dag_aggregation.json")
        del broken["edges"]
        errors = validate(broken, self.schema)
        self.assertTrue(any("edges" in e for e in errors))

    def test_join_without_two_roled_edges_is_caught(self):
        broken = _load("valid_dag_join.json")
        del broken["edges"][1]["role"]  # src_tracking -> j1 loses its 'right' role
        errors = validate(broken, self.schema)
        self.assertTrue(any("left" in e and "right" in e for e in errors))

    def test_cycle_is_caught(self):
        broken = _load("valid_dag_aggregation.json")
        # n3 (aggregate) -> n2 (filter) is a back-edge that doesn't touch
        # source/output arity, isolating the cycle check from the others.
        broken["edges"].append({"from_node": "n3", "to_node": "n2"})
        errors = validate(broken, self.schema)
        self.assertTrue(any("cycle" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
