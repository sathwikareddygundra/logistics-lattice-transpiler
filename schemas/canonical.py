"""T-10: canonical schema model.

Unifies the three T-9 source extracts (dispatch, tracking, turnaround_time)
into typed domain models, joined by invoice_number, with the data-quality
issues flagged in T-9 resolved here rather than passed downstream.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Warehouse(StrEnum):
    CHICAGO = "Chicago_WH"
    COLUMBUS = "Columbus_WH"
    LOS_ANGELES = "LA_WH"
    ATLANTA = "Atlanta_WH"
    DALLAS = "Dallas_WH"


class Carrier(StrEnum):
    DHL = "DHL"
    JB_HUNT = "JB Hunt"
    FEDEX = "FedEx"
    XPO = "XPO Logistics"
    UPS = "UPS"


class ShipmentStatus(StrEnum):
    IN_TRANSIT = "In Transit"
    DELIVERED = "Delivered"
    CUSTOMS_HOLD = "Customs Hold"
    DELAYED = "Delayed"
    OUT_FOR_DELIVERY = "Out for Delivery"


class SlaStatus(StrEnum):
    ON_TIME = "On Time"
    DELAYED = "Delayed"


class Shipment(BaseModel):
    """Owns dispatch_date — the single source of truth for it.
    Resolves T-9 flag #1 (duplicated across two source files)."""

    invoice_number: str
    dispatch_date: datetime
    origin_warehouse: Warehouse
    destination_city: str
    carrier: Carrier
    shipment_weight_kg: float = Field(gt=0)
    freight_cost_usd: float = Field(ge=0)


class TrackingEvent(BaseModel):
    """hub_code / city split resolves T-9 flag #2 (Last_Known_Location
    mixed two value spaces in one column). Exactly one of the two is
    set per event — never both, never neither."""

    invoice_number: str
    checkpoint_timestamp: datetime
    status: ShipmentStatus
    hub_code: str | None = None
    city: str | None = None
    driver_id: str


class TurnaroundRecord(BaseModel):
    """dispatch_date intentionally omitted — see Shipment."""

    invoice_number: str
    promised_delivery_date: datetime
    actual_delivery_date: datetime
    loading_time_mins: int = Field(ge=0)
    unloading_time_mins: int = Field(ge=0)
    total_tat_hours: float = Field(ge=0)
    sla_status: SlaStatus
