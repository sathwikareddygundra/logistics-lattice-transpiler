"""Golden regression nets (T-40, T-62, T-68, T-74, T-80): every artifact is frozen in
tests/golden/ and compared exactly. Regenerate deliberately with scripts/update_golden.py."""

import json
from pathlib import Path

import pytest

from scripts.update_golden import ROOT, golden_files, golden_results
from tests.golden_queries import GOLDEN_QUERIES

EXPECTED = golden_files()


@pytest.mark.parametrize("rel", sorted(EXPECTED))
def test_generated_artifact_matches_golden(rel):
    path = ROOT / rel
    assert path.exists(), f"missing golden file {rel}; run scripts/update_golden.py"
    assert path.read_text() == EXPECTED[rel], f"{rel} drifted from its golden version"


def test_no_stale_golden_files():
    on_disk = {
        str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and p.suffix != ".pyc"
    }
    expected_results = {f"results/{g}.json" for g in GOLDEN_QUERIES}
    assert on_disk == set(EXPECTED) | expected_results


@pytest.mark.parametrize("gid", sorted(GOLDEN_QUERIES))
def test_execution_results_match_frozen_results(databases, gid):
    got = golden_results({k: v for k, v in databases.items()})[f"results/{gid}.json"]
    assert json.loads(got) == json.loads((ROOT / f"results/{gid}.json").read_text())


def test_golden_directory_layout():
    assert {p.name for p in Path(ROOT).iterdir() if p.is_dir()} == {
        "ast", "dag", "ir", "python", "results", "sql",
    }  # fmt: skip
