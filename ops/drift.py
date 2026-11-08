"""Schema drift between production and staging databases (T-96)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ops.alerts import Alert

Fingerprint = dict[str, dict[str, str]]  # table -> column -> declared type


def schema_fingerprint(db_path: Path | str, engine: str) -> Fingerprint:
    if engine == "sqlite":
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in con.execute(
                    "select name from sqlite_master where type='table' "
                    "and name not like 'sqlite_%' order by name"
                )
            ]
            return {
                t: {r[1]: r[2].upper() for r in con.execute(f'pragma table_info("{t}")')}
                for t in tables
            }
        finally:
            con.close()
    if engine == "duckdb":
        import duckdb

        dcon = duckdb.connect(str(db_path), read_only=True)
        try:
            rows = dcon.execute(
                "select table_name, column_name, data_type from information_schema.columns "
                "where table_schema='main' order by table_name, ordinal_position"
            ).fetchall()
        finally:
            dcon.close()
        fp: Fingerprint = {}
        for t, c, ty in rows:
            fp.setdefault(t, {})[c] = str(ty).upper()
        return fp
    raise ValueError(f"unsupported engine {engine!r}; use 'sqlite' or 'duckdb'")


def fingerprint_hash(fp: Fingerprint) -> str:
    return hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()


@dataclass
class DriftResult:
    added: list[str] = field(default_factory=list)  # "table.column" present only in staging
    removed: list[str] = field(default_factory=list)  # present only in production
    changed: list[str] = field(default_factory=list)  # type differs
    changed_tables: set[str] = field(default_factory=set)
    exceeds_lag: bool = False

    @property
    def drifted(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def check_drift(prod: Fingerprint, staging: Fingerprint, max_lag: int = 0) -> DriftResult:
    """`max_lag` is how many tables may differ before it counts as too far behind."""
    r = DriftResult()
    for t in sorted(set(prod) | set(staging)):
        p, s = prod.get(t, {}), staging.get(t, {})
        for c in sorted(set(p) | set(s)):
            if c not in p:
                r.added.append(f"{t}.{c}")
            elif c not in s:
                r.removed.append(f"{t}.{c}")
            elif p[c] != s[c]:
                r.changed.append(f"{t}.{c}")
            else:
                continue
            r.changed_tables.add(t)
    r.exceeds_lag = len(r.changed_tables) > max_lag
    return r


def alert_on_drift(prod: Fingerprint, staging: Fingerprint, max_lag: int = 0) -> Alert | None:
    r = check_drift(prod, staging, max_lag)
    if not r.exceeds_lag:
        return None
    parts = [f"{len(r.changed_tables)} tables differ (allowed {max_lag})"]
    for label, items in (("added", r.added), ("removed", r.removed), ("changed", r.changed)):
        if items:
            parts.append(f"{label}: {', '.join(items)}")
    return Alert("SchemaDrift", "page", "; ".join(parts))
