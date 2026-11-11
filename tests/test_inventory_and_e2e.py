"""T-9 inventory matches the live databases; T-94 end-to-end gate across all three plants."""

import json
from pathlib import Path

import pytest

from pipeline import answer
from plantdb.plants import Plant, plant_for_invoice
from scripts.build_inventory import build
from tests.conftest import TODAY
from tests.golden_queries import GOLDEN_QUERIES

ROOT = Path(__file__).resolve().parent.parent


def test_inventory_files_match_the_real_databases():
    live = build()
    for plant, doc in live.items():
        stored = json.loads((ROOT / "schemas" / "inventory" / f"{plant}.json").read_text())
        assert stored == doc, f"{plant} inventory is stale; run scripts/build_inventory.py"


def test_inventory_lists_every_table_column_type_and_known_gaps():
    for plant in Plant:
        doc = json.loads((ROOT / "schemas" / "inventory" / f"{plant.value}.json").read_text())
        assert len(doc["tables"]) == 3 and doc["known_gaps"]
        for t in doc["tables"].values():
            assert t["rows"] > 3000 and t["columns"] and len(t["sample"]) == 3
            assert all(c["type"] for c in t["columns"])


def test_plants_partition_the_invoices_with_no_overlap(truth):
    parts = truth.invoice_number.map(plant_for_invoice)
    assert set(parts) == set(Plant) and parts.value_counts().min() > 3000


@pytest.mark.parametrize("gid,query", sorted(GOLDEN_QUERIES.items()))
def test_every_golden_query_works_end_to_end_for_each_plant_and_all_together(databases, gid, query):
    allp = answer(query, databases, today=TODAY, confirmed=True)
    assert allp.status == "ok", allp.message
    for plant in Plant:
        scoped = answer(f"{query} for {plant.value}", databases, today=TODAY, confirmed=True)
        assert scoped.status == "ok", (plant, scoped.message)
        assert scoped.frame is not None and len(scoped.frame) > 0


@pytest.mark.parametrize(
    "q,col",
    [
        ("total freight cost", "sum_freight_cost_usd"),
        ("how many shipments", "count_invoice_number"),
        ("total weight", "sum_shipment_weight_kg"),
    ],
)
def test_additive_answers_equal_the_sum_of_the_plants(databases, truth, q, col):
    total = answer(q, databases, today=TODAY).frame.iloc[0][col]
    per_plant = [
        answer(f"{q} for {p.value}", databases, today=TODAY).frame.iloc[0][col] for p in Plant
    ]
    assert sum(per_plant) == pytest.approx(total)
    full = {"sum_freight_cost_usd": truth.freight_cost_usd.sum(), "count_invoice_number": len(truth),
            "sum_shipment_weight_kg": truth.shipment_weight_kg.sum()}[col]  # fmt: skip
    assert total == pytest.approx(full)


def test_averages_are_weighted_not_averaged_averages(databases, truth):
    got = answer("average freight cost", databases, today=TODAY).frame.iloc[0, 0]
    assert got == pytest.approx(truth.freight_cost_usd.mean())
