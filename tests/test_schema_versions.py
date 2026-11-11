"""
T-16 acceptance test: every schema file has a version field.

Glob-based rather than a hardcoded file list, so this test automatically
covers new schema files (and T-12's parsed_intent.schema.json, once its
branch merges) without needing an update every time a schema is added --
the whole point of a versioning policy is that it doesn't get forgotten.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _schema_files() -> list[Path]:
    return sorted(SCHEMAS_DIR.glob("*.schema.json"))


class TestSchemaVersions(unittest.TestCase):
    def test_at_least_one_schema_exists(self):
        # Guards against this test silently passing on an empty glob.
        self.assertTrue(_schema_files(), "expected at least one schemas/*.schema.json file")

    def test_every_schema_has_a_required_versioned_field(self):
        for path in _schema_files():
            with self.subTest(schema=path.name):
                doc = json.loads(path.read_text())
                properties = doc.get("properties", {})
                self.assertIn(
                    "schema_version",
                    properties,
                    f"{path.name} has no top-level 'schema_version' property",
                )
                self.assertIn(
                    "schema_version",
                    doc.get("required", []),
                    f"{path.name}'s schema_version is not in 'required'",
                )

    def test_every_schema_version_is_a_pinned_semver_string(self):
        for path in _schema_files():
            with self.subTest(schema=path.name):
                doc = json.loads(path.read_text())
                version_field = doc["properties"]["schema_version"]
                self.assertEqual(version_field.get("type"), "string")
                const_value = version_field.get("const")
                self.assertIsNotNone(
                    const_value,
                    f"{path.name}'s schema_version should pin an exact version via 'const'",
                )
                self.assertRegex(
                    const_value,
                    SEMVER_RE,
                    f"{path.name}'s schema_version {const_value!r} is not MAJOR.MINOR.PATCH",
                )


if __name__ == "__main__":
    unittest.main()
