"""Typed catalog of the synthetic plant tables.

The single source of column names and IR types for the pipeline (the
CAG schema lookup and IR lowering both read it). One table per plant for
now; each plant gets its own catalog entry as more plants are added.
"""

from __future__ import annotations

from dataclasses import dataclass

from ir.grammar import IrType


class UnknownTableError(KeyError):
    pass


class UnknownColumnError(KeyError):
    pass


@dataclass(frozen=True)
class TableDef:
    name: str
    columns: dict[str, IrType]


DISPATCH = TableDef(
    name="dispatch",
    columns={
        "invoice_number": IrType.INTEGER,
        "dispatch_date": IrType.DATE,
        "plant": IrType.STRING,
        "destination": IrType.STRING,
        "carrier": IrType.STRING,
        "product": IrType.STRING,
        "weight_tons": IrType.FLOAT,
        "freight_cost": IrType.FLOAT,
    },
)

_TABLES: dict[str, TableDef] = {DISPATCH.name: DISPATCH}


def get_table(name: str) -> TableDef:
    try:
        return _TABLES[name]
    except KeyError:
        raise UnknownTableError(
            f"unknown table {name!r}; known tables: {sorted(_TABLES)}"
        ) from None


def column_type(table: str, column: str) -> IrType:
    cols = get_table(table).columns
    try:
        return cols[column]
    except KeyError:
        raise UnknownColumnError(f"unknown column {table}.{column}") from None
