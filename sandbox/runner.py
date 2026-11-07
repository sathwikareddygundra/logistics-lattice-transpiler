"""Sandboxed execution (T-81..T-83, slice version).

Read-only SQLite connection, static validation before running, a hard
timeout and a row cap that rejects (never silently truncates). Python
code runs with a minimal builtins table and may only import pandas.

Known limit: Python execution is restricted by static checks and empty
builtins, not by an OS-level process sandbox. Full isolation is a later
hardening step.
"""

from __future__ import annotations

import ast
import sqlite3
import time
from pathlib import Path
from typing import Any

import pandas as pd
import sqlglot
from sqlglot import exp

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_ROWS = 10_000
_FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals",
    "getattr", "setattr", "delattr", "vars", "input", "breakpoint",
}  # fmt: skip


class SandboxError(Exception):
    """Structured failure: `stage` is one of static_validation, timeout,
    row_limit, execution."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message


def _connect(db_path: Path | str, timeout_s: float) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    deadline = time.monotonic() + timeout_s

    def _expired() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(_expired, 1000)
    return conn


def validate_sql(sql: str) -> None:
    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except sqlglot.errors.ParseError as exc:
        raise SandboxError("static_validation", f"SQL does not parse: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise SandboxError("static_validation", "only a single SELECT statement is allowed")


def validate_python(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxError("static_validation", f"Python does not parse: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name != "pandas" for a in node.names):
            raise SandboxError("static_validation", "only `import pandas` is allowed")
        if isinstance(node, ast.ImportFrom):
            raise SandboxError("static_validation", "`from ... import` is not allowed")
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise SandboxError("static_validation", f"use of {node.id!r} is not allowed")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise SandboxError("static_validation", f"dunder access {node.attr!r} is not allowed")


def _check_rows(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if len(df) > max_rows:
        raise SandboxError("row_limit", f"result has {len(df)} rows, limit is {max_rows}")
    return df


def run_sql(
    db_path: Path | str,
    sql: str,
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> pd.DataFrame:
    validate_sql(sql)
    conn = _connect(db_path, timeout_s)
    try:
        return _check_rows(pd.read_sql_query(sql, conn), max_rows)
    except sqlite3.OperationalError as exc:
        stage = "timeout" if "interrupted" in str(exc) else "execution"
        raise SandboxError(stage, str(exc)) from exc
    except pd.errors.DatabaseError as exc:
        stage = "timeout" if "interrupted" in str(exc) else "execution"
        raise SandboxError(stage, str(exc)) from exc
    finally:
        conn.close()


def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
    if name != "pandas":
        raise ImportError(f"import of {name!r} is not allowed")
    return pd


def run_python(
    db_path: Path | str,
    code: str,
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> pd.DataFrame:
    validate_python(code)
    namespace: dict[str, Any] = {"__builtins__": {"__import__": _restricted_import, "len": len}}
    conn = _connect(db_path, timeout_s)
    try:
        exec(compile(code, "<generated>", "exec"), namespace)  # noqa: S102
        result = namespace["run"](conn)
        if not isinstance(result, pd.DataFrame):
            raise SandboxError("execution", "generated code did not return a DataFrame")
        return _check_rows(result, max_rows)
    except SandboxError:
        raise
    except Exception as exc:
        stage = "timeout" if "interrupted" in str(exc) else "execution"
        raise SandboxError(stage, f"{type(exc).__name__}: {exc}") from exc
    finally:
        conn.close()
