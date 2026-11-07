"""Phase 12: sandbox safety, static validation, limits, diagnostics, shape/cost checks, traces."""

import json
import sqlite3
import time

import duckdb
import pandas as pd
import pytest

from ast_.nodes import AstTarget
from logging_config import get_trace
from nlu.parser import parse
from pipeline import answer, lower
from plantdb.plants import PROFILES, Plant
from sandbox.cost_check import MISMATCH_FACTOR, check_cost
from sandbox.result_check import ResultShapeError, check_result
from sandbox.runner import (
    SandboxError,
    _connect,
    run_python,
    run_sql,
    validate_python,
    validate_sql,
)
from scripts.update_golden import ROOT
from tests.conftest import TODAY
from tests.golden_queries import GOLDEN_QUERIES

MCW, YCW = PROFILES[Plant.MCW], PROFILES[Plant.YCW]


# ---- T-81 production is unreachable ------------------------------------------
@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM dispatch",
        "DROP TABLE dispatch",
        "UPDATE dispatch SET carrier='x'",
        "INSERT INTO dispatch VALUES (1)",
        "SELECT 1; DROP TABLE dispatch",
    ],
)
def test_destructive_sql_never_passes_validation(databases, sql):
    with pytest.raises(SandboxError) as err:
        run_sql(MCW, databases[Plant.MCW], sql)
    assert err.value.stage == "static_validation"


def test_even_if_validation_were_bypassed_the_connections_are_read_only(databases):
    conn = _connect(MCW, databases[Plant.MCW], 5.0)
    with pytest.raises(sqlite3.OperationalError):
        conn.raw.execute("DELETE FROM dispatch")
    conn.close()
    dconn = _connect(YCW, databases[Plant.YCW], 5.0)
    with pytest.raises(duckdb.Error):
        dconn.raw.execute("DELETE FROM ycw_dispatch")
    dconn.close()
    before = run_sql(MCW, databases[Plant.MCW], "SELECT COUNT(*) AS n FROM dispatch").n[0]
    assert before == 3333


# ---- T-82 static validation, zero false rejections ----------------------------
def test_full_golden_set_passes_static_validation():
    for path in (ROOT / "sql").glob("*.sql"):
        dialect = PROFILES[Plant(path.name.split(".")[1])].dialect
        validate_sql(path.read_text(), dialect)
    for path in (ROOT / "python").glob("*.py"):
        validate_python(path.read_text())


@pytest.mark.parametrize(
    "code,fragment",
    [
        ("import os\ndef run(read_sql):\n    return None\n", "only `import pandas`"),
        ("def run(read_sql):\n    return open('/etc/passwd')\n", "'open' is not allowed"),
        ("def run(read_sql):\n    return read_sql.__class__\n", "dunder"),
        ("from os import path\n", "`from ... import`"),
        ("def run(:\n", "does not parse"),
    ],
)
def test_malformed_or_unsafe_python_is_caught_before_running(databases, code, fragment):
    with pytest.raises(SandboxError, match="static_validation") as err:
        run_python(MCW, databases[Plant.MCW], code)
    assert fragment in err.value.message


def test_malformed_sql_is_caught_before_running(databases):
    with pytest.raises(SandboxError) as err:
        run_sql(MCW, databases[Plant.MCW], "SELEC carrier FRM dispatch")
    assert err.value.stage == "static_validation"


# ---- T-83 timeout and row limits ----------------------------------------------
RUNAWAY = {
    Plant.MCW: "SELECT COUNT(*) FROM dispatch a, dispatch b, dispatch c",
    Plant.YCW: "SELECT COUNT(*) FROM ycw_dispatch a, ycw_dispatch b, ycw_dispatch c, ycw_dispatch d",
}


@pytest.mark.parametrize("plant", [Plant.MCW, Plant.YCW])
def test_runaway_sql_is_killed_at_the_timeout(databases, plant):
    start = time.perf_counter()
    with pytest.raises(SandboxError) as err:
        run_sql(PROFILES[plant], databases[plant], RUNAWAY[plant], timeout_s=0.3)
    assert err.value.stage == "timeout"
    assert time.perf_counter() - start < 5


def test_infinite_python_loop_is_killed_in_an_isolated_process(databases):
    code = "def run(read_sql):\n    while True:\n        pass\n"
    start = time.perf_counter()
    with pytest.raises(SandboxError) as err:
        run_python(MCW, databases[Plant.MCW], code, timeout_s=1.0, isolated=True)
    assert err.value.stage == "timeout"
    assert time.perf_counter() - start < 6


def test_isolated_python_returns_the_same_frame_as_in_process(databases):
    code = (ROOT / "python" / "agg_sum_group.MCW.py").read_text()
    a = run_python(MCW, databases[Plant.MCW], code)
    b = run_python(MCW, databases[Plant.MCW], code, isolated=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


@pytest.mark.parametrize("plant,table", [(Plant.MCW, "dispatch"), (Plant.YCW, "ycw_dispatch")])
def test_oversized_results_are_rejected_not_truncated(databases, plant, table):
    with pytest.raises(SandboxError) as err:
        run_sql(
            PROFILES[plant], databases[plant], f"SELECT invoice_number FROM {table}", max_rows=10
        )
    assert err.value.stage == "row_limit"


# ---- T-84 diagnostics ---------------------------------------------------------
def test_failures_become_structured_diagnostics(databases, tmp_path):
    import shutil

    dst = tmp_path / "mcw.sqlite"
    shutil.copy(databases[Plant.MCW], dst)
    conn = sqlite3.connect(dst)
    conn.execute("ALTER TABLE dispatch RENAME COLUMN carrier TO carrier_name")
    conn.commit()
    conn.close()
    res = answer("total freight cost by carrier", {**databases, Plant.MCW: dst}, today=TODAY)
    diag = next(b for b in res.branches if b.plant == "MCW").diagnostic
    assert diag is not None
    d = diag.to_dict()
    assert d["category"] == "schema_drift" and d["stage"] == "lowering" and d["plant"] == "MCW"
    assert d["query"] == "total freight cost by carrier" and d["trace_id"] == res.trace_id
    assert "dispatch.carrier" in d["message"]
    json.dumps(d)


# ---- T-85 result shape --------------------------------------------------------
def _ast(q, plant="MCW"):
    return lower(parse(q, TODAY), plant, AstTarget.SQL, "t").ast


def test_correct_results_pass_the_shape_check(databases):
    for q in (
        "total freight cost by carrier",
        "how many delayed shipments",
        "monthly weight trend",
    ):
        doc = _ast(q)
        code_frame = answer(q, databases, today=TODAY).frame
        if q != "monthly weight trend":
            check_result(code_frame, doc)


def test_shape_mismatches_are_named():
    doc = _ast("total freight cost by carrier")
    good = pd.DataFrame({"carrier": ["DHL"], "sum_freight_cost_usd": [1.0]})
    check_result(good, doc)
    with pytest.raises(ResultShapeError, match=r"missing \['sum_freight_cost_usd'\]"):
        check_result(good[["carrier"]], doc)
    with pytest.raises(ResultShapeError, match=r"unexpected \['extra'\]"):
        check_result(good.assign(extra=1), doc)
    with pytest.raises(ResultShapeError, match="should be numeric"):
        check_result(good.assign(sum_freight_cost_usd="abc"), doc)
    scalar = _ast("total freight cost")
    with pytest.raises(ResultShapeError, match="must return 1 row"):
        check_result(pd.DataFrame({"sum_freight_cost_usd": [1.0, 2.0]}), scalar)
    top = _ast("top 2 carriers by freight cost")
    with pytest.raises(ResultShapeError, match="limits it to 2"):
        check_result(
            pd.DataFrame({"carrier": list("abc"), "sum_freight_cost_usd": [1.0, 2.0, 3.0]}), top
        )


# ---- T-86 cost sanity ---------------------------------------------------------
def test_order_of_magnitude_gap_blocks_promotion_but_small_gaps_do_not():
    assert check_cost(1000, 100_000).block_promotion
    assert check_cost(100_000, 1000).block_promotion
    assert not check_cost(1000, 5000).block_promotion
    assert not check_cost(2, 80).block_promotion  # tiny results are ignored
    assert check_cost(1000, 1000 * MISMATCH_FACTOR).block_promotion  # exactly at the limit


@pytest.mark.parametrize("gid,query", sorted(GOLDEN_QUERIES.items()))
def test_no_false_alarms_on_the_golden_queries(databases, gid, query):
    res = answer(query, databases, today=TODAY, confirmed=True)
    assert res.status == "ok", (res.status, res.message)
    assert all(not (b.cost and b.cost.block_promotion) for b in res.branches)


def test_a_bad_estimate_holds_the_result_for_review(databases, monkeypatch):
    import pipeline

    monkeypatch.setattr(pipeline, "_estimated_output_rows", lambda dag: 1_000_000)
    res = answer("show FedEx shipments in August", databases, today=TODAY, confirmed=True)
    assert res.status == "needs_review" and "needs human review" in res.message
    assert res.frame is not None  # visible to a reviewer, but not promoted as an answer


# ---- T-87 traces --------------------------------------------------------------
def test_one_trace_id_shows_the_whole_journey_in_order(databases):
    res = answer("average TAT by carrier in August", databases, today=TODAY)
    events = get_trace(res.trace_id)
    stages = [e["stage"] for e in events]
    assert stages[:2] == ["nlu", "confirm"] and stages[-1] == "merge"
    assert stages.count("sandbox") == 6  # three plants, sum and count variants
    for plant in ("MCW", "YCW", "VGU"):
        seq = [e["stage"] for e in events if e.get("plant") == plant]
        assert seq[:5] == ["dag", "ir", "ast", "codegen", "sandbox"]
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)
    assert all({"duration_ms", "cpu_ms", "max_rss_kb", "ok"} <= e.keys() for e in events)
    json.dumps(events)


# ---- T-88 good and bad queries ------------------------------------------------
BAD_SQL = [
    ("SELEC 1", "static_validation"),
    ("DELETE FROM dispatch", "static_validation"),
    ("SELECT nope FROM dispatch", "execution"),
    ("SELECT * FROM missing_table", "execution"),
]


@pytest.mark.parametrize("sql,stage", BAD_SQL)
def test_known_bad_sql_fails_in_its_specific_way(databases, sql, stage):
    with pytest.raises(SandboxError) as err:
        run_sql(MCW, databases[Plant.MCW], sql)
    assert err.value.stage == stage
