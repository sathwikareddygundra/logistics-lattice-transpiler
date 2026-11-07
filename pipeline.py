"""End-to-end orchestration: NL query -> per-plant code -> sandboxed results -> merged answer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from ast_.lowering import ir_to_ast
from ast_.nodes import AstDocument, AstTarget
from ast_.optimize import optimize_ast
from ast_.validate import validate_ast
from codegen.common import CodegenHints, GeneratedCode
from codegen.python import generate_python
from codegen.sql import generate_sql
from confirm.router import CONFIDENCE_THRESHOLD, route
from dag.builder import intent_to_dag
from dag.model import Dag, NodeType
from feedback import log as failure_log
from feedback.diagnostics import Diagnostic, diagnose
from feedback.router import (
    Attempt,
    GiveUp,
    NeedsConfirmation,
    RetryBudget,
    run_with_retries,
)
from feedback.taxonomy import CATCHABLE
from graph_eng.cost import estimate_rows
from graph_eng.optimize import optimize
from ir.adapters import to_plant_ir
from ir.grammar import Ir
from ir.lowering import dag_to_ir
from ir.registry_check import validate_against_database
from ir.typecheck import assert_well_typed
from logging_config import new_trace_id, stage_span
from nlu.fallback import decline, log_fallback
from nlu.intent import IntentType, ParsedIntent
from nlu.parser import parse
from nlu.slots import next_question
from plan.federation import Branch, merge, plan_branches
from plantdb.plants import Plant, get_profile
from sandbox.cost_check import CostVerdict, check_cost
from sandbox.result_check import check_result
from sandbox.runner import run_python, run_sql


@dataclass
class BranchRun:
    plant: str
    variant: str
    code: str = ""
    error: str = ""
    error_stage: str = ""
    ms: float = 0.0
    attempts: list[Attempt] = field(default_factory=list)
    diagnostic: Diagnostic | None = None
    user_message: str = ""  # human-readable give-up text; `error` keeps the exact diagnosis
    cost: CostVerdict | None = None
    rows: int = 0


@dataclass
class PipelineResult:
    # ok | partial | needs_slot | needs_confirmation | needs_review | out_of_scope | failed
    status: str
    trace_id: str
    intent: ParsedIntent
    message: str = ""
    frame: pd.DataFrame | None = None
    branches: list[BranchRun] = field(default_factory=list)
    budget: RetryBudget = field(default_factory=RetryBudget)

    @property
    def code(self) -> dict[str, str]:
        return {f"{b.plant}/{b.variant}": b.code for b in self.branches if b.code}


@dataclass
class Lowered:
    dag: Dag
    ir: Ir
    ast: AstDocument


def lower(
    intent: ParsedIntent,
    plant: str,
    target: AstTarget,
    trace_id: str,
    db: Path | str | None = None,
) -> Lowered:
    """Intent -> optimized DAG -> typed, plant-adapted IR -> validated, optimized AST.
    Every check that can fail runs here, before any code is generated."""
    with stage_span("dag", trace_id, plant=plant):
        dag = optimize(intent_to_dag(intent, trace_id))
    with stage_span("ir", trace_id, plant=plant):
        ir = to_plant_ir(dag_to_ir(dag), plant)
        assert_well_typed(ir)
        if db is not None:
            validate_against_database(ir, get_profile(plant), db)
    with stage_span("ast", trace_id, plant=plant):
        tree = optimize_ast(ir_to_ast(ir, target))
        validate_ast(tree)
    return Lowered(dag, ir, tree)


def generate_branch_code(
    intent: ParsedIntent,
    plant: str,
    target: AstTarget,
    trace_id: str,
    hints: CodegenHints | None = None,
    db: Path | str | None = None,
) -> GeneratedCode:
    tree = lower(intent, plant, target, trace_id, db).ast
    with stage_span("codegen", trace_id, plant=plant):
        profile = get_profile(plant)
        if target is AstTarget.SQL:
            return generate_sql(tree, intent.query, profile.dialect, hints)
        return generate_python(tree, intent.query, profile.dialect, hints)


def _estimated_output_rows(dag: Dag) -> int:
    out = next(n for n in dag.nodes if n.node_type is NodeType.OUTPUT)
    rows = estimate_rows(dag)[out.id]
    aggregated = any(n.node_type is NodeType.AGGREGATE for n in dag.nodes)
    return rows if aggregated else max(1, rows // len(Plant))  # a plant holds 1/3 of the rows


def run_branch(
    branch: Branch,
    db: Path | str,
    target: AstTarget,
    trace_id: str,
    budget: RetryBudget,
    run: BranchRun,
) -> pd.DataFrame:
    """Generate, validate and execute one plant branch, retrying per feedback/router.py."""
    profile = get_profile(branch.plant)
    stage_of = {"stage": "lowering"}
    cost: list[CostVerdict] = []

    def attempt(tgt: AstTarget, hints: CodegenHints) -> pd.DataFrame:
        stage_of["stage"] = "lowering"
        low = lower(branch.intent, branch.plant, tgt, trace_id, db)
        stage_of["stage"] = "codegen"
        with stage_span("codegen", trace_id, plant=branch.plant):
            if tgt is AstTarget.SQL:
                code = generate_sql(low.ast, branch.intent.query, profile.dialect, hints)
            else:
                code = generate_python(low.ast, branch.intent.query, profile.dialect, hints)
        run.code = code.text
        stage_of["stage"] = "sandbox"
        with stage_span("sandbox", trace_id, plant=branch.plant):
            frame = (
                run_sql(profile, db, code.text)
                if tgt is AstTarget.SQL
                else run_python(profile, db, code.text)
            )
        stage_of["stage"] = "validation"
        check_result(frame, low.ast)
        cost[:] = [check_cost(_estimated_output_rows(low.dag), len(frame))]
        return frame

    def to_diag(exc: BaseException, tgt: AstTarget) -> Diagnostic:
        return diagnose(exc, branch.intent.query, trace_id, stage_of["stage"], branch.plant)

    try:
        frame, run.attempts = run_with_retries(attempt, to_diag, budget, target)
    except (GiveUp, NeedsConfirmation) as exc:
        diags = exc.diagnostics if isinstance(exc, GiveUp) else [exc.diagnostic]
        run.diagnostic = diags[-1]
        raise
    run.cost = cost[0] if cost else None
    run.rows = len(frame)
    return frame


def answer(
    query: str,
    databases: dict[Plant, Path | str],
    today: date | None = None,
    target: AstTarget = AstTarget.SQL,
    confirmed: bool = False,
    trace_id: str | None = None,
    intent: ParsedIntent | None = None,
    threshold: float = CONFIDENCE_THRESHOLD,
    fallback_log: Path | str | None = None,
    budget: RetryBudget | None = None,
    failures_log: Path | str | None = None,
) -> PipelineResult:
    trace_id = trace_id or new_trace_id()
    budget = budget or RetryBudget()

    if intent is None:
        with stage_span("nlu", trace_id):
            intent = parse(query, today)
    if intent.intent_type is IntentType.OUT_OF_SCOPE:
        fb = decline(query)
        if fallback_log is not None:
            log_fallback(query, trace_id, fallback_log)
        return PipelineResult(
            "out_of_scope", trace_id, intent, fb.message + " " + " | ".join(fb.suggestions)
        )
    if question := next_question(intent):
        return PipelineResult("needs_slot", trace_id, intent, question)

    with stage_span("confirm", trace_id):
        decision = route(intent, threshold)
    if decision.needs_confirmation and not confirmed:
        return PipelineResult("needs_confirmation", trace_id, intent, decision.paraphrase)

    plants = [p for p in (intent.plants or [p.value for p in databases]) if Plant(p) in databases]
    runs: list[BranchRun] = []
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    failed_plants: set[str] = set()
    review: list[str] = []
    for branch in plan_branches(intent, plants):
        run = BranchRun(branch.plant, branch.variant)
        runs.append(run)
        start = time.perf_counter()
        try:
            frames[(branch.plant, branch.variant)] = run_branch(
                branch, databases[Plant(branch.plant)], target, trace_id, budget, run
            )
            if run.cost and run.cost.block_promotion:
                review.append(f"{branch.plant}: {run.cost.message}")
        except NeedsConfirmation as exc:
            _log_failure(failures_log, exc.diagnostic, "reopened_confirm", run)
            run.error, run.error_stage = exc.diagnostic.message, exc.diagnostic.category.value
            return PipelineResult(
                "needs_confirmation",
                trace_id,
                intent,
                f"This failed in a way that suggests I misread the question "
                f"({exc.diagnostic.message}). {decision.paraphrase}",
                None,
                runs,
                budget,
            )
        except GiveUp as exc:
            run.error = exc.diagnostics[-1].message
            run.user_message = str(exc)
            run.error_stage = exc.diagnostics[-1].category.value
            failed_plants.add(branch.plant)
            _log_failure(failures_log, exc.diagnostics[-1], "gave_up", run)
        except CATCHABLE as exc:  # not handled by the retry layer
            run.error, run.error_stage = str(exc), getattr(exc, "stage", "execution")
            failed_plants.add(branch.plant)
        else:
            if run.attempts and len(run.attempts) > 1:
                prior = Diagnostic(
                    "retry", _first_category(run), None, run.attempts[0].message, intent.query,
                    trace_id, branch.plant,
                )  # fmt: skip
                _log_failure(failures_log, prior, "recovered", run)
        run.ms = round((time.perf_counter() - start) * 1000, 2)

    # a plant with any failed variant is dropped entirely (a half-computed average would be wrong)
    frames = {k: v for k, v in frames.items() if k[0] not in failed_plants}
    if not frames:
        msg = next((r.user_message or r.error for r in runs if r.error), "no branches")
        return PipelineResult("failed", trace_id, intent, msg, None, runs, budget)
    with stage_span("merge", trace_id):
        result = merge(intent, frames)
    if review:
        return PipelineResult(
            "needs_review",
            trace_id,
            intent,
            "Held for review: " + "; ".join(review),
            result,
            runs,
            budget,
        )
    status = "partial" if failed_plants else "ok"
    msg = f"plants failed: {sorted(failed_plants)}" if failed_plants else decision.paraphrase
    return PipelineResult(status, trace_id, intent, msg, result, runs, budget)


def _first_category(run: BranchRun):
    from feedback.taxonomy import FailureCategory

    return (
        FailureCategory(run.attempts[0].category)
        if run.attempts[0].category
        else FailureCategory.SEMANTIC_MISMATCH
    )


def _log_failure(path: Path | str | None, diag: Diagnostic, outcome: str, run: BranchRun) -> None:
    if path is not None:
        failure_log.record_failure(diag, outcome, len(run.attempts) or 1, path)
