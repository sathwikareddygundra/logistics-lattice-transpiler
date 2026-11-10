import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))

import server  # noqa: E402


def test_every_example_chip_returns_an_answer(databases):
    html = (ROOT / "ui/index.html").read_text()
    examples = json.loads(re.search(r"const EXAMPLES = (\[.*?\]);", html).group(1))
    assert examples
    for q in examples:
        out = server.run_query(q, databases, confirmed=False)
        assert out["status"] == "ok", (q, out["status"], out["message"])
        assert out["table"]["data"], q
