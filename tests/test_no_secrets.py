"""T-5/T-8: no API keys or secrets are committed anywhere in the repository."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),  # Groq keys
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access keys
    re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
]


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / p for p in out.stdout.splitlines() if (ROOT / p).is_file()]


def test_no_tracked_file_contains_a_secret():
    hits = []
    for path in _tracked_files():
        if path.suffix in {".csv", ".lock", ".png", ".pyc"}:
            continue
        text = path.read_text(errors="ignore")
        hits += [f"{path.relative_to(ROOT)}: {p.pattern}" for p in PATTERNS if p.search(text)]
    assert hits == []


def test_env_files_other_than_the_example_are_not_tracked():
    tracked = {p.name for p in _tracked_files()}
    assert not {n for n in tracked if n.startswith(".env") and n != ".env.example"}


def test_groq_key_comes_only_from_the_environment():
    src = (ROOT / "common" / "groq_client.py").read_text()
    assert 'os.environ.get("GROQ_API_KEY")' in src and "gsk_" not in src
