"""Chapter 06 Airline Operations: source-side parity, the row-count exceptions and the PBIP's coverage."""
import json
from pathlib import Path

import pandas as pd
import pytest

import harness

APP = "Chapter06__Solution_Chapter 6_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter06_Airline_Operations"
MEASURES = {"# Departures Performed": ["CH01#1", "CH02#1"], "# Transported Passengers": ["CH01#2", "CH02#2"],
            "# Transported Freight": ["CH01#3", "CH02#3"], "# Transported Mail": ["CH01#4", "CH02#4"]}
AIRPORTS = {"Origin Airports": (2104, 6209), "Destination Airports": (2169, 6209)}


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok"
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def test_all_kpis_evaluated_and_tables_match_inventory(expected):
    assert expected["status"] == "ok"
    assert [k["kpi"] for k in expected["kpis"]] == [f"CH0{c}#{i}" for c in (1, 2) for i in range(1, 5)]
    for t in expected["model_tables"]:
        want = AIRPORTS.get(t["table"], (t["inventory_rows"], t["inventory_rows"]))
        assert (t["inventory_rows"], t["model_rows"]) == want, t
    assert len(expected["model_tables"]) == 12


@pytest.mark.needs_parquet
def test_kpis_match_independent_pandas(expected):
    df = pd.read_parquet(PARQUET / "Data Files/QVDs/Flight Data.parquet",
                         columns=["Year", "Month", "From - To City", *MEASURES])
    for field, kpis in MEASURES.items():
        for kpi in kpis:
            res = _results(expected, kpi)
            assert res["total"] == [[float(df[field].sum())]]
            if kpi.startswith("CH01"):
                assert {r[0]: r[1] for r in res["Year"]} == \
                    {int(y): float(v) for y, v in df.groupby("Year")[field].sum().items()}
                assert {(r[0], r[1]): r[2] for r in res["Year+Month"]} == \
                    {(int(y), m): float(v) for (y, m), v in df.groupby(["Year", "Month"])[field].sum().items()}
            else:
                by_route = df.groupby("From - To City")[field].sum()
                assert {r[0]: r[1] for r in res["From - To City"]} == {k: float(v) for k, v in by_route.items()}


@pytest.mark.needs_parquet
def test_committed_expected_results_are_reproducible(tmp_path, monkeypatch):
    committed = (harness.EXPECTED / f"{APP}.json.gz").read_bytes()
    monkeypatch.setattr(harness, "EXPECTED", tmp_path)
    harness.write_expected(APP)
    assert (tmp_path / f"{APP}.json.gz").read_bytes() == committed


def test_every_kpi_has_a_dax_query_and_report_uses_model_measures():
    queries = json.loads((harness.DAX / f"{APP}.queries.json").read_text())
    assert not queries["unmapped"]
    assert len(queries["relationships"]) == 11
    tmdl = (PBIP / "Chapter06_Airline_Operations.SemanticModel/definition/tables/Main Data.tmdl").read_text()
    report = json.loads((PBIP / "Chapter06_Airline_Operations.Report/report.json").read_text())
    (page,) = report["sections"]
    assert page["displayName"] == "Dashboard" and len(page["visualContainers"]) == 2
    for vc in page["visualContainers"]:
        for sel in json.loads(vc["config"])["singleVisual"]["prototypeQuery"]["Select"]:
            kind, prop = ("measure", sel["Measure"]["Property"]) if "Measure" in sel else \
                ("column", sel["Column"]["Property"])
            assert f"\t{kind} {prop if prop.isidentifier() else repr(prop)}" in tmdl.replace('"', "'"), prop
