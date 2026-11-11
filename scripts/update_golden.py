"""Regenerates every golden file under tests/golden/. Review the git diff before committing.

Usage: PYTHONPATH=. uv run python scripts/update_golden.py
"""

import json
import tempfile
from datetime import date
from pathlib import Path

import structlog

from ast_.nodes import AstTarget
from ast_.pretty import render_ast
from codegen.python import generate_python
from codegen.sql import generate_sql
from dag.serialization import to_json
from ir.pretty import render_ir
from nlu.parser import parse
from pipeline import answer, lower
from plan.federation import plan_branches
from plantdb.plants import PROFILES, Plant, build_plant_databases
from tests.golden_queries import GOLDEN_QUERIES, GOLDEN_TODAY

ROOT = Path(__file__).resolve().parent.parent / "tests" / "golden"
TRACE = "golden-trace"


def golden_files() -> dict[str, str]:
    """relative path -> expected content, for every golden artifact."""
    today = date(*GOLDEN_TODAY)
    out: dict[str, str] = {}
    for gid, query in GOLDEN_QUERIES.items():
        intent = parse(query, today)
        branch = plan_branches(intent, [p.value for p in Plant])[0].intent
        dag = lower(branch, "MCW", AstTarget.SQL, TRACE).dag
        out[f"dag/{gid}.json"] = to_json(dag)
        for plant, profile in PROFILES.items():
            ir = lower(branch, plant.value, AstTarget.SQL, TRACE).ir
            out[f"ir/{gid}.{plant.value}.txt"] = render_ir(ir)
            sql_ast = lower(branch, plant.value, AstTarget.SQL, TRACE).ast
            out[f"sql/{gid}.{plant.value}.sql"] = generate_sql(sql_ast, query, profile.dialect).text
            py_ast = lower(branch, plant.value, AstTarget.PYTHON, TRACE).ast
            out[f"python/{gid}.{plant.value}.py"] = generate_python(py_ast, query).text
        out[f"ast/{gid}.sql.txt"] = render_ast(lower(branch, "MCW", AstTarget.SQL, TRACE).ast)
        out[f"ast/{gid}.python.txt"] = render_ast(lower(branch, "MCW", AstTarget.PYTHON, TRACE).ast)
    return out


def golden_results(databases: dict) -> dict[str, str]:
    today = date(*GOLDEN_TODAY)
    out = {}
    for gid, query in GOLDEN_QUERIES.items():
        res = answer(query, databases, today=today, confirmed=True, trace_id=TRACE)
        frame = res.frame
        assert frame is not None, (gid, res.message)
        rounded = frame.round(4).astype(object).where(frame.notna(), None)
        out[f"results/{gid}.json"] = (
            json.dumps(
                {"query": query, "columns": list(frame.columns), "rows": rounded.values.tolist()},
                indent=1,
                default=str,
            )
            + "\n"
        )
    return out


if __name__ == "__main__":
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(50))
    dbs = build_plant_databases(tempfile.mkdtemp())
    files = {**golden_files(), **golden_results(dbs)}
    for rel, content in files.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print(len(files), "golden files written to", ROOT)
