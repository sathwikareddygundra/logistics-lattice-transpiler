"""Phase 13: failure taxonomy, routing, shared retry budget, failure logging."""

import importlib
import inspect
import json
import pkgutil
import sqlite3

import pytest
import sqlglot

import pipeline
from ast_.nodes import AstTarget
from codegen.common import CodegenHints, UnsupportedAstError
from feedback import log as flog
from feedback.diagnostics import diagnose
from feedback.router import (
    GiveUp,
    NeedsConfirmation,
    RetryBudget,
    next_action,
    run_with_retries,
)
from feedback.taxonomy import REGISTRY, FailureCategory, UnclassifiedFailure, classify
from pipeline import answer
from plantdb.catalog import UnknownColumnError
from plantdb.plants import Plant
from sandbox.runner import SandboxError
from tests.conftest import TODAY

REPO_PACKAGES = [
    "ast_", "cag", "codegen", "common", "confirm", "dag", "feedback", "graph_eng", "ir",
    "nlu", "plan", "plantdb", "sandbox",
]  # fmt: skip
CONTROL_FLOW = {"NeedsConfirmation", "GiveUp", "UnclassifiedFailure", "SandboxError"}


# ---- T-89 ------------------------------------------------------------------------
def _repo_exception_classes() -> set[type[BaseException]]:
    found: set[type[BaseException]] = set()
    for pkg in REPO_PACKAGES:
        mod = importlib.import_module(pkg)
        names = [pkg] + [m.name for m in pkgutil.iter_modules(mod.__path__, pkg + ".")]
        for name in names:
            for _, cls in inspect.getmembers(importlib.import_module(name), inspect.isclass):
                if issubclass(cls, Exception) and cls.__module__.split(".")[0] in REPO_PACKAGES:
                    found.add(cls)
    return found


def test_every_failure_type_in_the_repo_maps_to_exactly_one_category():
    uncovered = [
        c.__name__
        for c in _repo_exception_classes()
        if c.__name__ not in CONTROL_FLOW and not any(issubclass(c, k) for k in REGISTRY)
    ]
    assert uncovered == [], f"register these in feedback/taxonomy.py: {uncovered}"


def test_the_seven_categories_are_the_documented_ones():
    assert {c.value for c in FailureCategory} == {
        "syntax_error", "semantic_mismatch", "intent_mismatch", "timeout",
        "resource_limit", "permission", "schema_drift",
    }  # fmt: skip


@pytest.mark.parametrize(
    "stage,message,category",
    [
        ("timeout", "x", FailureCategory.TIMEOUT),
        ("row_limit", "x", FailureCategory.RESOURCE_LIMIT),
        ("permission", "x", FailureCategory.PERMISSION),
        ("static_validation", "SQL does not parse: boom", FailureCategory.SYNTAX_ERROR),
        (
            "static_validation",
            "only a single SELECT statement is allowed",
            FailureCategory.PERMISSION,
        ),
        ("execution", "no such column: nope", FailureCategory.SCHEMA_DRIFT),
        ("execution", "Table with name x does not exist", FailureCategory.SCHEMA_DRIFT),
        ("execution", "ZeroDivisionError: division by zero", FailureCategory.SEMANTIC_MISMATCH),
    ],
)
def test_sandbox_failures_classify_by_stage_and_message(stage, message, category):
    assert classify(SandboxError(stage, message)) is category


def test_classifier_uses_subclass_matching_and_refuses_unknown_types():
    class MyParse(sqlglot.errors.ParseError):
        pass

    assert classify(MyParse("x")) is FailureCategory.SYNTAX_ERROR
    with pytest.raises(UnclassifiedFailure):
        classify(RuntimeError("who knows"))


def test_diagnostics_carry_stage_node_query_and_trace():
    from ir.typecheck import IrTypeError, TypeIssue

    exc = IrTypeError([TypeIssue("n2", "sum needs a numeric input")])
    d = diagnose(exc, "my query", "trace-9", "lowering", "MCW")
    assert (d.category, d.node, d.stage, d.plant) == (
        FailureCategory.SEMANTIC_MISMATCH, "n2", "lowering", "MCW",
    )  # fmt: skip
    assert d.to_dict()["category"] == "semantic_mismatch"


# ---- T-90 / T-91 routing matrix ---------------------------------------------------
@pytest.mark.parametrize(
    "category,kind",
    [
        (FailureCategory.SYNTAX_ERROR, "retry_codegen"),
        (FailureCategory.SEMANTIC_MISMATCH, "retry_codegen"),
        (FailureCategory.INTENT_MISMATCH, "reopen_confirm"),
        (FailureCategory.TIMEOUT, "stop"),
        (FailureCategory.RESOURCE_LIMIT, "stop"),
        (FailureCategory.PERMISSION, "stop"),
        (FailureCategory.SCHEMA_DRIFT, "stop"),
    ],
)
def test_each_category_routes_to_exactly_one_place(category, kind):
    action = next_action(category, AstTarget.SQL, CodegenHints(), [], RetryBudget())
    assert action.kind == kind


def test_codegen_level_failures_never_reopen_confirm_and_intent_failures_never_retry_codegen():
    for c in (FailureCategory.SYNTAX_ERROR, FailureCategory.SEMANTIC_MISMATCH):
        assert (
            next_action(c, AstTarget.SQL, CodegenHints(), [], RetryBudget()).kind
            != "reopen_confirm"
        )
    assert next_action(
        FailureCategory.INTENT_MISMATCH, AstTarget.SQL, CodegenHints(), [], RetryBudget()
    ).kind == "reopen_confirm"  # fmt: skip


def _fail_once(exc, then=None):
    seen = []

    def attempt(target, hints):
        seen.append((target, hints))
        if len(seen) == 1:
            raise exc
        return "ok"

    return attempt, seen


def _diag(exc, target):
    return diagnose(exc, "q", "t", "codegen")


def test_syntax_retry_visibly_differs_from_the_first_attempt():
    attempt, seen = _fail_once(sqlglot.errors.ParseError("bad sql"))
    result, history = run_with_retries(attempt, _diag, RetryBudget(), AstTarget.SQL)
    assert result == "ok" and len(history) == 2
    assert seen[0][1].quote_all_identifiers is False and seen[1][1].quote_all_identifiers is True
    assert history[0].category == "syntax_error"


def test_semantic_retry_switches_target():
    attempt, seen = _fail_once(UnsupportedAstError("forecast is not supported in sql"))
    _, history = run_with_retries(attempt, _diag, RetryBudget(), AstTarget.SQL)
    assert [s[0] for s in seen] == [AstTarget.SQL, AstTarget.PYTHON]
    assert history[1].target is AstTarget.PYTHON


def test_intent_failure_reopens_confirm_instead_of_retrying():
    attempt, seen = _fail_once(UnknownColumnError("unknown column dispatch.x"))
    with pytest.raises(NeedsConfirmation) as err:
        run_with_retries(attempt, _diag, RetryBudget(), AstTarget.SQL)
    assert len(seen) == 1 and err.value.diagnostic.category is FailureCategory.INTENT_MISMATCH


def test_terminal_categories_are_not_retried():
    attempt, seen = _fail_once(SandboxError("timeout", "too slow"))
    with pytest.raises(GiveUp):
        run_with_retries(attempt, _diag, RetryBudget(), AstTarget.SQL, catch=(SandboxError,))
    assert len(seen) == 1


# ---- T-92 shared budget ----------------------------------------------------------
def test_alternating_failures_still_terminate_within_the_budget():
    """Syntax -> semantic -> syntax -> ... would bounce forever without a hard cap."""
    calls = []
    errors = [
        sqlglot.errors.ParseError("a"),
        UnsupportedAstError("b"),
        sqlglot.errors.ParseError("c"),
    ] * 5

    def attempt(target, hints):
        calls.append((target, hints))
        raise errors[len(calls) - 1]

    budget = RetryBudget(max_total=3)
    with pytest.raises(GiveUp) as err:
        run_with_retries(attempt, _diag, budget, AstTarget.SQL)
    assert len(calls) <= 1 + budget.max_total
    assert "couldn't produce a reliable answer" in str(err.value) and "Traceback" not in str(
        err.value
    )
    assert budget.used <= budget.max_total


def test_one_budget_spans_codegen_retries_and_confirm_reopenings(databases, monkeypatch):
    """The same budget object is shared across calls: intent-level reopenings and codegen
    retries both draw on it, and when it is spent the query ends with a readable failure."""
    budget = RetryBudget(max_total=2)

    def always_unknown_column(*a, **k):
        raise UnknownColumnError("unknown column dispatch.x")

    monkeypatch.setattr(pipeline, "lower", always_unknown_column)
    statuses = [
        answer("total freight cost by carrier", databases, today=TODAY, budget=budget).status
        for _ in range(4)
    ]
    assert statuses[:2] == ["needs_confirmation", "needs_confirmation"]
    assert budget.exhausted
    last = answer("total freight cost by carrier", databases, today=TODAY, budget=budget)
    assert last.status == "failed"
    assert "couldn't produce a reliable answer" in last.message and "Traceback" not in last.message


# ---- integration through the real pipeline ---------------------------------------
def test_pipeline_recovers_from_a_codegen_failure_by_switching_target(databases, monkeypatch):
    baseline = answer("total weight by carrier", databases, today=TODAY).frame
    real = pipeline.generate_sql
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 3:  # first attempt of each plant fails
            raise UnsupportedAstError("sql cannot express this")
        return real(*a, **k)

    monkeypatch.setattr(pipeline, "generate_sql", flaky)
    res = answer("total weight by carrier", databases, today=TODAY, budget=RetryBudget(max_total=5))
    assert res.status == "ok"
    first = res.branches[0]
    assert [a.target for a in first.attempts] == [AstTarget.SQL, AstTarget.PYTHON]
    assert first.code.startswith("# Query")  # the retry produced Python, not SQL
    assert res.frame is not None and baseline is not None
    assert res.frame.sort_values("carrier").reset_index(drop=True).iloc[
        :, 1
    ].to_numpy() == pytest.approx(
        baseline.sort_values("carrier").reset_index(drop=True).iloc[:, 1].to_numpy()
    )


def test_intent_level_failure_in_the_pipeline_goes_back_to_confirm(databases, monkeypatch):
    def boom(*a, **k):
        raise UnknownColumnError("unknown column dispatch.nope")

    monkeypatch.setattr(pipeline, "lower", boom)
    res = answer("total weight by carrier", databases, today=TODAY)
    assert res.status == "needs_confirmation"
    assert "misread the question" in res.message and res.frame is None


# ---- T-93 failure log ------------------------------------------------------------
def test_failures_are_logged_pii_safe_and_queryable_by_category(databases, tmp_path):
    import shutil

    log = tmp_path / "failures.jsonl"
    dst = tmp_path / "mcw.sqlite"
    shutil.copy(databases[Plant.MCW], dst)
    conn = sqlite3.connect(dst)
    conn.execute("ALTER TABLE dispatch RENAME COLUMN carrier TO carrier_name")
    conn.commit()
    conn.close()
    answer("total freight cost by carrier for INV-2026-00042", {**databases, Plant.MCW: dst},
           today=TODAY, failures_log=log)  # fmt: skip
    answer(
        "total freight cost by carrier",
        {**databases, Plant.MCW: dst},
        today=TODAY,
        failures_log=log,
    )
    rows = flog.load(log)
    assert rows and all(r["category"] == "schema_drift" and r["plant"] == "MCW" for r in rows)
    assert "INV-2026-00042" not in log.read_text()
    assert flog.count_by_category(log) == {"schema_drift": len(rows)}
    assert flog.query(log, category="timeout") == []
    assert len(flog.query(log, category="schema_drift")) == len(rows)
    json.loads(log.read_text().splitlines()[0])  # one valid JSON object per line


def test_recovered_failures_are_logged_too(databases, monkeypatch, tmp_path):
    log = tmp_path / "f.jsonl"
    real = pipeline.generate_sql
    state = {"failed": False}

    def once(*a, **k):
        if not state["failed"]:
            state["failed"] = True
            raise sqlglot.errors.ParseError("flaky")
        return real(*a, **k)

    monkeypatch.setattr(pipeline, "generate_sql", once)
    res = answer("total weight", databases, today=TODAY, failures_log=log)
    assert res.status == "ok"
    rows = flog.load(log)
    assert [r["retry_outcome"] for r in rows] == ["recovered"] and rows[0][
        "category"
    ] == "syntax_error"
