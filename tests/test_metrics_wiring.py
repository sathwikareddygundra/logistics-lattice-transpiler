from datetime import date

from ops import metrics
from pipeline import answer


def test_answer_records_query_and_stage_metrics(databases):
    before = metrics.snapshot()
    res = answer(
        "average dispatch to delivery time by plant last month", databases, today=date(2026, 9, 15)
    )
    after = metrics.snapshot()
    assert after["queries_total"] == before["queries_total"] + 1
    assert after["queries_by_status"][res.status] > before["queries_by_status"].get(res.status, 0)
    assert "nlu" in after["stage_latency_ms"]
    assert "lattice_queries_total" in metrics.render_prometheus()
