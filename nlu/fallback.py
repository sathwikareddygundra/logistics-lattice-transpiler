"""Graceful decline for out-of-scope questions (T-24), with a reviewable log."""

from __future__ import annotations

import difflib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from nlu.taxonomy import TAXONOMY, IntentType

DEFAULT_LOG = Path("logs") / "fallbacks.jsonl"


@dataclass(frozen=True)
class Fallback:
    message: str
    suggestions: list[str]


def decline(query: str) -> Fallback:
    examples = [
        q
        for d in TAXONOMY.values()
        if d.intent_type is not IntentType.OUT_OF_SCOPE
        for q in d.example_queries
    ]
    suggestions = difflib.get_close_matches(query, examples, n=2, cutoff=0.0)
    return Fallback(
        "I can only answer questions about dispatch, tracking and turnaround data "
        "(totals, trends, rankings, comparisons, forecasts). Try rephrasing, for example:",
        suggestions,
    )


def log_fallback(query: str, trace_id: str, path: Path | str = DEFAULT_LOG) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps({"ts": time.time(), "trace_id": trace_id, "query": query}) + "\n")
