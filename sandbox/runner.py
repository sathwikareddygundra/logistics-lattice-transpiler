"""Sandboxed execution (T-81..T-83).

* Read-only database access (SQLite `mode=ro` + `query_only`, DuckDB
  `read_only=True`): writes are structurally impossible.
* Static validation before anything runs (single SELECT; Python limited to
  `import pandas`, no file/exec/dunder access).
* Hard wall-clock timeout (SQL engine interrupt; subprocess kill for
  isolated Python) and a row cap that rejects rather than truncates.
"""

from __future__ import annotations

import ast
import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

from plantdb.plants import PlantProfile

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_ROWS = 10_000
ROOT = Path(__file__).resolve().parent.parent
_FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "getattr", "setattr",
    "delattr", "vars", "input", "breakpoint", "exit", "quit",
}  # fmt: skip
_SAFE_BUILTINS = (
    "len range float int str list dict min max sum round zip enumerate sorted abs isinstance "
    "tuple set bool"
).split()


class SandboxError(Exception):
    """`stage` is one of static_validation, timeout, row_limit, permission, execution."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message


# --- static validation -------------------------------------------------------
def validate_sql(sql: str, dialect: str = "sqlite") -> None:
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise SandboxError("static_validation", f"SQL does not parse: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise SandboxError("static_validation", "only a single SELECT statement is allowed")
    for bad in statements[0].find_all(exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create):
        raise SandboxError("static_validation", f"{type(bad).__name__} is not allowed")


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


# --- connections -------------------------------------------------------------
class _Conn:
    """Read-only connection with a deadline, exposing read_sql(sql) -> DataFrame."""

    def __init__(self, profile: PlantProfile, db_path: Path | str, timeout_s: float) -> None:
        self.profile = profile
        self._timer: threading.Timer | None = None
        if profile.engine == "sqlite":
            self.raw: Any = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            self.raw.execute("PRAGMA query_only = ON")
            deadline = time.monotonic() + timeout_s
            self.raw.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        elif profile.engine == "duckdb":
            self.raw = duckdb.connect(str(db_path), read_only=True)
            self._timer = threading.Timer(timeout_s, self.raw.interrupt)
            self._timer.start()
        elif profile.engine == "postgres":
            import psycopg

            self.raw = psycopg.connect(
                str(db_path), options=f"-c statement_timeout={int(timeout_s * 1000)}"
            )
            self.raw.read_only = True
        else:
            raise SandboxError("execution", f"unsupported engine {profile.engine!r}")

    def read_sql(self, sql: str) -> pd.DataFrame:
        if self.profile.engine == "duckdb":
            return self.raw.execute(sql).df()
        if self.profile.engine == "postgres":
            with self.raw.cursor() as cur:
                cur.execute(sql)
                cols = [d.name for d in cur.description]
                return pd.DataFrame(cur.fetchall(), columns=cols)
        return pd.read_sql_query(sql, self.raw)

    def close(self) -> None:
        if self._timer:
            self._timer.cancel()
        self.raw.close()


def _connect(profile: PlantProfile, db_path: Path | str, timeout_s: float) -> _Conn:
    try:
        return _Conn(profile, db_path, timeout_s)
    except SandboxError:
        raise
    except Exception as exc:
        raise SandboxError("execution", f"cannot open database: {exc}") from exc


def _classify(exc: Exception) -> SandboxError:
    text = str(exc)
    low = text.lower()
    if "interrupt" in low or "statement timeout" in low or "canceling statement" in low:
        return SandboxError("timeout", "query exceeded the time limit")
    if "readonly" in low or "read-only" in low or "read only" in low or "permission denied" in low:
        return SandboxError("permission", text)
    return SandboxError("execution", f"{type(exc).__name__}: {text}")


def _check_rows(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if len(df) > max_rows:
        raise SandboxError("row_limit", f"result has {len(df)} rows, limit is {max_rows}")
    return df


# --- execution ---------------------------------------------------------------
def run_sql(
    profile: PlantProfile,
    db_path: Path | str,
    sql: str,
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> pd.DataFrame:
    validate_sql(sql, profile.dialect)
    conn = _connect(profile, db_path, timeout_s)
    try:
        return _check_rows(conn.read_sql(sql), max_rows)
    except SandboxError:
        raise
    except Exception as exc:
        raise _classify(exc) from exc
    finally:
        conn.close()


def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
    if name != "pandas":
        raise ImportError(f"import of {name!r} is not allowed")
    return pd


def exec_python(code: str, read_sql: Any) -> pd.DataFrame:
    """Run generated code in a restricted namespace (shared by in-process and child modes)."""
    import builtins

    safe = {n: getattr(builtins, n) for n in _SAFE_BUILTINS}
    namespace: dict[str, Any] = {"__builtins__": {**safe, "__import__": _restricted_import}}
    exec(compile(code, "<generated>", "exec"), namespace)  # noqa: S102
    result = namespace["run"](read_sql)
    if not isinstance(result, pd.DataFrame):
        raise SandboxError("execution", "generated code did not return a DataFrame")
    return result


def run_python(
    profile: PlantProfile,
    db_path: Path | str,
    code: str,
    timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
    isolated: bool = False,
) -> pd.DataFrame:
    validate_python(code)
    if isolated:
        return _run_isolated(profile, db_path, code, timeout_s, max_rows)
    conn = _connect(profile, db_path, timeout_s)
    try:
        return _check_rows(exec_python(code, conn.read_sql), max_rows)
    except SandboxError:
        raise
    except Exception as exc:
        raise _classify(exc) from exc
    finally:
        conn.close()


_BOOTSTRAP = "import sys; sys.path.insert(0, sys.argv[1]); from sandbox.child import main; main()"


def _run_isolated(
    profile: PlantProfile, db_path: Path | str, code: str, timeout_s: float, max_rows: int
) -> pd.DataFrame:
    """Run in a separate process that is killed at the deadline."""
    payload = json.dumps(
        {"plant": profile.plant.value, "db_path": str(db_path), "code": code, "timeout": timeout_s}
    )
    try:
        done = subprocess.run(
            [sys.executable, "-E", "-c", _BOOTSTRAP, str(ROOT)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_s + 2,
        )
    except subprocess.TimeoutExpired:
        raise SandboxError(
            "timeout", "generated code exceeded the time limit and was killed"
        ) from None
    if done.returncode != 0:
        try:
            err = json.loads(done.stdout.strip().splitlines()[-1])
            raise SandboxError(err["stage"], err["message"])
        except (ValueError, KeyError, IndexError):
            raise SandboxError("execution", done.stderr.strip()[-500:] or "child failed") from None
    return _check_rows(pd.read_json(done.stdout, orient="split"), max_rows)
