import json
import re
import sqlite3
from pathlib import Path

import duckdb
import pytest

from ops import alerts, drift, metrics, rollout

ROOT = Path(__file__).resolve().parents[2]


def healthy(**over):
    s = {
        "queries_total": 500,
        "failures_total": 0,
        "failures_by_category": {},
        "stage_latency_ms": {"sandbox": {"p95": 100.0}},
        "row_count_mismatches": 0,
    }
    return {**s, **over}


# --- metrics -----------------------------------------------------------------
def test_unknown_failure_category_rejected():
    with pytest.raises(ValueError):
        metrics.Registry().record_failure("made_up")


def test_snapshot_and_quantiles():
    r = metrics.Registry()
    for ms in (1, 2, 3, 400):
        r.observe_stage("codegen", ms)
    for _ in range(3):
        r.record_query("ok")
    r.record_query("failed")
    r.record_failure("timeout")
    r.record_confirm()
    s = r.snapshot()
    assert s["queries_total"] == 4 and s["failures_by_category"] == {"timeout": 1}
    assert s["stage_latency_ms"]["codegen"]["p50"] == 5
    assert s["stage_latency_ms"]["codegen"]["p99"] == 500
    assert s["confirm_triggered"] == 1


def test_counter_rejects_negative():
    with pytest.raises(ValueError):
        metrics.Counter("x").inc(-1)


SAMPLE = re.compile(
    r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{([a-zA-Z_][a-zA-Z0-9_]*="[^"]*"(,|(?=\})))*\})? -?[0-9.e+]+(Inf)?$'
)


def test_prometheus_output_parses():
    r = metrics.Registry()
    r.observe_stage("nlu", 12)
    r.record_query("ok")
    r.record_failure("schema_drift")
    text = r.render_prometheus()
    assert text.endswith("\n")
    for line in text.splitlines():
        assert line.startswith("# HELP ") or line.startswith("# TYPE ") or SAMPLE.match(line), line
    assert 'lattice_stage_latency_ms_bucket{stage="nlu",le="+Inf"} 1' in text
    assert 'lattice_failures_total{category="schema_drift"} 1' in text


def test_metrics_are_thread_safe():
    import threading

    c = metrics.Counter("t")
    ts = [threading.Thread(target=lambda: [c.inc() for _ in range(1000)]) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert c.value() == 8000


# --- rollout -----------------------------------------------------------------
def test_may_advance_healthy_and_each_blocker():
    assert rollout.may_advance(healthy(), "MCW") == (True, [])
    ok, why = rollout.may_advance(healthy(queries_total=10), "MCW")
    assert not ok and "only 10 queries" in why[0]
    assert not rollout.may_advance(healthy(failures_total=50), "YCW")[0]
    assert not rollout.may_advance(
        healthy(stage_latency_ms={"nlu": {"p95": rollout.MAX_P95_MS + 1}}), "VGU"
    )[0]
    assert not rollout.may_advance(healthy(row_count_mismatches=1), "MCW")[0]
    with pytest.raises(ValueError):
        rollout.may_advance(healthy(), "XXX")


def test_rollout_doc_states_every_constant():
    doc = (ROOT / "docs/rollout-plan.md").read_text()
    for needle in (
        str(rollout.MIN_QUERIES),
        f"{rollout.MAX_FAILURE_RATE:.0%}",
        f"{rollout.MAX_P95_MS} ms",
        f"{rollout.ROW_COUNT_MISMATCH_FACTOR}x",
    ):
        assert needle in doc, needle
    order = [doc.index(p) for p in rollout.ROLLOUT_ORDER]
    assert order == sorted(order)


# --- alerts ------------------------------------------------------------------
def test_alert_fires_over_threshold_not_under():
    over = int(500 * rollout.MAX_FAILURE_RATE) + 1
    under = int(500 * rollout.MAX_FAILURE_RATE)  # exactly at the limit: not above it
    assert [a.name for a in alerts.evaluate(healthy(failures_total=over))] == ["HighFailureRate"]
    assert alerts.evaluate(healthy(failures_total=under)) == []


def test_latency_drift_and_mismatch_alerts():
    slow = healthy(stage_latency_ms={"sandbox": {"p95": rollout.MAX_P95_MS + 1}})
    assert [a.name for a in alerts.evaluate(slow)] == ["SlowStage"]
    just_ok = healthy(stage_latency_ms={"sandbox": {"p95": rollout.MAX_P95_MS}})
    assert alerts.evaluate(just_ok) == []
    assert alerts.evaluate(healthy(failures_by_category={"schema_drift": 2}))[0].severity == "page"
    assert alerts.evaluate(healthy(row_count_mismatches=1))[0].severity == "ticket"


# --- drift -------------------------------------------------------------------
def make_sqlite(path, extra=""):
    con = sqlite3.connect(path)
    con.execute(f"create table dispatch (id integer, plant text{extra})")
    con.execute("create table tracking (id integer, status text)")
    con.commit()
    con.close()


def test_sqlite_fingerprint_deterministic_and_drift(tmp_path):
    make_sqlite(tmp_path / "prod.db")
    make_sqlite(tmp_path / "stg.db")
    prod = drift.schema_fingerprint(tmp_path / "prod.db", "sqlite")
    assert prod == drift.schema_fingerprint(tmp_path / "stg.db", "sqlite")
    assert drift.fingerprint_hash(prod) == drift.fingerprint_hash(prod)
    assert not drift.check_drift(prod, prod).drifted
    assert drift.alert_on_drift(prod, prod) is None

    con = sqlite3.connect(tmp_path / "stg.db")
    con.execute("alter table dispatch add column weight real")
    con.commit()
    con.close()
    stg = drift.schema_fingerprint(tmp_path / "stg.db", "sqlite")
    r = drift.check_drift(prod, stg, max_lag=1)
    assert r.added == ["dispatch.weight"] and r.drifted and not r.exceeds_lag
    assert drift.alert_on_drift(prod, stg, max_lag=1) is None  # within allowed lag
    alert = drift.alert_on_drift(prod, stg, max_lag=0)
    assert alert and "dispatch.weight" in alert.message


def test_removed_and_changed_columns():
    prod = {"t": {"a": "TEXT", "b": "INTEGER"}}
    stg = {"t": {"a": "INTEGER"}}
    r = drift.check_drift(prod, stg)
    assert r.removed == ["t.b"] and r.changed == ["t.a"]


def test_duckdb_fingerprint(tmp_path):
    p = tmp_path / "a.duckdb"
    con = duckdb.connect(str(p))
    con.execute("create table ycw_dispatch (id integer, plant varchar)")
    con.close()
    fp = drift.schema_fingerprint(p, "duckdb")
    assert fp == {"ycw_dispatch": {"id": "INTEGER", "plant": "VARCHAR"}}
    with pytest.raises(ValueError):
        drift.schema_fingerprint(p, "oracle")


# --- dashboard and runbook ---------------------------------------------------
def test_dashboard_only_uses_emitted_metrics():
    d = json.loads((ROOT / "ops/grafana/lattice-dashboard.json").read_text())
    exprs = [t["expr"] for p in d["panels"] for t in p["targets"]]
    emitted = {
        metrics.STAGE_LATENCY,
        metrics.QUERIES_TOTAL,
        metrics.CONFIRM_TRIGGERED,
        metrics.FAILURES_TOTAL,
    }
    used = set()
    for e in exprs:
        used |= set(re.findall(r"lattice_[a-z_]+", e))
    assert used
    for name in used:
        assert re.sub(r"_(bucket|sum|count)$", "", name) in emitted, name
    text = " ".join(exprs)
    for c in metrics.FAILURE_CATEGORIES:
        assert c in text


def test_runbook_has_one_nonempty_entry_per_category():
    doc = (ROOT / "docs/runbook.md").read_text()
    heads = re.findall(r"^## (\w+)$", doc, re.M)
    assert sorted(heads) == sorted(metrics.FAILURE_CATEGORIES)
    sections = re.split(r"^## ", doc, flags=re.M)[1:]
    for s in sections:
        for label in ("Symptom", "Likely causes", "Diagnosis", "Remediation", "Escalation"):
            m = re.search(rf"\*\*{label}:\*\*\s*(\S.*)", s)
            assert m, (s.split()[0], label)
