"""End-to-end orchestration: NL query -> code -> sandboxed result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from ast_.lowering import ir_to_ast
from ast_.nodes import AstTarget
from codegen.python import generate_python
from codegen.sql import generate_sql
from confirm.router import route
from dag.builder import intent_to_dag
from ir.lowering import dag_to_ir
from logging_config import new_trace_id, stage_span
from nlu.intent import IntentType, ParsedIntent
from nlu.parser import parse
from sandbox.runner import run_python, run_sql


@dataclass
class PipelineResult:
    status: str  # ok | needs_confirmation | out_of_scope
    trace_id: str
    intent: ParsedIntent
    paraphrase: str = ""
    code: str = ""
    result: pd.DataFrame | None = None


def answer(
    query: str,
    db_path: Path | str,
    target: AstTarget = AstTarget.SQL,
    today: date | None = None,
    confirmed: bool = False,
    trace_id: str | None = None,
) -> PipelineResult:
    trace_id = trace_id or new_trace_id()

    with stage_span("nlu", trace_id):
        intent = parse(query, today)
    if intent.intent_type is IntentType.OUT_OF_SCOPE:
        return PipelineResult("out_of_scope", trace_id, intent, route(intent).paraphrase)

    with stage_span("confirm", trace_id):
        decision = route(intent)
    if decision.needs_confirmation and not confirmed:
        return PipelineResult("needs_confirmation", trace_id, intent, decision.paraphrase)

    with stage_span("dag", trace_id):
        dag = intent_to_dag(intent, trace_id)
    with stage_span("ir", trace_id):
        ir = dag_to_ir(dag)
    with stage_span("ast", trace_id):
        tree = ir_to_ast(ir, target)
    with stage_span("codegen", trace_id):
        if target is AstTarget.SQL:
            code = generate_sql(tree, query)
        else:
            code = generate_python(tree, query)
    with stage_span("sandbox", trace_id):
        run = run_sql if target is AstTarget.SQL else run_python
        result = run(db_path, code)
    return PipelineResult("ok", trace_id, intent, decision.paraphrase, code, result)
