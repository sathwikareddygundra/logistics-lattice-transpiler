"""The three plant databases, built from the source CSVs.

Each invoice is assigned to one plant (invoice sequence number mod 3), so
the plants hold disjoint slices of the same logistics domain. They differ
in engine and physical table names; IR-level adapters (ir.adapters) hide
that from every later stage.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import duckdb
import pandas as pd

from plantdb.catalog import TABLES

DEFAULT_SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "source"
_CSV_FILES = {
    "dispatch": "Dispatch_Data.csv",
    "tracking": "Tracking_Data.csv",
    "turnaround_time": "Turn_Around_Time_Data.csv",
}


class Plant(StrEnum):
    MCW = "MCW"
    YCW = "YCW"
    VGU = "VGU"


class UnknownPlantError(KeyError):
    pass


@dataclass(frozen=True)
class PlantProfile:
    plant: Plant
    engine: str  # sqlite | duckdb
    dialect: str  # sqlglot dialect name
    table_names: dict[str, str]  # canonical table -> physical table


PROFILES: dict[Plant, PlantProfile] = {
    Plant.MCW: PlantProfile(Plant.MCW, "sqlite", "sqlite", {t: t for t in TABLES}),
    Plant.YCW: PlantProfile(
        Plant.YCW,
        "duckdb",
        "duckdb",
        {"dispatch": "ycw_dispatch", "tracking": "ycw_tracking", "turnaround_time": "ycw_tat"},
    ),
    Plant.VGU: PlantProfile(
        Plant.VGU,
        "sqlite",
        "sqlite",
        {"dispatch": "vgu_dispatch", "tracking": "vgu_tracking", "turnaround_time": "vgu_tat"},
    ),
}


def vgu_on_postgres() -> bool:
    """VGU runs on a real PostgreSQL server when LATTICE_VGU_ENGINE=postgres (needs
    LATTICE_PG_DSN; see scripts/local_postgres.sh). Default is SQLite: no server needed."""
    return os.environ.get("LATTICE_VGU_ENGINE") == "postgres"


def get_profile(plant: Plant | str) -> PlantProfile:
    try:
        p = Plant(plant)
    except ValueError:
        raise UnknownPlantError(
            f"unknown plant {plant!r}; known plants: {[x.value for x in Plant]}"
        ) from None
    if p is Plant.VGU and vgu_on_postgres():
        base = PROFILES[Plant.VGU]
        return PlantProfile(Plant.VGU, "postgres", "postgres", base.table_names)
    return PROFILES[p]


def readonly_dsn(owner_dsn: str) -> str:
    """Same server, the SELECT-only role used by the sandbox."""
    u = urlparse(owner_dsn)
    host = u.netloc.rsplit("@", 1)[-1]
    return urlunparse(u._replace(netloc=f"{PG_RO_ROLE}@{host}"))


PG_RO_ROLE = "lattice_ro"
_PG_TYPES = {"integer": "BIGINT", "float": "DOUBLE PRECISION", "string": "TEXT", "date": "DATE",
             "datetime": "TIMESTAMP", "boolean": "BOOLEAN"}  # fmt: skip


def _build_postgres(frames: dict[str, pd.DataFrame], physical: dict[str, str], dsn: str) -> str:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        for table, df in frames.items():
            name = physical[table]
            cols = ", ".join(f"{c} {_PG_TYPES[t.value]}" for c, t in TABLES[table].columns.items())
            conn.execute(f"DROP TABLE IF EXISTS {name}")
            conn.execute(f"CREATE TABLE {name} ({cols})")
            with conn.cursor() as cur, cur.copy(f"COPY {name} FROM STDIN") as cp:
                for row in df.itertuples(index=False):
                    cp.write_row(row)
        conn.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{PG_RO_ROLE}') "
            f"THEN CREATE ROLE {PG_RO_ROLE} LOGIN; END IF; END $$"
        )
        conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {PG_RO_ROLE}")
        conn.execute(f"ALTER ROLE {PG_RO_ROLE} SET default_transaction_read_only = on")
    return readonly_dsn(dsn)


def db_path(out_dir: Path | str, plant: Plant | str) -> Path:
    profile = get_profile(plant)
    ext = "duckdb" if profile.engine == "duckdb" else "sqlite"
    return Path(out_dir) / f"{profile.plant.value.lower()}.{ext}"


def plant_for_invoice(invoice_number: str) -> Plant:
    return list(Plant)[int(invoice_number.rsplit("-", 1)[-1]) % len(Plant)]


def _load_source(source_dir: Path) -> dict[str, pd.DataFrame]:
    frames = {}
    for table, filename in _CSV_FILES.items():
        df = pd.read_csv(source_dir / filename)
        df.columns = [c.lower() for c in df.columns]
        keep = list(TABLES[table].columns)
        frames[table] = df[keep]
    return frames


def build_plant_databases(
    out_dir: Path | str, source_dir: Path | str = DEFAULT_SOURCE_DIR
) -> dict[Plant, Path | str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = _load_source(Path(source_dir))
    paths: dict[Plant, Path | str] = {}
    for plant in PROFILES:
        profile = get_profile(plant)
        if profile.engine == "postgres":
            owner = os.environ["LATTICE_PG_DSN"]
            by_table = {
                t: df[df["invoice_number"].map(plant_for_invoice) == plant]
                for t, df in frames.items()
            }
            paths[plant] = _build_postgres(by_table, profile.table_names, owner)
            continue
        path = db_path(out_dir, plant)
        path.unlink(missing_ok=True)
        for table, df in frames.items():
            mine = df[df["invoice_number"].map(plant_for_invoice) == plant].copy()
            physical = profile.table_names[table]
            if profile.engine == "sqlite":
                conn = sqlite3.connect(path)
                mine.to_sql(physical, conn, index=False, if_exists="replace")
                conn.commit()
                conn.close()
            else:
                for col, typ in TABLES[table].columns.items():
                    if typ.value == "datetime":
                        mine[col] = pd.to_datetime(mine[col])
                dconn = duckdb.connect(str(path))
                dconn.register("src", mine)
                dconn.execute(f"CREATE TABLE {physical} AS SELECT * FROM src")
                dconn.close()
        paths[plant] = path
    return paths
