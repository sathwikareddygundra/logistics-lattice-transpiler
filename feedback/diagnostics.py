"""Structured error diagnostics (T-84): every failure becomes a machine-readable object, so the
retry router never has to re-parse error text."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from feedback.taxonomy import FailureCategory, classify


@dataclass(frozen=True)
class Diagnostic:
    stage: str  # lowering | codegen | sandbox | validation
    category: FailureCategory
    node: str | None
    message: str
    query: str
    trace_id: str
    plant: str = ""

    def to_dict(self) -> dict[str, str | None]:
        d = asdict(self)
        d["category"] = self.category.value
        return d


_NODE = re.compile(r"\bnode\s+'?(n\d+)'?", re.IGNORECASE)


def diagnose(
    exc: BaseException, query: str, trace_id: str, stage: str, plant: str = ""
) -> Diagnostic:
    msg = str(getattr(exc, "message", None) or exc)
    m = _NODE.search(msg)
    return Diagnostic(stage, classify(exc), m.group(1) if m else None, msg, query, trace_id, plant)
