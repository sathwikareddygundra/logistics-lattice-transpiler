"""Conditions on the result: HAVING-style thresholds and "more than the average"."""

from datetime import date

import pandas as pd
import pytest

from nlu.parser import parse
from pipeline import answer
from plantdb.plants import DEFAULT_SOURCE_DIR, build_plant_databases

TODAY = date(2026, 9, 15)


@pytest.fixture(scope="module")
def dbs(tmp_path_factory):
    return build_plant_databases(tmp_path_factory.mktemp("having"))


@pytest.fixture(scope="module")
def dispatch() -> pd.DataFrame:
    d = pd.read_csv(DEFAULT_SOURCE_DIR / "Dispatch_Data.csv")
    d.columns = [c.lower() for c in d.columns]
    return d


def ask(dbs, q):
    res = answer(q, dbs, today=TODAY, confirmed=True)
    assert res.status == "ok", res.message
    return res.frame


def test_parser_reads_count_threshold():
    i = parse("carriers with more than 500 shipments", TODAY)
    assert (i.metric, i.agg.value, i.group_by) == ("invoice_number", "count", ["carrier"])
    assert (i.having[0].operator.value, i.having[0].value) == ("gt", 500.0)


def test_parser_reads_average_threshold_with_synonyms():
    i = parse("depots whose average dock time to load is over 90 minutes", TODAY)
    assert (i.metric, i.agg.value, i.group_by) == ("loading_time_mins", "avg", ["origin_warehouse"])
    assert i.having[0].value == 90.0


def test_parser_reads_relative_average():
    i = parse("which transporters charge more than the average haulage fees", TODAY)
    assert (i.metric, i.agg.value, i.group_by) == ("freight_cost_usd", "avg", ["carrier"])
    assert i.having[0].relative_to == "overall_avg"


def test_plain_questions_have_no_condition():
    assert not parse("average freight cost by carrier", TODAY).having
    assert not parse("top 5 carriers by freight cost", TODAY).having
    assert not parse("average freight cost last 3 months", TODAY).having


def test_count_threshold_matches_pandas(dbs, dispatch):
    counts = dispatch.carrier.value_counts()
    got = ask(dbs, "carriers with more than 2000 shipments")
    assert set(got.carrier) == set(counts[counts > 2000].index)
    got = ask(dbs, "carriers with fewer than 2000 shipments")
    assert set(got.carrier) == set(counts[counts < 2000].index)


def test_average_comparison_matches_pandas(dbs, dispatch):
    by_carrier = dispatch.groupby("carrier").freight_cost_usd.mean()
    want = set(by_carrier[by_carrier > dispatch.freight_cost_usd.mean()].index)
    got = ask(dbs, "which transporters charge more than the average haulage fees")
    assert set(got.carrier) == want


def test_row_level_average_comparison(dbs, dispatch):
    got = ask(dbs, "show shipments to Boston that cost more than the average shipping cost")
    avg = dispatch.freight_cost_usd.mean()
    assert len(got) > 0
    assert (got.freight_cost_usd > avg).all()
    assert (got.destination_city == "Boston").all()


def test_row_level_number_threshold(dbs):
    got = ask(dbs, "list all shipments with loading time over 150 minutes")
    assert (got.loading_time_mins > 150).all()


def test_confirm_text_names_the_condition(dbs):
    res = answer("carriers with more than 2000 shipments", dbs, today=TODAY)
    assert "more than 2000" in res.message
    res = answer("list all shipments with loading time over 150 minutes", dbs, today=TODAY)
    assert "more than 150" in res.message
