from pathlib import Path

from schemas.loaders import (
    load_shipments,
    load_tracking_events,
    load_turnaround_records,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_all_shipments_validate() -> None:
    shipments = load_shipments(FIXTURES / "dispatch.csv")
    assert len(shipments) == 10000
    assert len({s.invoice_number for s in shipments}) == 10000


def test_all_tracking_events_validate() -> None:
    events = load_tracking_events(FIXTURES / "tracking.csv")
    assert len(events) == 10000
    for e in events:
        assert (e.hub_code is None) != (e.city is None)


def test_all_turnaround_records_validate() -> None:
    records = load_turnaround_records(FIXTURES / "turnaround_time.csv")
    assert len(records) == 10000


def test_join_key_consistent_across_sources() -> None:
    dispatch_ids = {s.invoice_number for s in load_shipments(FIXTURES / "dispatch.csv")}
    tracking_ids = {e.invoice_number for e in load_tracking_events(FIXTURES / "tracking.csv")}
    tat_ids = {r.invoice_number for r in load_turnaround_records(FIXTURES / "turnaround_time.csv")}
    assert dispatch_ids == tracking_ids == tat_ids
