"""Phases 10-11: generated Python and SQL are valid, lint-clean, formatted, commented, deterministic
and give the same answers on every engine."""

import ast
import subprocess
import sys

import pytest
import sqlglot

from ast_.nodes import AstTarget
from cag.templates import select_template
from codegen.common import CodegenHints, UnsupportedAstError
from codegen.python import format_python, generate_python
from codegen.sql import _format, generate_sql, literal, quote
from nlu.parser import parse
from pipeline import lower
from plantdb.plants import PROFILES, Plant
from scripts.update_golden import ROOT
from tests.conftest import TODAY
from tests.golden_queries import GOLDEN_QUERIES

PY_FILES = sorted((ROOT / "python").glob("*.py"))
SQL_FILES = sorted((ROOT / "sql").glob("*.sql"))


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: p.name)
def test_generated_python_parses_and_has_no_lint_problems(path):
    code = path.read_text()
    ast.parse(code)
    out = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F", "--stdin-filename", "g.py", "-"],
        input=code, capture_output=True, text=True,
    )  # fmt: skip
    assert out.returncode == 0, out.stdout  # no unused imports, no undefined names


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: p.name)
def test_python_formatting_is_idempotent(path):
    code = path.read_text()
    assert format_python(code) == code


def test_imports_are_injected_only_when_used():
    simple = (ROOT / "python" / "list_filter.MCW.py").read_text()
    windowed = (ROOT / "python" / "trend_month.MCW.py").read_text()
    assert "import pandas" not in simple and "pd." not in simple
    assert "import pandas as pd" in windowed and "pd.to_datetime" in windowed


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.name)
def test_generated_sql_parses_in_its_dialect_and_formatting_is_idempotent(path):
    plant = path.name.split(".")[1]
    dialect = PROFILES[Plant(plant)].dialect
    body = path.read_text().split("\n", 1)[1]  # drop the header comment
    assert sqlglot.parse_one(body, read=dialect)
    assert _format(body, dialect) == body.strip()


@pytest.mark.parametrize("gid,query", sorted(GOLDEN_QUERIES.items()))
def test_every_generated_file_carries_the_exact_source_query(gid, query):
    assert (ROOT / "sql" / f"{gid}.MCW.sql").read_text().startswith(f"-- Query: {query}\n")
    py = (ROOT / "python" / f"{gid}.MCW.py").read_text()
    assert py.startswith(f"# Query: {query}\n")
    assert "# n1 select" in py  # per-statement comment mapping back to the AST node


def test_header_collapses_newlines_in_the_query():
    low = lower(parse("total freight cost\nby carrier", TODAY), "MCW", AstTarget.SQL, "t")
    sql = generate_sql(low.ast, "total freight cost\nby carrier", "sqlite").text
    assert sql.startswith("-- Query: total freight cost by carrier\n")


@pytest.mark.parametrize("dialect", ["sqlite", "duckdb", "postgres"])
def test_time_buckets_use_each_dialects_own_function(dialect):
    gran_fn = {"sqlite": "STRFTIME", "duckdb": "STRFTIME", "postgres": "TO_CHAR"}[dialect]
    plant = {"sqlite": "MCW", "duckdb": "YCW", "postgres": "MCW"}[dialect]
    low = lower(parse("monthly weight trend", TODAY), plant, AstTarget.SQL, "t")
    assert gran_fn in generate_sql(low.ast, "q", dialect).text


def test_reserved_words_and_quote_characters_are_handled():
    hints = CodegenHints()
    assert quote("select", hints) == '"select"' and quote("order", hints) == '"order"'
    assert quote("carrier", hints) == "carrier"
    assert quote("carrier", CodegenHints(quote_all_identifiers=True)) == '"carrier"'
    assert quote('we"ird', CodegenHints(quote_all_identifiers=True)) == '"we""ird"'
    assert literal("O'Brien") == "'O''Brien'" and literal(True) == "TRUE" and literal(2.5) == "2.5"


def test_quote_all_hint_produces_valid_sql_with_the_same_answer(databases):
    from sandbox.runner import run_sql

    low = lower(parse("total freight cost by carrier", TODAY), "MCW", AstTarget.SQL, "t")
    plain = generate_sql(low.ast, "q", "sqlite").text
    quoted = generate_sql(low.ast, "q", "sqlite", CodegenHints(quote_all_identifiers=True)).text
    assert plain != quoted and '"carrier"' in quoted
    a = run_sql(PROFILES[Plant.MCW], databases[Plant.MCW], plain)
    b = run_sql(PROFILES[Plant.MCW], databases[Plant.MCW], quoted)
    assert a.equals(b)


def test_sql_refuses_what_it_cannot_express_instead_of_guessing():
    low = lower(parse("forecast freight cost next 2 months", TODAY), "MCW", AstTarget.SQL, "t")
    assert all(n.op.value != "forecast" for n in low.ast.nodes)  # forecast happens after the merge
    from ast_.lowering import ir_to_ast
    from dag.builder import intent_to_dag
    from graph_eng.optimize import optimize
    from ir.adapters import to_plant_ir
    from ir.lowering import dag_to_ir

    dag = optimize(intent_to_dag(parse("forecast freight cost next 2 months", TODAY), "t", True))
    ast_doc = ir_to_ast(to_plant_ir(dag_to_ir(dag), "MCW"), AstTarget.SQL)
    with pytest.raises(UnsupportedAstError, match="forecast"):
        generate_sql(ast_doc, "q", "sqlite")
    py = generate_python(ir_to_ast(to_plant_ir(dag_to_ir(dag), "MCW"), AstTarget.PYTHON), "q")
    assert "_linear_forecast" in py.text


def test_generation_is_deterministic():
    low = lower(parse("average TAT by carrier in August", TODAY), "YCW", AstTarget.SQL, "t")
    first = generate_sql(low.ast, "q", "duckdb").text
    assert all(generate_sql(low.ast, "q", "duckdb").text == first for _ in range(20))


def test_template_selection_failure_is_loud():
    from cag.templates import TemplateNotFoundError

    with pytest.raises(TemplateNotFoundError):
        select_template("bucket", "python", granularity="decade")


@pytest.mark.parametrize("gid,query", sorted(GOLDEN_QUERIES.items()))
def test_python_and_sql_targets_agree_on_every_golden_query(databases, gid, query):
    from pipeline import answer

    a = answer(query, databases, today=TODAY, confirmed=True, target=AstTarget.SQL)
    b = answer(query, databases, today=TODAY, confirmed=True, target=AstTarget.PYTHON)
    assert a.status == b.status == "ok", (a.message, b.message)
    assert a.frame is not None and b.frame is not None
    assert list(a.frame.columns) == list(b.frame.columns)
    num = a.frame.select_dtypes("number").columns
    assert a.frame.drop(columns=num).equals(b.frame.drop(columns=num))
    assert a.frame[num].to_numpy() == pytest.approx(b.frame[num].to_numpy())
