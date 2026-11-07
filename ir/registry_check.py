"""Validate IR against the live database schema, before any code is generated (T-59)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb

from ir.grammar import Ir, IrOp
from plantdb.plants import PlantProfile


class SchemaDriftError(ValueError):
    """A table/column the IR needs is missing from the real database."""

    stage = "schema_drift"

    def __init__(self, missing: list[str]) -> None:
        super().__init__("schema drift, missing: " + ", ".join(missing))
        self.missing = missing


class DatabaseUnavailableError(ValueError):
    """The database could not be opened or introspected (not drift: nothing to compare)."""

    stage = "execution"


def physical_columns(profile: PlantProfile, db_path: Path | str) -> dict[str, set[str]]:
    try:
        return _physical_columns(profile, db_path)
    except ValueError:
        raise
    except Exception as exc:
        raise DatabaseUnavailableError(
            f"cannot read schema of {profile.plant.value}: {exc}"
        ) from exc


def _physical_columns(profile: PlantProfile, db_path: Path | str) -> dict[str, set[str]]:
    if profile.engine == "sqlite":
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ]
            return {t: {r[1] for r in conn.execute(f"PRAGMA table_info('{t}')")} for t in tables}
        finally:
            conn.close()
    if profile.engine == "duckdb":
        dconn = duckdb.connect(str(db_path), read_only=True)
        try:
            rows = dconn.execute(
                "SELECT table_name, column_name FROM information_schema.columns"
            ).fetchall()
        finally:
            dconn.close()
        out: dict[str, set[str]] = {}
        for table, col in rows:
            out.setdefault(table, set()).add(col)
        return out
    if profile.engine == "postgres":
        import psycopg

        with psycopg.connect(str(db_path)) as pg:
            rows = pg.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            ).fetchall()
        out = {}
        for table, col in rows:
            out.setdefault(table, set()).add(col)
        return out
    raise ValueError(f"unsupported engine {profile.engine!r}")


def validate_against_database(ir: Ir, profile: PlantProfile, db_path: Path | str) -> None:
    """Raises SchemaDriftError naming every missing `table.column`."""
    actual = physical_columns(profile, db_path)
    missing: list[str] = []
    for node in ir.nodes:
        if node.op is not IrOp.SELECT:
            continue
        table = node.params["table"]
        if table not in actual:
            missing.append(table)
            continue
        missing += [
            f"{table}.{c['column']}"
            for c in node.params["columns"]
            if c["column"] not in actual[table]
        ]
    if missing:
        raise SchemaDriftError(sorted(set(missing)))
