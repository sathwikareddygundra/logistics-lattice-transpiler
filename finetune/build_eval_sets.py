"""Write finetune/data/eval_labeled.jsonl: the hand-labeled queries in the model's prompt format.

Gold here is the entity list of nlu/data/labeled_queries.jsonl. It is a weaker check than the
validation set (same author as the parser), so read it as a sanity check, not as accuracy.
Questions from people go in finetune/data/human_test.jsonl as {"query": ..., "intent": ...}
and are written to eval_human.jsonl the same way (not used for training).
Run: uv run python finetune/build_eval_sets.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from build_dataset import system_prompt  # noqa: E402

DATA = Path(__file__).parent / "data"
TODAY = date(2026, 9, 15)


def convert(src: Path, dst: Path) -> int:
    rows = [json.loads(line) for line in src.read_text().splitlines() if line.strip()]
    out = []
    for r in rows:
        out.append(
            {
                "messages": [
                    {"role": "system", "content": system_prompt(TODAY)},
                    {"role": "user", "content": r["query"]},
                ],
                "gold": {"intent": r["intent"], "entities": r.get("entities")},
                "meta": {"today": TODAY.isoformat()},
            }
        )
    dst.write_text("".join(json.dumps(r) + "\n" for r in out))
    return len(out)


def main() -> None:
    print("labeled:", convert(ROOT / "nlu/data/labeled_queries.jsonl", DATA / "eval_labeled.jsonl"))
    human = DATA / "human_test.jsonl"
    if human.exists():
        print("human:", convert(human, DATA / "eval_human.jsonl"))


if __name__ == "__main__":
    main()
