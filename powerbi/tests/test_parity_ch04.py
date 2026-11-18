"""Chapter 04 parity proof: source KPIs, airport row-count exceptions, PBIP measures and report."""
import json
import re
from pathlib import Path

import pytest
from pyqvd import QvdTable

import build_report
import harness
from harness import parity_key

REPO = Path(__file__).resolve().parents[2]
CH04 = "Chapter04__Solution_Chapter 4_Airline Operations"
PBIP = REPO / "powerbi" / "apps" / "Chapter04_Airline_Operations"
MEASURES = {"# Departures Performed": ["CH01#1", "CH02#1"], "# Transported Passengers": ["CH01#2", "CH02#2"],
            "# Transported Freight": ["CH01#3", "CH02#3"], "# Transported Mail": ["CH01#4", "CH02#4"]}
EXCEPTIONS = {"Origin Airports", "Destination Airports"}


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(CH04)


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok"
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def test_all_ch04_kpis_evaluated(expected):
    assert expected["status"] == "ok"
    assert [k["kpi"] for k in expected["kpis"]] == [f"CH0{c}#{i}" for c in (1, 2) for i in range(1, 5)]
    tables = {m["table"]: m for m in expected["model_tables"]}
    assert len(tables) == 12
    assert all(m["inventory_rows"] == m["model_rows"] for t, m in tables.items() if t not in EXCEPTIONS)


def test_airport_row_differences_are_documented(expected):
    doc = json.loads((REPO / "powerbi" / "inventory" / "row_count_exceptions.json").read_text())
    documented = {(e["table"], e["inventory_rows"], e["parquet_rows"])
                  for e in doc["exceptions"] if re.fullmatch(e["apps"], CH04)}
    diffs = {(m["table"], m["inventory_rows"], m["model_rows"])
             for m in expected["model_tables"] if m["inventory_rows"] != m["model_rows"]}
    assert diffs == documented == {("Origin Airports", 2104, 6209), ("Destination Airports", 2169, 6209)}


def test_every_kpi_has_an_annotated_measure(expected):
    by_key = build_report.measures(PBIP / PBIP.name)
    for k in harness.kpi_list(json.loads((REPO / "powerbi/inventory/manifests" / f"{CH04}.json").read_text()), CH04):
        assert parity_key(k["expression"]) in by_key


def test_report_has_both_sheets_and_charts():
    report = json.loads((PBIP / f"{PBIP.name}.Report" / "report.json").read_text())
    assert [s["displayName"] for s in report["sections"]] == ["Main", "Dashboard"]
    configs = [json.loads(v["config"]) for v in report["sections"][1]["visualContainers"]]
    charts = {c["name"]: c["singleVisual"] for c in configs if c["name"] in ("CH01", "CH02")}
    assert charts["CH01"]["visualType"] == "clusteredColumnChart"
    assert charts["CH02"]["visualType"] == "tableEx"
    top = json.loads(report["sections"][1]["visualContainers"][-1]["filters"])
    assert top[0]["type"] == "TopN" and top[0]["filter"]["From"][0]["Expression"]["Subquery"]["Query"]["Top"] == 10


@pytest.mark.slow
def test_ch04_kpis_match_independent_pandas_on_original_qvd(expected):
    df = QvdTable.from_qvd(str(REPO / "Data Files/QVDs/Flight Data.qvd")).to_pandas()
    for fld, kpis in MEASURES.items():
        for kpi in kpis:
            res = _results(expected, kpi)
            assert res["total"] == [[float(df[fld].sum())]]
            if kpi.startswith("CH01"):
                by_year = df.groupby("Year")[fld].sum()
                assert {r[0]: r[1] for r in res["Year"]} == {int(y): float(v) for y, v in by_year.items()}
            else:
                by_route = df.groupby("From - To City")[fld].sum()
                assert {r[0]: r[1] for r in res["From - To City"]} == {k: float(v) for k, v in by_route.items()}
