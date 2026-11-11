"""VGU on a real PostgreSQL server (T-75..T-80). Skipped when no server is reachable;
start one with scripts/local_postgres.sh and export LATTICE_PG_DSN."""

import os

import pandas as pd
import pytest

psycopg = pytest.importorskip("psycopg")

DSN = os.environ.get("LATTICE_PG_DSN", "postgresql://postgres@localhost:5433/lattice")


def _server_up() -> bool:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _server_up(), reason="no PostgreSQL server reachable")

from ast_.nodes import AstTarget  # noqa: E402
from pipeline import answer  # noqa: E402
from plantdb.plants import (  # noqa: E402
    Plant,
    build_plant_databases,
    get_profile,
    plant_for_invoice,
)
from sandbox.runner import SandboxError, _connect, run_sql  # noqa: E402
from tests.conftest import TODAY  # noqa: E402


@pytest.fixture(scope="module")
def pg_databases(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LATTICE_VGU_ENGINE", "postgres")
    mp.setenv("LATTICE_PG_DSN", DSN)
    try:
        yield build_plant_databases(tmp_path_factory.mktemp("pg"))
    finally:
        mp.undo()


@pytest.fixture(autouse=True)
def _vgu_postgres(monkeypatch):
    monkeypatch.setenv("LATTICE_VGU_ENGINE", "postgres")
    monkeypatch.setenv("LATTICE_PG_DSN", DSN)


def test_vgu_is_really_postgres(pg_databases):
    assert get_profile(Plant.VGU).engine == "postgres"
    assert isinstance(pg_databases[Plant.VGU], str) and "lattice_ro@" in pg_databases[Plant.VGU]


def test_totals_across_sqlite_duckdb_and_postgres_match_ground_truth(pg_databases, truth):
    r = answer("total freight cost by carrier", pg_databases, today=TODAY)
    assert r.status == "ok", r.message
    exp = truth.groupby("carrier").freight_cost_usd.sum()
    assert r.frame.set_index("carrier").iloc[:, 0].to_dict() == pytest.approx(exp.to_dict())
    assert any("FROM vgu_dispatch" in b.code for b in r.branches)


def test_vgu_only_is_the_vgu_slice_of_the_data(pg_databases, truth):
    r = answer("total weight for VGU", pg_databases, today=TODAY)
    mask = truth.invoice_number.map(plant_for_invoice) == Plant.VGU
    assert r.frame.iloc[0, 0] == pytest.approx(truth[mask].shipment_weight_kg.sum())


@pytest.mark.parametrize("gran", ["day", "week", "month", "quarter", "year"])
def test_time_buckets_agree_across_all_three_engines(pg_databases, truth, gran):
    """The dialect-specific bucket templates must produce the same labels as pandas."""
    r = answer(
        f"{gran}ly freight cost" if gran != "day" else "daily freight cost",
        pg_databases,
        today=TODAY,
    )
    assert r.status == "ok", r.message
    t = pd.to_datetime(truth.dispatch_date)
    label = {
        "day": t.dt.strftime("%Y-%m-%d"), "week": t.dt.strftime("%Y-W%W"),
        "month": t.dt.strftime("%Y-%m"), "year": t.dt.strftime("%Y"),
        "quarter": t.dt.year.astype(str) + "-Q" + t.dt.quarter.astype(str),
    }[gran]  # fmt: skip
    exp = truth.groupby(label).freight_cost_usd.sum()
    got = r.frame.set_index(r.frame.columns[0]).iloc[:, 0]
    assert got.to_dict() == pytest.approx(exp.to_dict())


def test_python_target_on_postgres_matches_sql_target(pg_databases):
    q = "total weight by origin warehouse in July 2026"
    a = answer(q, pg_databases, today=TODAY, target=AstTarget.SQL).frame
    b = answer(q, pg_databases, today=TODAY, target=AstTarget.PYTHON).frame
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


def test_sandbox_role_cannot_write(pg_databases):
    conn = _connect(get_profile(Plant.VGU), pg_databases[Plant.VGU], 5.0)
    with pytest.raises(Exception, match="(?i)read-only|permission denied"):
        conn.raw.execute("DELETE FROM vgu_dispatch")
    conn.close()


def test_runaway_query_is_cancelled_at_the_timeout(pg_databases):
    sql = "SELECT COUNT(*) FROM vgu_dispatch a, vgu_dispatch b, vgu_dispatch c"
    with pytest.raises(SandboxError) as err:
        run_sql(get_profile(Plant.VGU), pg_databases[Plant.VGU], sql, timeout_s=0.3)
    assert err.value.stage == "timeout"


def test_registry_validation_works_on_postgres(pg_databases):
    from dag.builder import intent_to_dag
    from ir.adapters import to_plant_ir
    from ir.lowering import dag_to_ir
    from ir.registry_check import validate_against_database
    from nlu.parser import parse

    ir = to_plant_ir(dag_to_ir(intent_to_dag(parse("total freight cost", TODAY), "t")), "VGU")
    validate_against_database(ir, get_profile(Plant.VGU), pg_databases[Plant.VGU])


@pytest.mark.parametrize(
    "gid", sorted(__import__("tests.golden_queries", fromlist=["x"]).GOLDEN_QUERIES)
)
def test_golden_queries_match_frozen_results_with_vgu_on_postgres(pg_databases, gid):
    """T-80: every golden query, run with VGU on real PostgreSQL, equals the frozen result."""
    import json

    from scripts.update_golden import ROOT
    from tests.golden_queries import GOLDEN_QUERIES

    res = answer(GOLDEN_QUERIES[gid], pg_databases, today=TODAY, confirmed=True)
    assert res.status == "ok", res.message
    frozen = json.loads((ROOT / "results" / f"{gid}.json").read_text())
    got = res.frame.round(4).astype(object).where(res.frame.notna(), None).values.tolist()
    assert list(res.frame.columns) == frozen["columns"]
    assert len(got) == len(frozen["rows"])
    for g_row, f_row in zip(got, frozen["rows"], strict=True):
        for g, f in zip(g_row, f_row, strict=True):
            if isinstance(f, int | float) and not isinstance(f, bool):
                assert g == pytest.approx(f, rel=1e-3, abs=1e-3)
            else:
                assert str(g) == str(f)  # timestamps come back as datetime objects
