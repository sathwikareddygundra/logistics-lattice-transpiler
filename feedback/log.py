"""Failure and retry log (T-93): structured, PII-safe, queryable by category."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from confirm.log import scrub
from feedback.diagnostics import Diagnostic

DEFAULT_LOG = Path("logs") / "failures.jsonl"


def record_failure(
    diag: Diagnostic, retry_outcome: str, attempts: int, path: Path | str = DEFAULT_LOG
) -> dict:
    row = {
        "ts": time.time(),
        "trace": hashlib.sha256(diag.trace_id.encode()).hexdigest()[:12],
        "category": diag.category.value,
        "stage": diag.stage,
        "plant": diag.plant,
        "node": diag.node,
        "message": scrub(diag.message)[:300],
        "query": scrub(diag.query),
        "retry_outcome": retry_outcome,  # recovered | gave_up | reopened_confirm | not_retried
        "attempts": attempts,
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def load(path: Path | str = DEFAULT_LOG) -> list[dict]:
    p = Path(path)
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def query(
    path: Path | str = DEFAULT_LOG, category: str | None = None, since: float | None = None
) -> list[dict]:
    return [
        r
        for r in load(path)
        if (category is None or r["category"] == category) and (since is None or r["ts"] >= since)
    ]


def count_by_category(path: Path | str = DEFAULT_LOG, since: float | None = None) -> dict[str, int]:
    """Answers 'what is our most common failure type?'"""
    return dict(Counter(r["category"] for r in query(path, since=since)).most_common())
