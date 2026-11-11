"""Phase 7: CAG is lookup + template injection only, deterministic, cached and versioned."""

import dataclasses

import httpx
import pytest

import cag.templates as templates
from ast_.lowering import ir_to_ast
from ast_.nodes import AstTarget
from cag.context import assemble_cached, assemble_context, clear_cache, needed_columns
from cag.templates import (
    TEMPLATES,
    TemplateNotFoundError,
    check_lock,
    select_template,
)
from codegen.python import generate_python
from codegen.sql import generate_sql
from common.groq_client import GroqClient
from dag.builder import intent_to_dag
from ir.grammar import IrOp
from ir.lowering import dag_to_ir
from nlu.parser import parse
from plantdb.catalog import TABLES
from tests.conftest import TODAY


def _dag(q):
    return intent_to_dag(parse(q, TODAY), "t")


def test_context_holds_only_the_slice_a_query_touches():
    cols = needed_columns(_dag("total freight cost by carrier"))
    assert cols == {"dispatch": ["carrier", "freight_cost_usd"]}
    assert "tracking" not in cols and "turnaround_time" not in cols
    total = sum(len(t.columns) for t in TABLES.values())
    assert sum(len(c) for c in cols.values()) < total / 3


def test_context_size_follows_relevance_not_schema_size():
    small = needed_columns(_dag("total freight cost"))
    bigger = needed_columns(_dag("average TAT by carrier for delayed shipments in August"))
    assert sum(map(len, small.values())) < sum(map(len, bigger.values()))
    assert set(bigger) == {"dispatch", "turnaround_time", "tracking"}


def test_join_key_is_included_only_when_tables_are_joined():
    assert "invoice_number" not in needed_columns(_dag("total freight cost by carrier"))["dispatch"]
    joined = needed_columns(_dag("average TAT by carrier"))
    assert all("invoice_number" in cols for cols in joined.values())


def test_selection_is_exact_and_never_guesses():
    assert select_template("filter", "sql").id == "filter.sql"
    assert select_template("bucket", "sql", "duckdb", "month").id == "bucket.sql.duckdb.month"
    with pytest.raises(TemplateNotFoundError):
        select_template("sort", "sql")  # folded into the final SELECT, deliberately no template
    with pytest.raises(TemplateNotFoundError):
        select_template("filter", "cobol")
    with pytest.raises(TemplateNotFoundError):
        select_template("bucket", "sql", "oracle", "month")


def test_template_coverage_matrix_has_no_unexplained_gaps():
    folded_in_sql = {"sort", "limit"}
    unsupported_in_sql = {"forecast"}  # forecast runs on Python or after the cross-plant merge
    for op in IrOp:
        name = "select" if op is IrOp.SELECT else op.value
        py_op = name
        if op is IrOp.AGGREGATE:
            assert select_template("aggregate", "python") and select_template(
                "aggregate_scalar", "python"
            )
        else:
            assert select_template(py_op, "python"), f"missing python template for {name}"
        if name in folded_in_sql | unsupported_in_sql:
            with pytest.raises(TemplateNotFoundError):
                select_template(name, "sql")
        else:
            assert select_template(name, "sql"), f"missing sql template for {name}"
    for dialect in ("sqlite", "duckdb", "postgres"):
        for gran in ("day", "week", "month", "quarter", "year"):
            assert select_template("bucket", "sql", dialect, gran)
    for gran in ("day", "week", "month", "quarter", "year"):
        assert select_template("bucket", "python", granularity=gran)


def test_assembly_never_calls_a_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("an LLM/network call happened during CAG assembly")

    monkeypatch.setattr(GroqClient, "chat_completion", boom)
    monkeypatch.setattr(httpx.Client, "post", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    ctx = assemble_context(_dag("average TAT by carrier"))
    assert ctx and all(isinstance(c.template_id, str) for c in ctx.values())


def test_context_assembly_and_codegen_are_byte_identical_over_100_runs():
    dag = _dag("average TAT by carrier in August 2026")
    first_ctx = repr(assemble_context(dag))
    ir = dag_to_ir(dag)
    first_sql = generate_sql(ir_to_ast(ir, AstTarget.SQL), "q", "sqlite").text
    first_py = generate_python(ir_to_ast(ir, AstTarget.PYTHON), "q").text
    for _ in range(100):
        assert repr(assemble_context(dag)) == first_ctx
        assert generate_sql(ir_to_ast(ir, AstTarget.SQL), "q", "sqlite").text == first_sql
    assert generate_python(ir_to_ast(ir, AstTarget.PYTHON), "q").text == first_py


def test_cache_hits_and_invalidates_on_a_template_version_bump(monkeypatch):
    clear_cache()
    dag = _dag("total freight cost by carrier")
    a = assemble_cached(dag)
    assert assemble_cached(dag) is a  # hit
    bumped = dataclasses.replace(
        TEMPLATES["filter.sql"], version=TEMPLATES["filter.sql"].version + 1
    )
    monkeypatch.setitem(TEMPLATES, "filter.sql", bumped)
    assert assemble_cached(dag) is not a  # version bump gives a new key
    clear_cache()


def test_cache_key_ignores_trace_id_but_not_the_query_shape():
    clear_cache()
    a = assemble_cached(intent_to_dag(parse("total freight cost", TODAY), "trace-1"))
    b = assemble_cached(intent_to_dag(parse("total freight cost", TODAY), "trace-2"))
    c = assemble_cached(intent_to_dag(parse("total weight", TODAY), "trace-1"))
    assert a is b and a is not c
    clear_cache()


def test_lock_file_is_current():
    assert check_lock() == []


def test_lock_check_catches_an_unbumped_template_edit(monkeypatch):
    edited = dataclasses.replace(TEMPLATES["limit.py"], body=TEMPLATES["limit.py"].body + " ")
    monkeypatch.setitem(TEMPLATES, "limit.py", edited)
    problems = check_lock()
    assert any("limit.py" in p and "version is still" in p for p in problems)


def test_provenance_records_template_versions_for_every_node():
    ir = dag_to_ir(_dag("average TAT by carrier"))
    code = generate_sql(ir_to_ast(ir, AstTarget.SQL), "q", "sqlite")
    assert {n for n, _, _ in code.provenance} >= {"n1", "n3", "n4"}
    assert all(v >= 1 and tid in templates.TEMPLATES for _, tid, v in code.provenance)
