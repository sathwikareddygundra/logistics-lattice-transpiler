"""Entity vocabulary (valid values per column), read once from the source CSVs."""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from plantdb.plants import _CSV_FILES, DEFAULT_SOURCE_DIR

_VALUE_COLUMNS = {
    "origin_warehouse": "dispatch",
    "destination_city": "dispatch",
    "carrier": "dispatch",
    "current_status": "tracking",
    "sla_status": "turnaround_time",
}


@lru_cache(maxsize=1)
def column_values() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for column, table in _VALUE_COLUMNS.items():
        df = pd.read_csv(DEFAULT_SOURCE_DIR / _CSV_FILES[table])
        df.columns = [c.lower() for c in df.columns]
        out[column] = tuple(sorted(df[column].dropna().unique()))
    return out


@lru_cache(maxsize=1)
def date_span() -> tuple[str, str]:
    df = pd.read_csv(DEFAULT_SOURCE_DIR / _CSV_FILES["dispatch"])
    col = df["Dispatch_Date"].astype(str)
    return col.min()[:10], col.max()[:10]
