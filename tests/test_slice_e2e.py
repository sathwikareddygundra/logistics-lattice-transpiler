"""End-to-end slice: NL query -> DAG -> IR -> AST -> SQL/Python -> sandbox."""

import json
import sqlite3
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from ast_.nodes import AstTarget
from confirm.router import CONFIDENCE_THRESHOLD, route
from nlu.groq_parser import GroqParseError, parse_with_groq
from nlu.intent import IntentType, ParsedIntent
from nlu.parser import parse
from pipeline import answer
from plantdb.generate import build_rows, create_database
from sandbox.runner import SandboxError, _connect, run_python, run_sql

TODAY = date(2026, 6, 15)
COLUMNS = [
    "invoice_number", "dispatch_date", "plant", "destination",
    "carrier", "product", "weight_tons", "freight_cost",
]  # fmt: skip


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("plantdb") / "plant.sqlite"
    create_database(path)
    return path


@pytest.fixture(scope="module")
def truth():
    return pd.DataFrame(build_rows(), columns=COLUMNS)


def _same(a: pd.DataFrame, b: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(
        a.reset_index(drop=True), b.reset_index(drop=True), check_dtype=False, rtol=1e-9
    )


def test_seed_data_is_deterministic():
    assert build_rows() == build_rows()


@pytest.mark.parametrize("target", [AstTarget.SQL, AstTarget.PYTHON])
def test_grouped_sum_with_filters(db, truth, target):
    res = answer("total weight by carrier for MCW in March 2026", db, target, TODAY)
    assert res.status == "ok"
    sel = truth[
        (truth.plant == "MCW")
        & (truth.dispatch_date >= "2026-03-01")
        & (truth.dispatch_date < "2026-04-01")
    ]
    exp = sel.groupby("carrier", as_index=False)["weight_tons"].sum()
    exp.columns = ["carrier", "sum_weight_tons"]
    _same(res.result.sort_values("carrier"), exp.sort_values("carrier"))


@pytest.mark.parametrize("target", [AstTarget.SQL, AstTarget.PYTHON])
def test_top_n_ranking(db, truth, target):
    res = answer("top 3 destinations by freight cost", db, target, TODAY)
    assert res.status == "ok"
    exp = (
        truth.groupby("destination", as_index=False)["freight_cost"]
        .sum()
        .sort_values("freight_cost", ascending=False)
        .head(3)
    )
    exp.columns = ["destination", "sum_freight_cost"]
    _same(res.result, exp)


@pytest.mark.parametrize("target", [AstTarget.SQL, AstTarget.PYTHON])
def test_count_last_month(db, truth, target):
    res = answer("how many dispatches last month", db, target, TODAY)
    assert res.status == "ok"
    n = ((truth.dispatch_date >= "2026-05-01") & (truth.dispatch_date < "2026-06-01")).sum()
    assert int(res.result.iloc[0, 0]) == n


@pytest.mark.parametrize("target", [AstTarget.SQL, AstTarget.PYTHON])
def test_ungrouped_average(db, truth, target):
    res = answer("average freight cost for DHL", db, target, TODAY)
    assert res.status == "ok"
    exp = truth[truth.carrier == "DHL"].freight_cost.mean()
    assert res.result.iloc[0, 0] == pytest.approx(exp)


def test_sql_and_python_agree(db):
    q = "total weight by product in April 2026"
    a = answer(q, db, AstTarget.SQL, TODAY).result.sort_values("product")
    b = answer(q, db, AstTarget.PYTHON, TODAY).result.sort_values("product")
    _same(a, b)


def test_codegen_is_deterministic_and_has_header(db):
    q = "total weight by carrier"
    first = answer(q, db, AstTarget.SQL, TODAY).code
    assert first == answer(q, db, AstTarget.SQL, TODAY).code
    assert first.startswith(f"-- Query: {q}")
    assert answer(q, db, AstTarget.PYTHON, TODAY).code.startswith(f"# Query: {q}")


def test_out_of_scope_does_not_crash(db):
    res = answer("what is the weather in Pune", db, AstTarget.SQL, TODAY)
    assert res.status == "out_of_scope"
    assert res.result is None


def test_low_confidence_asks_for_confirmation_then_proceeds(db):
    res = answer("top 3 carriers", db, AstTarget.SQL, TODAY)
    assert res.status == "needs_confirmation"
    assert res.paraphrase.startswith("Did you mean")
    confirmed = answer("top 3 carriers", db, AstTarget.SQL, TODAY, confirmed=True)
    assert confirmed.status == "ok"


def test_router_boundary_is_inclusive_of_threshold():
    def intent(conf: float) -> ParsedIntent:
        return ParsedIntent(query="q", intent_type=IntentType.OUT_OF_SCOPE, confidence=conf)

    assert route(intent(CONFIDENCE_THRESHOLD)).needs_confirmation is False
    assert route(intent(CONFIDENCE_THRESHOLD - 0.001)).needs_confirmation is True


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM dispatch", "DROP TABLE dispatch", "SELECT 1; DELETE FROM dispatch"],
)
def test_destructive_sql_is_rejected(db, sql):
    with pytest.raises(SandboxError) as err:
        run_sql(db, sql)
    assert err.value.stage == "static_validation"


def test_database_connection_is_read_only(db):
    conn = _connect(db, 5.0)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM dispatch")
    conn.close()


def test_runaway_query_is_killed_at_timeout(db):
    sql = "SELECT COUNT(*) FROM dispatch a, dispatch b, dispatch c"
    with pytest.raises(SandboxError) as err:
        run_sql(db, sql, timeout_s=0.2)
    assert err.value.stage == "timeout"


def test_oversized_result_is_rejected_not_truncated(db):
    with pytest.raises(SandboxError) as err:
        run_sql(db, "SELECT invoice_number FROM dispatch", max_rows=10)
    assert err.value.stage == "row_limit"


@pytest.mark.parametrize(
    "code",
    [
        "import os\ndef run(conn):\n    return None\n",
        "def run(conn):\n    return open('/etc/passwd')\n",
        "def run(conn):\n    return conn.__class__\n",
    ],
)
def test_unsafe_python_is_rejected(db, code):
    with pytest.raises(SandboxError) as err:
        run_python(db, code)
    assert err.value.stage == "static_validation"


class _FakeGroq:
    def __init__(self, content: str) -> None:
        self._content = content

    def chat_completion(self, model, messages):
        return SimpleNamespace(content=self._content)


def test_groq_parser_accepts_valid_json_and_rejects_garbage():
    good = {
        "intent_type": "aggregation", "table": "dispatch", "metric": "weight_tons",
        "agg": "sum", "group_by": [], "filters": [], "confidence": 0.9,
    }  # fmt: skip
    intent = parse_with_groq("total weight", _FakeGroq("```json\n" + json.dumps(good) + "\n```"))
    assert intent.metric == "weight_tons"
    with pytest.raises(GroqParseError):
        parse_with_groq("total weight", _FakeGroq("sure! here is your answer"))


def test_parser_never_returns_unvalidated_text():
    assert parse("hello there", TODAY).intent_type is IntentType.OUT_OF_SCOPE
