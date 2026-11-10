from datetime import date

import pandas as pd
import pytest
import structlog

from plantdb.plants import DEFAULT_SOURCE_DIR, build_plant_databases

TODAY = date(2026, 9, 15)


@pytest.fixture(autouse=True)
def _reset_logging():
    """A test that configures logging while pytest captures stdout would leave later tests
    writing to a closed stream."""
    yield
    structlog.reset_defaults()


@pytest.fixture(scope="session")
def databases(tmp_path_factory):
    return build_plant_databases(tmp_path_factory.mktemp("plants"))


@pytest.fixture(scope="session")
def truth():
    """The full source data joined on invoice, with canonical lower-case column names."""
    frames = []
    for name in ("Dispatch_Data", "Tracking_Data", "Turn_Around_Time_Data"):
        df = pd.read_csv(DEFAULT_SOURCE_DIR / f"{name}.csv")
        df.columns = [c.lower() for c in df.columns]
        frames.append(df.drop(columns=["dispatch_date"]) if name.startswith("Turn") else df)
    out = frames[0]
    for df in frames[1:]:
        out = out.merge(df, on="invoice_number")
    return out
