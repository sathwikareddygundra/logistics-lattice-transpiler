"""Result-shape validation (T-85): compare what actually came back with what the plan promised."""

from __future__ import annotations

import pandas as pd

from ast_.nodes import AstDocument, AstOp
from plantdb.catalog import TABLES


class ResultShapeError(ValueError):
    stage = "semantic_mismatch"


def _kind(ir_type: str) -> str:
    return {"integer": "number", "float": "number", "datetime": "time", "date": "time"}.get(
        ir_type, "text"
    )


def expected_shape(doc: AstDocument) -> tuple[list[tuple[str, str]], int | None, int | None]:
    """(ordered (column, kind) pairs, min rows, max rows) the output node promises."""
    by_id = {n.id: n for n in doc.nodes}
    agg = next((n for n in doc.nodes if n.op is AstOp.AGGREGATE), None)
    alias_kind: dict[str, str] = {}
    scalar = False
    if agg is not None:
        p = agg.params
        alias = f"{p['op']}_{p['metric']['column']}"
        alias_kind[p["metric"]["column"]] = _kind(p["result_type"])
        alias_kind[alias] = _kind(p["result_type"])
        scalar = not p["group_by"]
    derived = {
        f"{n.params['column']['column']}_{n.params['granularity']}"
        for n in doc.nodes
        if n.op is AstOp.WINDOW
    }
    out = next(n for n in doc.nodes if n.op is AstOp.OUTPUT)
    cols: list[tuple[str, str]] = []
    for c in out.params["columns"]:
        name = c["column"]
        if name in derived:
            cols.append((name, "text"))
        elif name in alias_kind and agg is not None:
            alias = f"{agg.params['op']}_{name}"
            cols.append((alias, alias_kind[name]))
        else:
            cols.append((name, _kind(TABLES[c["table"]].columns[name].value)))
    limit = next((n.params["count"] for n in doc.nodes if n.op is AstOp.LIMIT), None)
    has_forecast = any(n.op is AstOp.FORECAST for n in by_id.values())
    if has_forecast:
        cols.append(("kind", "text"))
    exact = 1 if scalar else None
    return cols, exact, limit


def check_result(frame: pd.DataFrame, doc: AstDocument) -> None:
    """Raises ResultShapeError naming the extra, missing or mistyped column."""
    cols, exact, limit = expected_shape(doc)
    want = [c for c, _ in cols]
    got = list(frame.columns)
    if got != want:
        missing, extra = [c for c in want if c not in got], [c for c in got if c not in want]
        detail = []
        if missing:
            detail.append(f"missing {missing}")
        if extra:
            detail.append(f"unexpected {extra}")
        if not detail:
            detail.append(f"order is {got}, expected {want}")
        raise ResultShapeError("result columns do not match the plan: " + "; ".join(detail))
    for name, kind in cols:
        s = frame[name]
        if len(s) and kind == "number" and not pd.api.types.is_numeric_dtype(s):
            raise ResultShapeError(f"column {name!r} should be numeric but is {s.dtype}")
        if len(s) and kind == "text" and pd.api.types.is_numeric_dtype(s):
            raise ResultShapeError(f"column {name!r} should be text but is {s.dtype}")
    if exact is not None and len(frame) != exact:
        raise ResultShapeError(f"an ungrouped aggregate must return {exact} row, got {len(frame)}")
    if limit is not None and len(frame) > limit:
        raise ResultShapeError(f"result has {len(frame)} rows but the plan limits it to {limit}")
