"""Canonical typed catalog (the logical schema every plant maps onto).

Column names are unique across tables except the join key
`invoice_number`, which every table carries (clean 1:1:1 join, see
docs/T-9). `dispatch_date` is owned by `dispatch` only (T-9 flag #1).
"""

from __future__ import annotations

from dataclasses import dataclass

from ir.grammar import IrType

SCHEMA_VERSION = "1.0.0"
JOIN_KEY = "invoice_number"


class UnknownTableError(KeyError):
    pass


class UnknownColumnError(KeyError):
    pass


@dataclass(frozen=True)
class TableDef:
    name: str
    columns: dict[str, IrType]
    row_count: int  # approximate, used by the cost model (T-43)


DISPATCH = TableDef(
    "dispatch",
    {
        "invoice_number": IrType.STRING,
        "dispatch_date": IrType.DATETIME,
        "origin_warehouse": IrType.STRING,
        "destination_city": IrType.STRING,
        "carrier": IrType.STRING,
        "shipment_weight_kg": IrType.FLOAT,
        "freight_cost_usd": IrType.FLOAT,
    },
    row_count=10_000,
)
TRACKING = TableDef(
    "tracking",
    {
        "invoice_number": IrType.STRING,
        "checkpoint_timestamp": IrType.DATETIME,
        "current_status": IrType.STRING,
        "last_known_location": IrType.STRING,
        "driver_id": IrType.STRING,
    },
    row_count=10_000,
)
TURNAROUND = TableDef(
    "turnaround_time",
    {
        "invoice_number": IrType.STRING,
        "promised_delivery_date": IrType.DATETIME,
        "actual_delivery_date": IrType.DATETIME,
        "loading_time_mins": IrType.INTEGER,
        "unloading_time_mins": IrType.INTEGER,
        "total_tat_hours": IrType.FLOAT,
        "sla_status": IrType.STRING,
    },
    row_count=10_000,
)

TABLES: dict[str, TableDef] = {t.name: t for t in (DISPATCH, TRACKING, TURNAROUND)}


def get_table(name: str) -> TableDef:
    try:
        return TABLES[name]
    except KeyError:
        raise UnknownTableError(f"unknown table {name!r}; known tables: {sorted(TABLES)}") from None


def column_type(table: str, column: str) -> IrType:
    try:
        return get_table(table).columns[column]
    except KeyError:
        raise UnknownColumnError(f"unknown column {table}.{column}") from None


def owner_table(column: str) -> str:
    """The table a (non-key) column belongs to."""
    if column == JOIN_KEY:
        return DISPATCH.name
    for table in TABLES.values():
        if column in table.columns:
            return table.name
    raise UnknownColumnError(f"unknown column {column!r}")


def tables_for_columns(columns: list[str]) -> list[str]:
    """Distinct owning tables, dispatch first (the join hub), then catalog order."""
    wanted = {owner_table(c) for c in columns if c != JOIN_KEY} or {DISPATCH.name}
    return [name for name in TABLES if name in wanted]
