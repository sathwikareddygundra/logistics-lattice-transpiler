"""Deterministic synthetic data for the `dispatch` table (SQLite)."""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from plantdb.catalog import DISPATCH

PLANTS = ["MCW", "YCW", "VGU"]
DESTINATIONS = ["Hyderabad", "Chennai", "Bengaluru", "Pune", "Vijayawada", "Nagpur"]
CARRIERS = ["DHL", "JB Hunt", "Blue Dart", "Gati"]
PRODUCTS = ["OPC", "PPC", "Clinker", "Slag Cement"]
START = date(2026, 1, 1)
DAYS = 300

_SQLITE_TYPES = {"integer": "INTEGER", "float": "REAL", "string": "TEXT", "date": "TEXT"}


def build_rows(n: int = 2000, seed: int = 7) -> list[tuple]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        weight = round(rng.uniform(5, 60), 2)
        rows.append(
            (
                100000 + i,
                (START + timedelta(days=rng.randrange(DAYS))).isoformat(),
                rng.choice(PLANTS),
                rng.choice(DESTINATIONS),
                rng.choice(CARRIERS),
                rng.choice(PRODUCTS),
                weight,
                round(weight * rng.uniform(300, 900), 2),
            )
        )
    return rows


def create_database(path: Path | str, n: int = 2000, seed: int = 7) -> None:
    path = Path(path)
    path.unlink(missing_ok=True)
    cols = ", ".join(
        f"{name} {_SQLITE_TYPES[t.value]}" for name, t in DISPATCH.columns.items()
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"CREATE TABLE {DISPATCH.name} ({cols})")
        marks = ", ".join("?" * len(DISPATCH.columns))
        conn.executemany(f"INSERT INTO {DISPATCH.name} VALUES ({marks})", build_rows(n, seed))
        conn.commit()
    finally:
        conn.close()
