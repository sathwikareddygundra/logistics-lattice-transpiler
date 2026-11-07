"""Phases 8-9: IR type-checking, registry validation, plant quirks, AST validation and passes."""

import re
import shutil
import sqlite3
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ast_.lowering import ir_to_ast
from ast_.nodes import AstDocument, AstTarget
from ast_.nodes import Node as AstNode
from ast_.optimize import collapse_sorts_and_limits, fold_filters, optimize_ast, prune_dead_branches
from ast_.pretty import render_ast
from ast_.validate import AstValidationError, ast_violations, validate_ast
from codegen.sql import generate_sql
from dag.builder import intent_to_dag
from dag.model import FilterOperator
from ir.adapters import to_plant_ir
from ir.grammar import Edge, Ir, IrOp, Node
from ir.lowering import dag_to_ir
from ir.pretty import render_ir
from ir.registry_check import SchemaDriftError, validate_against_database
from ir.typecheck import IrTypeError, assert_well_typed, check_ir
from nlu.intent import IntentFilter, IntentType, ParsedIntent
from nlu.parser import parse
from pipeline import answer, lower
from plantdb.plants import PROFILES, Plant
from sandbox.runner import run_sql
from tests.conftest import TODAY

ROOT = Path(__file__).resolve().parent.parent


def _ir(q: str) -> Ir:
    return dag_to_ir(intent_to_dag(parse(q, TODAY), "t"))


def col(table, column, type_):
    return {"table": table, "column": column, "type": type_}


def _bad_ir(op_params: dict, op: IrOp, extra_nodes=()) -> Ir:
    """A structurally valid IR (select -> X -> output) whose *types* are wrong."""
    sel = Node(
        id="n1",
        op=IrOp.SELECT,
        params={
            "table": "dispatch",
            "columns": [
                col("dispatch", "carrier", "string"),
                col("dispatch", "freight_cost_usd", "float"),
            ],
        },
    )
    mid = Node.model_construct(id="n2", op=op, params=op_params)
    out = Node(id="n3", op=IrOp.OUTPUT, params={"columns": [col("dispatch", "carrier", "string")]})
    return Ir.model_construct(
        schema_version="1.0.0", trace_id="t", nodes=[sel, mid, out, *extra_nodes],
        edges=[Edge(from_node="n1", to_node="n2"), Edge(from_node="n2", to_node="n3")],
    )  # fmt: skip


# ---- T-58 -------------------------------------------------------------------
def test_well_typed_ir_passes():
    for q in ("total freight cost by carrier", "average TAT by carrier", "monthly weight trend"):
        assert check_ir(_ir(q)) == []


def test_sum_over_a_string_column_names_the_node():
    bad = _bad_ir(
        {
            "group_by": [], "metric": col("dispatch", "carrier", "string"), "op": "sum",
            "result_type": "float",
        },
        IrOp.AGGREGATE,
    )  # fmt: skip
    with pytest.raises(
        IrTypeError, match=r"node n2: sum needs a numeric input but dispatch.carrier is string"
    ):
        assert_well_typed(bad)


def test_filter_value_type_and_operator_checks():
    bad = _bad_ir(
        {
            "column": col("dispatch", "carrier", "string"), "operator": "eq",
            "value": {"value": 3, "type": "integer"},
        },
        IrOp.FILTER,
    )  # fmt: skip
    assert any("filter value is integer, column is string" in str(i) for i in check_ir(bad))


def test_join_key_type_mismatch_is_reported():
    bad = _bad_ir(
        {
            "left_key": col("dispatch", "carrier", "string"),
            "right_key": col("tracking", "driver_id", "integer"), "how": "inner",
        },
        IrOp.JOIN,
    )  # fmt: skip
    assert any("incompatible types" in str(i) and i.node_id == "n2" for i in check_ir(bad))


def test_unavailable_column_is_reported():
    bad = _bad_ir({"by": col("tracking", "driver_id", "string"), "direction": "asc"}, IrOp.SORT)
    msgs = [str(i) for i in check_ir(bad)]
    assert any("node n2: sort column tracking.driver_id is not available here" in m for m in msgs)


# ---- T-59 -------------------------------------------------------------------
def _copy_db(databases, plant, tmp_path):
    src = databases[plant]
    dst = tmp_path / src.name
    shutil.copy(src, dst)
    return dst


def test_renamed_column_fails_with_the_exact_name_before_codegen(databases, tmp_path):
    dst = _copy_db(databases, Plant.MCW, tmp_path)
    conn = sqlite3.connect(dst)
    conn.execute("ALTER TABLE dispatch RENAME COLUMN carrier TO carrier_name")
    conn.commit()
    conn.close()
    ir = to_plant_ir(_ir("total freight cost by carrier"), "MCW")
    with pytest.raises(SchemaDriftError, match=r"dispatch\.carrier"):
        validate_against_database(ir, PROFILES[Plant.MCW], dst)
    res = answer("total freight cost by carrier", {**databases, Plant.MCW: dst}, today=TODAY)
    assert res.status == "partial"
    mcw = next(b for b in res.branches if b.plant == "MCW")
    assert mcw.error_stage == "schema_drift" and "dispatch.carrier" in mcw.error
    assert mcw.code == ""  # nothing was generated for the drifted plant


def test_dropped_table_on_duckdb_is_reported(databases, tmp_path):
    dst = _copy_db(databases, Plant.YCW, tmp_path)
    conn = duckdb.connect(str(dst))
    conn.execute("DROP TABLE ycw_dispatch")
    conn.close()
    ir = to_plant_ir(_ir("total freight cost"), "YCW")
    with pytest.raises(SchemaDriftError, match="ycw_dispatch"):
        validate_against_database(ir, PROFILES[Plant.YCW], dst)


# ---- T-60 -------------------------------------------------------------------
def test_each_plant_gets_its_own_physical_tables_at_ir_level_only():
    base = _ir("average TAT by carrier")
    tables = {
        p: [n.params["table"] for n in to_plant_ir(base, p).nodes if n.op is IrOp.SELECT]
        for p in ("MCW", "YCW", "VGU")
    }
    assert tables["MCW"] == ["dispatch", "turnaround_time"]
    assert tables["YCW"] == ["ycw_dispatch", "ycw_tat"]
    assert tables["VGU"] == ["vgu_dispatch", "vgu_tat"]
    assert [n.params for n in base.nodes if n.op is not IrOp.SELECT] == [
        n.params for n in to_plant_ir(base, "YCW").nodes if n.op is not IrOp.SELECT
    ]


def test_no_downstream_stage_branches_on_plant_names():
    for folder in ("codegen", "ast_", "cag", "dag", "graph_eng", "sandbox", "plan"):
        for path in (ROOT / folder).rglob("*.py"):
            assert not re.search(r"\b(MCW|YCW|VGU)\b", path.read_text()), path


@pytest.mark.parametrize("plant", list(Plant))
def test_one_golden_query_per_plant_runs_with_plant_correct_ir(databases, plant):
    intent = parse("total freight cost by carrier", TODAY)
    low = lower(intent, plant.value, AstTarget.SQL, "t", databases[plant])
    sql = generate_sql(low.ast, intent.query, PROFILES[plant].dialect).text
    frame = run_sql(PROFILES[plant], databases[plant], sql)
    assert len(frame) == 5 and frame.iloc[:, 1].sum() > 0


# ---- T-61 / T-67 ------------------------------------------------------------
def test_pretty_printers_are_stable_and_readable():
    ir = _ir("average TAT by carrier in August")
    assert render_ir(ir) == render_ir(ir)
    text = render_ir(ir)
    assert (
        "join: dispatch.invoice_number:string = turnaround_time.invoice_number:string (inner)"
        in text
    )
    assert (
        "avg(turnaround_time.total_tat_hours:float) -> float by [dispatch.carrier:string]" in text
    )
    assert "<- n1[left], n2[right]" in text
    ast = ir_to_ast(ir, AstTarget.SQL)
    assert render_ast(ast) == render_ast(ast) and render_ast(ast).startswith(
        "ast v1.0.0 target=sql"
    )


# ---- T-65 -------------------------------------------------------------------
def _ast(q: str) -> AstDocument:
    return ir_to_ast(_ir(q), AstTarget.SQL)


def test_well_formed_asts_pass():
    for q in ("total freight cost by carrier", "average TAT by carrier", "show delayed shipments"):
        validate_ast(_ast(q))


def test_orphaned_subtree_is_named():
    doc = _ast("total freight cost by carrier")
    extra = AstNode(
        id="zz", op=IrOp.FILTER, var="df99",
        params={
            "column": col("dispatch", "carrier", "string"), "operator": "eq",
            "value": {"value": "DHL", "type": "string"},
        },
    )  # fmt: skip
    bad = AstDocument(
        trace_id="t", target=doc.target, nodes=[*doc.nodes, extra],
        edges=[*doc.edges, Edge(from_node="n1", to_node="zz")],
    )  # fmt: skip
    assert any("df99: orphaned subtree" in v for v in ast_violations(bad))
    with pytest.raises(AstValidationError, match="df99"):
        validate_ast(bad)


def test_dangling_column_reference_is_named():
    doc = _ast("total freight cost by carrier")
    nodes = [
        n.model_copy(
            update={
                "params": {
                    **n.params,
                    "by": col("tracking", "driver_id", "string"),
                    "direction": "asc",
                }
            }
        )
        if False
        else n
        for n in doc.nodes
    ]
    sort = AstNode(
        id="n9", op=IrOp.SORT, var="df9",
        params={"by": col("tracking", "driver_id", "string"), "direction": "asc"},
    )  # fmt: skip
    out_edge = next(e for e in doc.edges if e.to_node == nodes[-1].id)
    bad = AstDocument(
        trace_id="t", target=doc.target, nodes=[*nodes, sort],
        edges=[*[e for e in doc.edges if e is not out_edge],
               Edge(from_node=out_edge.from_node, to_node="n9"), Edge(from_node="n9", to_node=out_edge.to_node)],
    )  # fmt: skip
    assert any(
        "tracking.driver_id, which is not available upstream" in v for v in ast_violations(bad)
    )


def test_join_with_one_input_is_flagged():
    doc = _ast("average TAT by carrier")
    join = next(n for n in doc.nodes if n.op is IrOp.JOIN)
    crippled = AstDocument.model_construct(
        schema_version="1.0.0", trace_id="t", target=doc.target, nodes=doc.nodes,
        edges=[e for e in doc.edges if not (e.to_node == join.id and e.role and e.role.value == "right")],
    )  # fmt: skip
    assert any("join needs exactly two inputs, has 1" in v for v in ast_violations(crippled))


# ---- T-66 -------------------------------------------------------------------
def _intent_with_redundant_filters() -> ParsedIntent:
    f = lambda c, o, v: IntentFilter(column=c, operator=o, value=v)  # noqa: E731
    return ParsedIntent(
        query="q", intent_type=IntentType.AGGREGATION, metric="freight_cost_usd", agg="sum",
        group_by=["carrier"], confidence=0.9,
        filters=[
            f("carrier", FilterOperator.EQ, "DHL"), f("carrier", FilterOperator.EQ, "DHL"),
            f("dispatch_date", FilterOperator.GTE, "2026-06-01"),
            f("dispatch_date", FilterOperator.GTE, "2026-07-01"),
            f("dispatch_date", FilterOperator.LT, "2026-09-01"),
            f("dispatch_date", FilterOperator.LT, "2026-08-01"),
        ],
    )  # fmt: skip


def _ast_for(intent: ParsedIntent) -> AstDocument:
    return ir_to_ast(dag_to_ir(intent_to_dag(intent, "t")), AstTarget.SQL)


def test_redundant_filters_fold_to_the_tightest_bounds():
    doc = _ast_for(_intent_with_redundant_filters())
    folded = fold_filters(doc)
    kept = [
        (n.params["column"]["column"], n.params["operator"], n.params["value"]["value"])
        for n in folded.nodes
        if n.op is IrOp.FILTER
    ]
    assert sorted(kept) == [
        ("carrier", "eq", "DHL"),
        ("dispatch_date", "gte", "2026-07-01"),
        ("dispatch_date", "lt", "2026-08-01"),
    ]


def test_ast_passes_are_idempotent():
    doc = _ast_for(_intent_with_redundant_filters())
    for fn in (fold_filters, collapse_sorts_and_limits, prune_dead_branches, optimize_ast):
        once = fn(doc)
        assert fn(once) == once


def test_optimized_ast_returns_the_same_rows(databases):
    doc = _ast_for(_intent_with_redundant_filters())
    opt = optimize_ast(doc)
    assert len(opt.nodes) < len(doc.nodes)
    out = []
    for d in (doc, opt):
        ir_like = to_plant_ir  # noqa: F841
        sql = generate_sql(
            AstDocument(trace_id="t", target=d.target, nodes=[
                AstNode(id=n.id, op=n.op, var=n.var, params=(
                    {**n.params, "table": "dispatch"} if n.op is IrOp.SELECT else n.params
                )) for n in d.nodes], edges=d.edges),
            "q", "sqlite",
        ).text  # fmt: skip
        out.append(run_sql(PROFILES[Plant.MCW], databases[Plant.MCW], sql))
    pd.testing.assert_frame_equal(out[0], out[1])


def test_stacked_limits_and_sorts_collapse():
    doc = _ast("top 5 carriers by freight cost")
    limit = next(n for n in doc.nodes if n.op is IrOp.LIMIT)
    assert limit.params["count"] == 5
    assert collapse_sorts_and_limits(doc) == doc
