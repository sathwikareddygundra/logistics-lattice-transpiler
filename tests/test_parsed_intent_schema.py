import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nlu.taxonomy import allowed_intent_values  # noqa: E402
from schemas.validate_parsed_intent import (  # noqa: E402
    SchemaValidationError,
    load_schema,
    validate,
    validate_or_raise,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "schemas" / "examples"

VALID_EXAMPLES = [
    "valid_aggregation.json",
    "valid_join_multiplant.json",
    "valid_out_of_scope.json",
]
MALFORMED_EXAMPLE = "malformed_bad_entity_type.json"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text())


class TestParsedIntentSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()

    def test_schema_declares_draft_2020_12(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_intent_enum_matches_taxonomy(self):
        """T-12 depends on T-17: this is the drift guard that proves it.

        If someone adds an intent to nlu/taxonomy.py and forgets to update
        the schema (or vice versa), this test fails loudly instead of the
        two silently drifting apart.
        """
        schema_values = set(self.schema["properties"]["intent_type"]["enum"])
        taxonomy_values = set(allowed_intent_values())
        self.assertEqual(schema_values, taxonomy_values)

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

    def test_malformed_example_fails_with_readable_error(self):
        instance = _load(MALFORMED_EXAMPLE)
        errors = validate(instance, self.schema)
        self.assertTrue(errors, "malformed example should have produced at least one error")

        # "readable" == it names the offending field and the bad value,
        # not just "invalid document".
        combined = " ".join(errors)
        self.assertIn("entity_type", combined)
        self.assertIn("date", combined)

    def test_malformed_example_raises_with_message(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            validate_or_raise(_load(MALFORMED_EXAMPLE), self.schema)
        self.assertIn("entity_type", str(ctx.exception))

    def test_missing_required_field_is_caught(self):
        broken = _load("valid_aggregation.json")
        del broken["confidence"]
        errors = validate(broken, self.schema)
        self.assertTrue(any("confidence" in e for e in errors))

    def test_out_of_range_confidence_is_caught(self):
        broken = _load("valid_aggregation.json")
        broken["confidence"]["overall"] = 1.5
        errors = validate(broken, self.schema)
        self.assertTrue(any("overall" in e or "1.5" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
