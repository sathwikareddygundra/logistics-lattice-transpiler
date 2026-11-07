"""Updates the live dashboard. Usage:

  python dashboard/update.py set T-17 done|active|partial|pending|blocked ["note"]
  python dashboard/update.py log "message"
  python dashboard/update.py next "step one" "step two" ...
  python dashboard/update.py show

Keeps dashboard/state.json and rewrites dashboard/status.js, which
index.html reloads every couple of seconds.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / "state.json"
STATUS_JS = HERE / "status.js"

PHASES = [
    (1, "Setup", "T-1", "T-8"),
    (2, "Schemas", "T-9", "T-16"),
    (3, "NLU", "T-17", "T-26"),
    (4, "Confirm", "T-27", "T-33"),
    (5, "DAG", "T-34", "T-40"),
    (6, "Graph opt", "T-41", "T-47"),
    (7, "CAG", "T-48", "T-55"),
    (8, "IR", "T-56", "T-62"),
    (9, "AST", "T-63", "T-68"),
    (10, "Python gen", "T-69", "T-74"),
    (11, "SQL gen", "T-75", "T-80"),
    (12, "Sandbox", "T-81", "T-88"),
    (13, "Retry loop", "T-89", "T-93"),
    (14, "Ship it", "T-94", "T-100"),
]

TITLES = """1 Monorepo|2 Dependency manager|3 Branching and PR rules|4 NLU compute decision|5 Groq client|
6 Structured logging|7 CI pipeline|8 Environment configs|9 Inventory source schemas|10 Canonical schema|
11 Schema registry|12 Intent JSON schema|13 DAG JSON schema|14 IR JSON schema|15 AST JSON schema|
16 Schema versioning policy|17 Intent taxonomy|18 NLU approach ADR|19 Entity extraction|20 Slot filling|
21 Confidence scoring|22 Prompt templates|23 Few-shot examples|24 Out-of-scope fallback|25 Labeled dataset + gate|
26 Latency benchmark + SLA|27 Paraphrase template|28 Confirm Groq client|29 Threshold routing|30 Yes/no hook|
31 Re-prompt loop|32 Retry cap|33 Log confirm data|34 DAG data model|35 Intent to DAG|
36 Dependency inference|37 Acyclicity check|38 DAG serialization|39 Multi-plant branches|40 DAG unit tests|
41 Optimization passes|42 Topological sort|43 Cost estimation|44 Join order|45 Predicate push-down|
46 Cross-plant optimization|47 Semantic-equivalence tests|48 CAG boundaries ADR|49 Schema-aware lookup|50 Template library|
51 Template selection|52 Context assembly|53 Cache layer|54 Template versioning|55 CAG determinism proof|
56 IR grammar|57 DAG+CAG to IR|58 IR type-checking|59 IR vs registry|60 Plant IR quirks|
61 IR pretty-printer|62 IR golden tests|63 Target AST|64 IR to AST|65 AST validation|
66 AST optimization|67 AST pretty-printer|68 AST golden tests|69 Python templates|70 AST to Python|
71 Import injection|72 Auto-format Python|73 Query comments (py)|74 Python golden outputs|75 SQL dialects|
76 AST to SQL|77 Dialect quirks|78 Format SQL|79 Query comments (sql)|80 SQL golden outputs|
81 Sandbox environment|82 Static validation|83 Timeout and row limits|84 Error diagnostics|85 Result schema check|
86 Cost sanity check|87 Execution traces|88 Sandbox tests|89 Failure taxonomy|90 Route to codegen|
91 Route to confirm|92 Shared retry budget|93 Log failures|94 End-to-end suite|95 Load testing|
96 Staging + drift alert|97 Rollout plan|98 Dashboards|99 Alert thresholds|100 On-call runbook""".replace("\n", "").split("|")


def initial_state() -> dict:
    tasks = {}
    for item in TITLES:
        num, title = item.split(" ", 1)
        tasks[f"T-{num}"] = {"title": title, "state": "pending", "note": ""}
    done = [f"T-{i}" for i in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 34, 56, 63)]
    partial = {
        "T-3": "branch protection is a GitHub setting, not verified",
        "T-17": "taxonomy merged from older branch, being extended",
        "T-19": "rule-based entities in slice", "T-27": "basic paraphrase in slice",
        "T-29": "threshold routing in slice", "T-35": "linear templates in slice",
        "T-57": "linear lowering in slice", "T-64": "linear lowering in slice",
        "T-70": "pandas generator in slice", "T-76": "SQLite generator in slice",
        "T-81": "read-only connection in slice", "T-83": "timeout/row cap in slice",
    }
    for t in done:
        tasks[t]["state"] = "done"
    for t, note in partial.items():
        tasks[t].update(state="partial", note=note)
    return {"tasks": tasks, "log": [], "next": [], "started": time.time()}


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else initial_state()


def save(state: dict) -> None:
    state["updated"] = time.time()
    STATE.write_text(json.dumps(state, indent=1))
    payload = {**state, "phases": [list(p) for p in PHASES]}
    STATUS_JS.write_text("window.__STATUS = " + json.dumps(payload) + ";\n")


def main(argv: list[str]) -> None:
    state = load()
    cmd = argv[0] if argv else "show"
    if cmd == "set":
        task, new = argv[1], argv[2]
        if task not in state["tasks"]:
            raise SystemExit(f"unknown task {task}")
        if new == "active":  # one active task at a time
            for t in state["tasks"].values():
                if t["state"] == "active":
                    t["state"] = "pending"
        state["tasks"][task]["state"] = new
        if len(argv) > 3:
            state["tasks"][task]["note"] = argv[3]
        state["log"].append({"t": time.time(), "msg": f"{task} -> {new}"})
    elif cmd == "log":
        state["log"].append({"t": time.time(), "msg": argv[1]})
    elif cmd == "next":
        state["next"] = argv[1:]
    state["log"] = state["log"][-40:]
    save(state)
    counts: dict[str, int] = {}
    for t in state["tasks"].values():
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    print(counts)


if __name__ == "__main__":
    main(sys.argv[1:])
