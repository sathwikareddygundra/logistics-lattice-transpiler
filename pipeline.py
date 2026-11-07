"""End-to-end orchestration: NL query -> per-plant code -> sandboxed results -> merged answer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from ast_.lowering import ir_to_ast
from ast_.nodes import AstTarget
from codegen.common import CodegenHints, GeneratedCode
from codegen.python import generate_python
from codegen.sql import generate_sql
from confirm.router import CONFIDENCE_THRESHOLD, route
from dag.builder import intent_to_dag
from ir.adapters import to_plant_ir
from ir.lowering import dag_to_ir
from logging_config import new_trace_id, stage_span
from nlu.fallback import decline, log_fallback
from nlu.intent import IntentType, ParsedIntent
from nlu.parser import parse
from nlu.slots import next_question
from plan.federation import Branch, merge, plan_branches
from plantdb.plants import Plant, get_profile
from sandbox.runner import SandboxError, run_python, run_sql


@dataclass
class BranchRun:
    plant: str
    variant: str
    code: str = ""
    error: str = ""
    error_stage: str = ""
    ms: float = 0.0


@dataclass
class PipelineResult:
    status: str  # ok | partial | needs_slot | needs_confirmation | out_of_scope | failed
    trace_id: str
    intent: ParsedIntent
    message: str = ""
    frame: pd.DataFrame | None = None
    branches: list[BranchRun] = field(default_factory=list)

    @property
    def code(self) -> dict[str, str]:
        return {f"{b.plant}/{b.variant}": b.code for b in self.branches if b.code}


def generate_branch_code(
    intent: ParsedIntent,
    plant: str,
    target: AstTarget,
    trace_id: str,
    hints: CodegenHints | None = None,
) -> GeneratedCode:
    with stage_span("dag", trace_id, plant=plant):
        dag = intent_to_dag(intent, trace_id)
    with stage_span("ir", trace_id, plant=plant):
        ir = to_plant_ir(dag_to_ir(dag), plant)
    with stage_span("ast", trace_id, plant=plant):
        tree = ir_to_ast(ir, target)
    with stage_span("codegen", trace_id, plant=plant):
        profile = get_profile(plant)
        if target is AstTarget.SQL:
            return generate_sql(tree, intent.query, profile.dialect, hints)
        return generate_python(tree, intent.query, profile.dialect, hints)


def run_branch(
    branch: Branch, db: Path | str, target: AstTarget, trace_id: str
) -> tuple[pd.DataFrame, GeneratedCode]:
    code = generate_branch_code(branch.intent, branch.plant, target, trace_id)
    profile = get_profile(branch.plant)
    with stage_span("sandbox", trace_id, plant=branch.plant):
        if target is AstTarget.SQL:
            frame = run_sql(profile, db, code.text)
        else:
            frame = run_python(profile, db, code.text)
    return frame, code


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
) -> PipelineResult:
    trace_id = trace_id or new_trace_id()

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
    for branch in plan_branches(intent, plants):
        run = BranchRun(branch.plant, branch.variant)
        start = time.perf_counter()
        try:
            frame, code = run_branch(branch, databases[Plant(branch.plant)], target, trace_id)
            run.code = code.text
            frames[(branch.plant, branch.variant)] = frame
        except (SandboxError, ValueError, KeyError) as exc:
            run.error = str(exc)
            run.error_stage = getattr(exc, "stage", "codegen")
            failed_plants.add(branch.plant)
        run.ms = round((time.perf_counter() - start) * 1000, 2)
        runs.append(run)

    # a plant with any failed variant is dropped entirely (a half-computed average would be wrong)
    frames = {k: v for k, v in frames.items() if k[0] not in failed_plants}
    if not frames:
        return PipelineResult(
            "failed", trace_id, intent, runs[0].error if runs else "no branches", None, runs
        )
    with stage_span("merge", trace_id):
        result = merge(intent, frames)
    status = "partial" if failed_plants else "ok"
    msg = f"plants failed: {sorted(failed_plants)}" if failed_plants else decision.paraphrase
    return PipelineResult(status, trace_id, intent, msg, result, runs)
