"""PII-safe interaction log and fine-tuning export (T-33)."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from nlu.intent import ParsedIntent

DEFAULT_LOG = Path("logs") / "confirm_interactions.jsonl"
_PII = [
    (re.compile(r"INV-\d{4}-\d{5}"), "<INVOICE>"),
    (re.compile(r"DRV-\d+"), "<DRIVER>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<EMAIL>"),
    (re.compile(r"\+?\d[\d\s().-]{8,}\d"), "<PHONE>"),
]


def scrub(text: str) -> str:
    for pattern, token in _PII:
        text = pattern.sub(token, text)
    return text


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _summary(intent: ParsedIntent) -> dict:
    data = intent.model_dump(mode="json", exclude_defaults=True)
    for key in ("query", "entity_confidence", "missing_slots"):
        data.pop(key, None)
    return data


def record(
    trace_id: str,
    query: str,
    paraphrase: str,
    verdict: str,
    correction: str,
    final_intent: ParsedIntent | None,
    path: Path | str = DEFAULT_LOG,
) -> dict:
    row = {
        "ts": time.time(),
        "trace": _hash(trace_id),
        "query": scrub(query),
        "paraphrase": scrub(paraphrase),
        "verdict": verdict,
        "correction": scrub(correction),
        "final_intent": _summary(final_intent) if final_intent else None,
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def export_finetune(log_path: Path | str, out_path: Path | str) -> int:
    """Chat-format JSONL (one example per accepted or corrected interaction)."""
    n = 0
    with Path(out_path).open("w") as out:
        for line in Path(log_path).read_text().splitlines():
            row = json.loads(line)
            if row["final_intent"] is None or row["verdict"] not in ("yes", "no"):
                continue
            example = {
                "messages": [
                    {"role": "user", "content": row["query"]},
                    {
                        "role": "assistant",
                        "content": json.dumps(row["final_intent"], sort_keys=True),
                    },
                ]
            }
            out.write(json.dumps(example) + "\n")
            n += 1
    return n
