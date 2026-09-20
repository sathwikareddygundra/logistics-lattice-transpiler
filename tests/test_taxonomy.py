import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nlu.taxonomy import TAXONOMY, IntentType, allowed_intent_values, is_out_of_scope  # noqa: E402


class TestTaxonomy(unittest.TestCase):
    def test_every_intent_type_has_a_taxonomy_entry(self):
        self.assertEqual(set(TAXONOMY.keys()), set(IntentType))

    def test_every_real_category_has_at_least_three_examples(self):
        for intent, definition in TAXONOMY.items():
            if intent is IntentType.OUT_OF_SCOPE:
                continue
            self.assertGreaterEqual(
                len(definition.example_queries),
                3,
                msg=f"{intent} needs 3+ example queries",
            )

    def test_out_of_scope_bucket_exists_and_is_flagged(self):
        self.assertIn(IntentType.OUT_OF_SCOPE, TAXONOMY)
        self.assertTrue(is_out_of_scope(IntentType.OUT_OF_SCOPE))
        for intent in IntentType:
            if intent is not IntentType.OUT_OF_SCOPE:
                self.assertFalse(is_out_of_scope(intent))

    def test_allowed_intent_values_are_plain_strings(self):
        values = allowed_intent_values()
        self.assertEqual(len(values), len(IntentType))
        self.assertIn("out_of_scope", values)
        self.assertIn("aggregation", values)


if __name__ == "__main__":
    unittest.main()
