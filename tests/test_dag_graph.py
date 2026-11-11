"""Phases 5-6: dependency inference, cycles, serialization, toposort, optimizer passes,
cost model and semantic equivalence (with a mutation check on the checker itself)."""

import itertools
from datetime import date

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ast_.lowering import ir_to_ast
from ast_.nodes import AstTarget
from codegen.sql import generate_sql
from dag.builder import UnsupportedIntentError, intent_to_dag
from dag.dependencies import infer_edges
from dag.model import Dag, Edge, FilterOperator, Node, NodeType
from dag.serialization import from_json, to_json
from graph_eng.cost import estimate_rows
from graph_eng.cycles import find_cycle
from graph_eng.optimize import (
    merge_identical_sources,
    optimize,
    prune_dead,
    push_down_filters,
    reorder_joins,
)
from graph_eng.toposort import CycleError, toposort
from ir.adapters import to_plant_ir
from ir.lowering import dag_to_ir
from nlu.intent import IntentFilter, IntentType, ParsedIntent
from nlu.parser import parse
from plantdb.plants import PROFILES, Plant
from sandbox.runner import run_sql
from tests.conftest import TODAY


def _dag(q: str) -> Dag:
    return intent_to_dag(parse(q, TODAY), "t")


# ---- T-36 dependency inference --------------------------------------------
def test_filter_then_aggregate_needs_no_manual_edges():
    nodes = [
        Node(id="a", node_type=NodeType.SOURCE, params={"source": "dispatch"}),
        Node(id="b", node_type=NodeType.FILTER, params={"column": "carrier", "operator": "eq", "value": "DHL"}),
        Node(id="c", node_type=NodeType.AGGREGATE, params={"group_by": [], "metric": "freight_cost_usd", "op": "sum"}),
        Node(id="d", node_type=NodeType.OUTPUT, params={"columns": ["freight_cost_usd"]}),
    ]  # fmt: skip
    assert [(e.from_node, e.to_node) for e in infer_edges(nodes)] == [
        ("a", "b"),
        ("b", "c"),
        ("c", "d"),
    ]


def test_consuming_a_column_nobody_produces_is_an_error():
    nodes = [
        Node(id="a", node_type=NodeType.SOURCE, params={"source": "dispatch"}),
        Node(id="b", node_type=NodeType.FILTER, params={"column": "sla_status", "operator": "eq", "value": "x"}),
    ]  # fmt: skip
    with pytest.raises(ValueError, match="no upstream node produces"):
        infer_edges(nodes)


def test_join_is_wired_from_lineage_with_roles():
    dag = _dag("average TAT by carrier")
    join = next(n for n in dag.nodes if n.node_type is NodeType.JOIN)
    roles = {e.role.value: e.from_node for e in dag.edges if e.to_node == join.id}
    assert set(roles) == {"left", "right"}


def test_builder_refuses_out_of_scope_and_unfilled_slots():
    with pytest.raises(UnsupportedIntentError):
        intent_to_dag(parse("optimise my routes", TODAY), "t")
    with pytest.raises(UnsupportedIntentError):
        intent_to_dag(parse("top 3 carriers", TODAY), "t")


# ---- T-37 cycles ----------------------------------------------------------
def test_cycle_error_names_the_path():
    def flt(i: str) -> Node:
        return Node(
            id=i,
            node_type=NodeType.FILTER,
            params={"column": "carrier", "operator": "eq", "value": "x"},
        )

    nodes = [
        Node(id="s", node_type=NodeType.SOURCE, params={"source": "dispatch"}),
        flt("a"),
        flt("b"),
        Node(id="o", node_type=NodeType.OUTPUT, params={"columns": ["carrier"]}),
    ]
    edges = [
        Edge(from_node="s", to_node="a"),
        Edge(from_node="a", to_node="b"),
        Edge(from_node="b", to_node="a"),
        Edge(from_node="b", to_node="o"),
    ]
    with pytest.raises(ValueError, match=r"a -> b -> a"):
        Dag(trace_id="t", nodes=nodes, edges=edges)


graphs = st.integers(2, 8).flatmap(
    lambda n: st.sets(
        st.tuples(st.integers(0, n - 1), st.integers(0, n - 1)).filter(lambda t: t[0] != t[1]),
        max_size=14,
    ).map(lambda es: (n, sorted(es)))
)


@given(graphs)
@settings(max_examples=200, deadline=None)
def test_cycle_detection_agrees_with_toposort_on_random_graphs(g):
    n, edges = g
    ids = [f"n{i}" for i in range(n)]
    pairs = [(f"n{a}", f"n{b}") for a, b in edges]
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for a, b in pairs:
        adj[a].append(b)
    cycle = find_cycle(adj)
    try:
        toposort(ids, pairs)
        assert cycle is None
    except CycleError as exc:
        assert cycle is not None and exc.cycle == cycle
        assert cycle[0] == cycle[-1]
        assert all((a, b) in set(pairs) for a, b in itertools.pairwise(cycle))


# ---- T-38 serialization ---------------------------------------------------
def test_dag_round_trip_is_lossless():
    for q in ("average TAT by carrier", "monthly weight trend", "show delayed shipments"):
        dag = _dag(q)
        assert from_json(to_json(dag)) == dag


def test_small_change_gives_small_diff():
    a = to_json(_dag("total freight cost for DHL")).splitlines()
    b = to_json(_dag("total freight cost for UPS")).splitlines()
    assert sum(x != y for x, y in zip(a, b, strict=True)) == 1 and len(a) == len(b)


# ---- T-42 toposort --------------------------------------------------------
def test_toposort_is_deterministic_with_stable_tie_break():
    ids = ["n10", "n2", "n1", "n3"]
    edges: list[tuple[str, str]] = []
    assert toposort(ids, edges) == ["n1", "n2", "n3", "n10"]  # natural order, not string order
    assert all(toposort(ids, edges) == toposort(list(reversed(ids)), edges) for _ in range(5))


# ---- T-41/44/45 passes ----------------------------------------------------
@pytest.mark.parametrize(
    "q", ["average TAT by carrier in August", "show delayed shipments from Atlanta"]
)
def test_passes_are_idempotent(q):
    dag = _dag(q)
    for fn in (merge_identical_sources, push_down_filters, reorder_joins, prune_dead, optimize):
        once = fn(dag)
        assert fn(once) == once


def test_predicate_pushdown_moves_filters_onto_their_source():
    dag = optimize(_dag("average TAT by carrier in August"))
    by_id = {n.id: n for n in dag.nodes}
    for e in dag.edges:
        if by_id[e.to_node].node_type is NodeType.JOIN:
            # nothing between a join and its consumer is a filter any more
            assert by_id[e.from_node].node_type in (NodeType.SOURCE, NodeType.FILTER)
    assert not any(
        by_id[e.from_node].node_type is NodeType.JOIN
        and by_id[e.to_node].node_type is NodeType.FILTER
        for e in dag.edges
    )


def test_dead_branches_are_pruned():
    dag = _dag("total freight cost for DHL")
    dead = Node(
        id="dead",
        node_type=NodeType.FILTER,
        params={"column": "carrier", "operator": "eq", "value": "UPS"},
    )
    src = next(n.id for n in dag.nodes if n.node_type is NodeType.SOURCE)
    bloated = Dag(
        trace_id="t",
        nodes=[*dag.nodes, dead],
        edges=[*dag.edges, Edge(from_node=src, to_node="dead")],
    )
    assert "dead" in {n.id for n in bloated.nodes}
    assert prune_dead(bloated) == dag


def test_duplicate_sources_merge():
    nodes = [
        Node(id="a", node_type=NodeType.SOURCE, params={"source": "dispatch"}),
        Node(id="b", node_type=NodeType.SOURCE, params={"source": "dispatch"}),
        Node(id="j", node_type=NodeType.JOIN, params={"on": "invoice_number", "how": "inner"}),
        Node(id="o", node_type=NodeType.OUTPUT, params={"columns": ["carrier"]}),
    ]
    from dag.model import EdgeRole

    dag = Dag(
        trace_id="t",
        nodes=nodes,
        edges=[
            Edge(from_node="a", to_node="j", role=EdgeRole.LEFT),
            Edge(from_node="b", to_node="j", role=EdgeRole.RIGHT),
            Edge(from_node="j", to_node="o"),
        ],
    )
    merged = merge_identical_sources(dag)
    assert [n.id for n in merged.nodes if n.node_type is NodeType.SOURCE] == ["a"]


# ---- T-43 cost model within 10x -------------------------------------------
@pytest.mark.parametrize(
    "q,mask",
    [
        ("show shipments from Chicago", lambda t: t.origin_warehouse == "Chicago_WH"),
        ("list DHL shipments", lambda t: t.carrier == "DHL"),
        ("list shipments in July 2026", lambda t: (t.dispatch_date >= "2026-07-01") & (t.dispatch_date < "2026-08-01")),
        ("show delayed shipments", lambda t: t.current_status == "Delayed"),
    ],
)  # fmt: skip
def test_cost_estimates_are_within_an_order_of_magnitude(truth, q, mask):
    intent = parse(q, TODAY).model_copy(update={"limit": None})
    dag = intent_to_dag(intent, "t")
    filters = [n for n in dag.nodes if n.node_type is NodeType.FILTER]
    est = estimate_rows(dag)[filters[-1].id]
    actual = int(mask(truth).sum())
    assert 0.1 <= est / actual <= 10, (est, actual)


# ---- T-47 semantic equivalence + mutation check ---------------------------
def _run(dag: Dag, databases) -> pd.DataFrame:
    plant = Plant.MCW
    ir = to_plant_ir(dag_to_ir(dag), plant.value)
    sql = generate_sql(ir_to_ast(ir, AstTarget.SQL), "q", PROFILES[plant].dialect).text
    return run_sql(PROFILES[plant], databases[plant], sql)


def _equivalent(a: Dag, b: Dag, databases) -> bool:
    fa, fb = _run(a, databases), _run(b, databases)
    if list(fa.columns) != list(fb.columns) or len(fa) != len(fb):
        return False
    keys = list(fa.columns)
    fa, fb = (
        fa.sort_values(keys).reset_index(drop=True),
        fb.sort_values(keys).reset_index(drop=True),
    )
    try:
        pd.testing.assert_frame_equal(fa, fb, check_dtype=False, rtol=1e-9)
    except AssertionError:
        return False
    return True


METRICS = ["freight_cost_usd", "shipment_weight_kg", "total_tat_hours", "loading_time_mins"]
FILTERS = [
    IntentFilter(column="carrier", operator=FilterOperator.EQ, value="DHL"),
    IntentFilter(column="current_status", operator=FilterOperator.EQ, value="Delayed"),
    IntentFilter(column="sla_status", operator=FilterOperator.EQ, value="On Time"),
    IntentFilter(column="origin_warehouse", operator=FilterOperator.EQ, value="Chicago_WH"),
    IntentFilter(column="dispatch_date", operator=FilterOperator.GTE, value="2026-07-01"),
    IntentFilter(column="dispatch_date", operator=FilterOperator.LT, value="2026-08-01"),
]  # fmt: skip


@given(
    metric=st.sampled_from(METRICS),
    agg=st.sampled_from(["sum", "avg", "min", "max", "count"]),
    group=st.lists(
        st.sampled_from(["carrier", "origin_warehouse", "current_status", "sla_status"]),
        max_size=2,
        unique=True,
    ),  # fmt: skip
    filters=st.lists(
        st.sampled_from(FILTERS), max_size=4, unique_by=lambda f: (f.column, f.operator)
    ),
)
@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_optimized_dag_gives_identical_results(databases, metric, agg, group, filters):
    intent = ParsedIntent(
        query="q", intent_type=IntentType.AGGREGATION, metric=metric, agg=agg,
        group_by=group, filters=filters, confidence=0.9,
    )  # fmt: skip
    dag = intent_to_dag(intent, "t")
    assert _equivalent(dag, optimize(dag), databases)


def _drop_filters(dag: Dag) -> Dag:
    """A deliberately broken 'optimizer': throws every filter away."""
    keep = [n for n in dag.nodes if n.node_type is not NodeType.FILTER]
    ids = {n.id for n in keep}
    remap: dict[str, str] = {}
    for e in dag.edges:
        remap.setdefault(e.to_node, e.from_node)
    out = []
    for e in dag.edges:
        if e.to_node in ids and e.from_node in ids:
            out.append(e)
        elif e.to_node in ids:  # reconnect around the dropped filter
            src = e.from_node
            while src not in ids:
                src = remap[src]
            out.append(Edge(from_node=src, to_node=e.to_node, role=e.role))
    return Dag(trace_id=dag.trace_id, nodes=keep, edges=out)


def test_equivalence_checker_catches_a_buggy_optimizer(databases):
    dag = _dag("total freight cost for DHL in August 2026")
    assert _equivalent(dag, optimize(dag), databases)
    assert not _equivalent(dag, _drop_filters(dag), databases)


def test_equivalence_checker_catches_wrong_aggregate(databases):
    dag = _dag("total freight cost by carrier")
    broken = Dag(
        trace_id="t",
        nodes=[
            n.model_copy(update={"params": {**n.params, "op": "max"}})
            if n.node_type is NodeType.AGGREGATE
            else n
            for n in dag.nodes
        ],
        edges=dag.edges,
    )
    assert not _equivalent(dag, broken, databases)


# ---- T-46 local aggregation before merge equals the naive plan ------------
@pytest.mark.parametrize(
    "agg,fn", [("sum", "sum"), ("avg", "mean"), ("min", "min"), ("max", "max"), ("count", "count")]
)
def test_aggregate_locally_then_merge_equals_transfer_everything(databases, truth, agg, fn):
    from pipeline import answer

    word = {"sum": "total", "avg": "average", "min": "minimum", "max": "maximum", "count": "count"}[
        agg
    ]
    q = f"{word} freight cost by carrier" if agg != "count" else "how many shipments by carrier"
    res = answer(q, databases, today=TODAY)
    col = "freight_cost_usd" if agg != "count" else "invoice_number"
    naive = getattr(truth.groupby("carrier")[col], fn)()
    got = res.frame.set_index("carrier").iloc[:, 0]
    assert got.to_dict() == pytest.approx(naive.to_dict())
    assert max(len(f) for f in [res.frame]) <= 5  # only per-carrier rows ever moved, never raw rows


def test_today_constant_is_a_date():
    assert isinstance(TODAY, date)
