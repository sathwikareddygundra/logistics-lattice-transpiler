"""Versioned code-template library (T-50, T-54).

Every code fragment the generators emit lives here as a typed template with
an id and a version. Bumping a body without bumping its version fails
tests/test_cag_templates.py (the lock file records body hashes).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

LOCK_PATH = Path(__file__).with_name("templates.lock.json")


class TemplateNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Template:
    id: str
    version: int
    op: str
    target: str  # sql | python
    body: str
    dialect: str = "any"
    granularity: str = ""

    def render(self, **params: object) -> str:
        return self.body.format(**params)

    @property
    def body_hash(self) -> str:
        return hashlib.sha256(self.body.encode()).hexdigest()[:16]


def _t(id_: str, op: str, target: str, body: str, dialect: str = "any", gran: str = "") -> Template:
    return Template(id_, 1, op, target, body, dialect, gran)


_SQLITE_WEEK = "strftime('%Y-W%W', {col})"
_BUCKETS: list[Template] = [
    _t("bucket.sql.sqlite.day", "bucket", "sql", "strftime('%Y-%m-%d', {col})", "sqlite", "day"),
    _t("bucket.sql.sqlite.week", "bucket", "sql", _SQLITE_WEEK, "sqlite", "week"),
    _t("bucket.sql.sqlite.month", "bucket", "sql", "strftime('%Y-%m', {col})", "sqlite", "month"),
    _t(
        "bucket.sql.sqlite.quarter",
        "bucket",
        "sql",
        "(strftime('%Y', {col}) || '-Q' || ((CAST(strftime('%m', {col}) AS INTEGER) + 2) / 3))",
        "sqlite",
        "quarter",
    ),  # fmt: skip
    _t("bucket.sql.sqlite.year", "bucket", "sql", "strftime('%Y', {col})", "sqlite", "year"),
    _t("bucket.sql.duckdb.day", "bucket", "sql", "strftime({col}, '%Y-%m-%d')", "duckdb", "day"),
    _t("bucket.sql.duckdb.week", "bucket", "sql", "strftime({col}, '%Y-W%W')", "duckdb", "week"),
    _t("bucket.sql.duckdb.month", "bucket", "sql", "strftime({col}, '%Y-%m')", "duckdb", "month"),
    _t(
        "bucket.sql.duckdb.quarter",
        "bucket",
        "sql",
        "(strftime({col}, '%Y') || '-Q' || CAST(quarter({col}) AS VARCHAR))",
        "duckdb",
        "quarter",
    ),  # fmt: skip
    _t("bucket.sql.duckdb.year", "bucket", "sql", "strftime({col}, '%Y')", "duckdb", "year"),
    _t(
        "bucket.sql.postgres.day",
        "bucket",
        "sql",
        "to_char({col}, 'YYYY-MM-DD')",
        "postgres",
        "day",
    ),
    _t(
        "bucket.sql.postgres.week",
        "bucket",
        "sql",
        "(to_char({col}, 'YYYY') || '-W' || lpad((((CAST(extract(doy FROM {col}) AS INTEGER) - 1) "
        "+ 7 - ((CAST(extract(dow FROM {col}) AS INTEGER) + 6) % 7)) / 7)::text, 2, '0'))",
        "postgres",
        "week",
    ),  # fmt: skip
    _t(
        "bucket.sql.postgres.month",
        "bucket",
        "sql",
        "to_char({col}, 'YYYY-MM')",
        "postgres",
        "month",
    ),
    _t(
        "bucket.sql.postgres.quarter",
        "bucket",
        "sql",
        "(to_char({col}, 'YYYY') || '-Q' || CAST(extract(quarter FROM {col}) AS INTEGER)::text)",
        "postgres",
        "quarter",
    ),  # fmt: skip
    _t("bucket.sql.postgres.year", "bucket", "sql", "to_char({col}, 'YYYY')", "postgres", "year"),
    _t(
        "bucket.python.day",
        "bucket",
        "python",
        "pd.to_datetime({prev}[{col}]).dt.strftime('%Y-%m-%d')",
        gran="day",
    ),
    _t(
        "bucket.python.week",
        "bucket",
        "python",
        "pd.to_datetime({prev}[{col}]).dt.strftime('%Y-W%W')",
        gran="week",
    ),
    _t(
        "bucket.python.month",
        "bucket",
        "python",
        "pd.to_datetime({prev}[{col}]).dt.strftime('%Y-%m')",
        gran="month",
    ),
    _t(
        "bucket.python.quarter",
        "bucket",
        "python",
        "pd.to_datetime({prev}[{col}]).dt.year.astype(str) + '-Q' + "
        "pd.to_datetime({prev}[{col}]).dt.quarter.astype(str)",
        gran="quarter",
    ),  # fmt: skip
    _t(
        "bucket.python.year",
        "bucket",
        "python",
        "pd.to_datetime({prev}[{col}]).dt.strftime('%Y')",
        gran="year",
    ),
]

_STRUCTURE: list[Template] = [
    _t("select.sql", "select", "sql", "SELECT {columns} FROM {table}"),
    _t("filter.sql", "filter", "sql", "SELECT * FROM {prev} WHERE {column} {operator} {value}"),
    _t(
        "join.sql",
        "join",
        "sql",
        "SELECT {select_list} FROM {left} AS l {join_kw} JOIN {right} AS r ON l.{key} = r.{key}",
    ),  # fmt: skip
    _t("window.sql", "window", "sql", "SELECT *, {bucket} AS {alias} FROM {prev}"),
    _t("aggregate.sql", "aggregate", "sql", "SELECT {select_list} FROM {prev}{group_by}"),
    _t("output.sql", "output", "sql", "SELECT {columns} FROM {prev}{order_by}{limit}"),
    _t("select.py", "select", "python", '{var} = read_sql("SELECT {columns} FROM {table}")'),
    _t("filter.py", "filter", "python", "{var} = {prev}[{prev}[{column}] {operator} {value}]"),
    _t(
        "join.py",
        "join",
        "python",
        "{var} = {left}.merge({right}[{right_cols}], on={key}, how={how})",
    ),  # fmt: skip
    _t("window.py", "window", "python", "{var} = {prev}.assign({alias}={bucket})"),
    _t(
        "aggregate_group.py",
        "aggregate",
        "python",
        "{var} = {prev}.groupby({group}, as_index=False)[{metric}].{fn}()"
        ".rename(columns={{{metric}: {alias}}})",
    ),  # fmt: skip
    _t(
        "aggregate_scalar.py",
        "aggregate_scalar",
        "python",
        "{var} = pd.DataFrame({{{alias}: [{prev}[{metric}].{fn}()]}})",
    ),  # fmt: skip
    _t(
        "sort.py",
        "sort",
        "python",
        '{var} = {prev}.sort_values(by={by}, ascending={asc}, kind="stable")',
    ),
    _t("limit.py", "limit", "python", "{var} = {prev}.head({count})"),
    _t("output.py", "output", "python", "{var} = {prev}[{columns}].reset_index(drop=True)"),
    _t(
        "forecast.py",
        "forecast",
        "python",
        "{var} = _linear_forecast({prev}, {period}, {value}, {horizon})",
    ),
]

TEMPLATES: dict[str, Template] = {t.id: t for t in (*_BUCKETS, *_STRUCTURE)}


def select_template(op: str, target: str, dialect: str = "any", granularity: str = "") -> Template:
    """Exactly one template per (op, target[, dialect, granularity]); no silent fallback."""
    matches = [
        t
        for t in TEMPLATES.values()
        if t.op == op
        and t.target == target
        and t.granularity == granularity
        and (t.dialect == dialect or (t.dialect == "any" and op != "bucket"))
    ]
    if len(matches) != 1:
        raise TemplateNotFoundError(
            f"expected exactly one template for op={op!r} target={target!r} "
            f"dialect={dialect!r} granularity={granularity!r}, found {len(matches)}"
        )
    return matches[0]


def fingerprint() -> dict[str, dict[str, object]]:
    return {t.id: {"version": t.version, "hash": t.body_hash} for t in TEMPLATES.values()}


def write_lock() -> None:
    LOCK_PATH.write_text(json.dumps(fingerprint(), indent=1, sort_keys=True) + "\n")
