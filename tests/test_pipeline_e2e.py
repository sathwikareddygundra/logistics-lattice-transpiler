"""End-to-end: NL query -> DAG -> IR -> AST -> SQL/Python per plant -> sandbox -> merge,
checked against an independent pandas calculation on the raw CSV data."""

import pandas as pd
import pytest

from ast_.nodes import AstTarget
from pipeline import answer
from tests.conftest import TODAY


def _run(q, dbs, **kw):
    return answer(q, dbs, today=TODAY, **kw)


def _same(a: pd.DataFrame, b: pd.DataFrame):
    pd.testing.assert_frame_equal(
        a.reset_index(drop=True), b.reset_index(drop=True), check_dtype=False, rtol=1e-9
    )


@pytest.mark.parametrize("target", [AstTarget.SQL, AstTarget.PYTHON])
def test_grouped_sum_matches_ground_truth(databases, truth, target):
    r = _run("total freight cost by carrier in August 2026", databases, target=target)
    assert r.status == "ok", r.message
    sel = truth[(truth.dispatch_date >= "2026-08-01") & (truth.dispatch_date < "2026-09-01")]
    exp = sel.groupby("carrier", as_index=False)["freight_cost_usd"].sum()
    exp.columns = ["carrier", "sum_freight_cost_usd"]
    _same(r.frame, exp.sort_values("carrier"))


@pytest.mark.parametrize("target", [AstTarget.SQL, AstTarget.PYTHON])
def test_join_across_tables_average(databases, truth, target):
    r = _run("average TAT by carrier", databases, target=target)
    assert r.status == "ok", r.message
    exp = truth.groupby("carrier", as_index=False)["total_tat_hours"].mean()
    exp.columns = ["carrier", "avg_total_tat_hours"]
    _same(r.frame, exp.sort_values("carrier"))


def test_rank_top_n(databases, truth):
    r = _run("top 3 destinations by freight cost", databases)
    exp = (
        truth.groupby("destination_city", as_index=False)["freight_cost_usd"]
        .sum()
        .sort_values("freight_cost_usd", ascending=False)
        .head(3)
    )
    exp.columns = ["destination_city", "sum_freight_cost_usd"]
    _same(r.frame, exp)


def test_count_with_status_filter(databases, truth):
    r = _run("how many delayed shipments", databases)
    assert int(r.frame.iloc[0, 0]) == (truth.current_status == "Delayed").sum()


def test_trend_monthly(databases, truth):
    r = _run("monthly weight trend", databases)
    exp = (
        truth.assign(m=truth.dispatch_date.str[:7])
        .groupby("m", as_index=False)["shipment_weight_kg"]
        .sum()
    )
    exp.columns = ["dispatch_date_month", "sum_shipment_weight_kg"]
    _same(r.frame, exp)


def test_forecast_adds_future_rows(databases):
    r = _run("forecast freight cost next 2 months", databases)
    assert list(r.frame.columns) == ["dispatch_date_month", "sum_freight_cost_usd", "kind"]
    assert (r.frame.kind == "forecast").sum() == 2
    assert r.frame[r.frame.kind == "forecast"].dispatch_date_month.tolist() == [
        "2026-09",
        "2026-10",
    ]


def test_compare_plants_keeps_each_plant_separate(databases, truth):
    r = _run("compare MCW and YCW freight cost", databases)
    assert sorted(r.frame.plant.unique()) == ["MCW", "YCW"]
    assert len(r.frame) == 2
    assert r.frame.sum_freight_cost_usd.sum() < truth.freight_cost_usd.sum()


def test_or_semantics_for_two_values_of_one_column(databases, truth):
    r = _run("freight cost for DHL and FedEx", databases)
    assert sorted(r.frame.carrier) == ["DHL", "FedEx"]
    exp = truth[truth.carrier.isin(["DHL", "FedEx"])].groupby("carrier").freight_cost_usd.sum()
    got = r.frame.set_index("carrier").sum_freight_cost_usd.to_dict()
    assert got == pytest.approx(exp.to_dict())


def test_row_listing_join(databases):
    r = _run("show delayed shipments from Chicago with sla status", databases)
    assert r.status == "ok"
    assert len(r.frame) == 20
    assert {"invoice_number", "sla_status", "origin_warehouse"} <= set(r.frame.columns)
    assert (r.frame.origin_warehouse == "Chicago_WH").all()


def test_single_plant_scope_is_a_strict_subset(databases, truth):
    one = _run("total weight for MCW", databases).frame.iloc[0, 0]
    allp = _run("total weight", databases).frame.iloc[0, 0]
    assert 0 < one < allp
    assert allp == pytest.approx(truth.shipment_weight_kg.sum())


def test_sql_and_python_targets_agree(databases):
    q = "total weight by origin warehouse in July 2026"
    a = _run(q, databases, target=AstTarget.SQL).frame
    b = _run(q, databases, target=AstTarget.PYTHON).frame
    _same(a, b)


def test_out_of_scope_is_declined_and_logged(databases, tmp_path):
    log = tmp_path / "fb.jsonl"
    r = _run("optimise my delivery routes", databases, fallback_log=log)
    assert r.status == "out_of_scope" and r.frame is None
    assert log.read_text().count("\n") == 1


def test_missing_metric_asks_exactly_one_question(databases):
    r = _run("top 3 carriers", databases)
    assert r.status == "needs_slot"
    assert r.message.startswith("Which measure")


def test_one_plant_failing_does_not_kill_the_answer(databases, tmp_path):
    broken = dict(databases)
    from plantdb.plants import Plant

    broken[Plant.VGU] = tmp_path / "missing.sqlite"
    r = _run("total weight", broken)
    assert r.status == "partial"
    assert "VGU" in r.message
    assert r.frame is not None
