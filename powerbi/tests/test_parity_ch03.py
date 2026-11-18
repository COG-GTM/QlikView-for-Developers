"""Chapter 03 parity proof on the source side.

The harness's KPI results (DuckDB over the converted Parquet) must equal the same KPIs
computed independently with pyqvd + pandas straight from the original Flight Data.qvd,
and the committed expected results must be reproducible.
"""
from pathlib import Path

import pytest
from pyqvd import QvdTable

import harness
from conftest import CH03

REPO = Path(__file__).resolve().parents[2]
MEASURES = {"# Departures Performed": ["CH01#1", "CH02#1"], "# Transported Passengers": ["CH01#2", "CH02#2"],
            "# Transported Freight": ["CH01#3", "CH02#3"], "# Transported Mail": ["CH01#4", "CH02#4"]}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(CH03)


@pytest.fixture(scope="module")
def flight_data():
    return QvdTable.from_qvd(str(REPO / "Data Files/QVDs/Flight Data.qvd")).to_pandas()


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok"
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def test_all_ch03_kpis_evaluated(expected):
    assert expected["status"] == "ok"
    assert [k["kpi"] for k in expected["kpis"]] == [f"CH0{c}#{i}" for c in (1, 2) for i in range(1, 5)]
    assert all(k["status"] == "ok" for k in expected["kpis"])
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])


@pytest.mark.slow
def test_ch03_kpis_match_independent_pandas_on_original_qvd(expected, flight_data):
    df = flight_data
    df["MonthName"] = df["Month"].map(lambda m: MONTHS[int(m) - 1])
    for field, kpis in MEASURES.items():
        for kpi in kpis:
            res = _results(expected, kpi)
            assert res["total"] == [[float(df[field].sum())]]
            if kpi.startswith("CH01"):
                by_year = df.groupby("Year")[field].sum()
                assert {r[0]: r[1] for r in res["Year"]} == {int(y): float(v) for y, v in by_year.items()}
                by_ym = df.groupby(["Year", "MonthName"])[field].sum()
                assert {(r[0], r[1]): r[2] for r in res["Year+Month"]} == \
                    {(int(y), m): float(v) for (y, m), v in by_ym.items()}
            else:
                by_route = df.groupby("From - To City")[field].sum()
                assert len(res["From - To City"]) == len(by_route)
                assert {r[0]: r[1] for r in res["From - To City"]} == {k: float(v) for k, v in by_route.items()}


@pytest.mark.needs_parquet
def test_committed_expected_results_are_reproducible(tmp_path, monkeypatch):
    committed = (harness.EXPECTED / f"{CH03}.json.gz").read_bytes()
    monkeypatch.setattr(harness, "EXPECTED", tmp_path)
    harness.write_expected(CH03)
    assert (tmp_path / f"{CH03}.json.gz").read_bytes() == committed
