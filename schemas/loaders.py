"""CSV loaders for the canonical schema. Each function reads one T-9
source file and returns fully-validated pydantic models."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from schemas.canonical import (
    Carrier,
    Shipment,
    ShipmentStatus,
    SlaStatus,
    TrackingEvent,
    TurnaroundRecord,
    Warehouse,
)


def _split_location(raw: str) -> tuple[str | None, str | None]:
    """Tracking_Data.Last_Known_Location mixes hub codes (Hub_323) and
    city names (Phoenix) in one column. Verified against all 907 real
    distinct values: hub codes always start with 'Hub_', the remaining
    7 values are exact city names with no overlap or ambiguity."""
    if raw.startswith("Hub_"):
        return raw, None
    return None, raw


def load_shipments(path: Path) -> list[Shipment]:
    with path.open(newline="") as f:
        return [
            Shipment(
                invoice_number=row["Invoice_Number"],
                dispatch_date=datetime.fromisoformat(row["Dispatch_Date"]),
                origin_warehouse=Warehouse(row["Origin_Warehouse"]),
                destination_city=row["Destination_City"],
                carrier=Carrier(row["Carrier"]),
                shipment_weight_kg=float(row["Shipment_Weight_KG"]),
                freight_cost_usd=float(row["Freight_Cost_USD"]),
            )
            for row in csv.DictReader(f)
        ]


def load_tracking_events(path: Path) -> list[TrackingEvent]:
    events = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            hub_code, city = _split_location(row["Last_Known_Location"])
            events.append(
                TrackingEvent(
                    invoice_number=row["Invoice_Number"],
                    checkpoint_timestamp=datetime.fromisoformat(row["Checkpoint_Timestamp"]),
                    status=ShipmentStatus(row["Current_Status"]),
                    hub_code=hub_code,
                    city=city,
                    driver_id=row["Driver_ID"],
                )
            )
    return events


def load_turnaround_records(path: Path) -> list[TurnaroundRecord]:
    with path.open(newline="") as f:
        return [
            TurnaroundRecord(
                invoice_number=row["Invoice_Number"],
                promised_delivery_date=datetime.fromisoformat(row["Promised_Delivery_Date"]),
                actual_delivery_date=datetime.fromisoformat(row["Actual_Delivery_Date"]),
                loading_time_mins=int(row["Loading_Time_Mins"]),
                unloading_time_mins=int(row["Unloading_Time_Mins"]),
                total_tat_hours=float(row["Total_TAT_Hours"]),
                sla_status=SlaStatus(row["SLA_Status"]),
            )
            for row in csv.DictReader(f)
        ]
