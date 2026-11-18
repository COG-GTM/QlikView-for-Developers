"""Chapter 14 (Airline Operations, derived from the Chapter 15 base): source-side parity and the PBIP's coverage.

Chapter 14 runs the Chapter 15 script without Section Access, so nothing is reduced: Main Data keeps the Employment
Statistics rows and the PBIP has no roles.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_tmdl
from engine import SourceModel

APP = "Chapter14__Solution_Chapter 14_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter14_Airline_Operations"
SM = PBIP / "Chapter14_Airline_Operations.SemanticModel" / "definition"
DEP = "# Departures Performed"


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def flights():
    return pd.read_parquet(PARQUET / "QVD/Source/Flight Data.parquet", columns=["Period", DEP])


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def _total(expected, kpi):
    rows = _results(expected, kpi)["total"]
    return rows[0][0] if rows else None


def test_every_kpi_evaluated_and_model_matches_unreduced_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 92 and all(k["status"] == "ok" for k in expected["kpis"])
    rows = {m["table"]: (m["inventory_rows"], m["model_rows"]) for m in expected["model_tables"]}
    assert len(rows) == 13 and "INLFED-1" not in rows
    assert all(inv == got for inv, got in rows.values())
    assert {t: rows[t][1] for t in ("Main Data", "Airlines", "Carrier Operating Region", "Origin Markets")} == \
        {"Main Data": 1258763, "Airlines": 337, "Carrier Operating Region": 8, "Origin Markets": 1860}


@pytest.mark.needs_parquet
def test_main_data_is_not_reduced(flights):
    q = SourceModel(APP).con.execute
    assert q('SELECT count(*) FROM "Main Data"').fetchone()[0] == len(flights) + 2688
    assert q('SELECT count(*) FROM "Main Data" WHERE "# Equivalent FTEs" IS NOT NULL').fetchone()[0] > 0


@pytest.mark.needs_parquet
def test_kpis_match_pandas(expected, flights):
    by_period = flights.groupby("Period")[DEP].sum()
    ytd, ly = by_period[by_period.index // 100 == 2011].sum(), by_period[by_period.index // 100 == 2010].sum()
    assert _total(expected, "CH01#1") == flights[DEP].sum()
    assert _total(expected, "CH65#1") == ytd
    assert _total(expected, "CH60#1") == pytest.approx(ytd / ly - 1, rel=1e-12)
    assert _results(expected, "CH69#1")["Carrier Name"]  # Employment rows are visible without Section Access
    assert _results(expected, "CH46#1") == {"total": [], "Carrier Group": []}  # no Metric Name selected
    shares = [r[1] for r in _results(expected, "CH43#1")["Carrier Name"] if r[1] is not None]
    assert len(shares) > 1 and sum(shares) == pytest.approx(1)  # $(vTotalFTEs) is the selection-wide total


def test_pbip_covers_every_kpi_without_roles(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m.get("keys", [])}
    assert {k["parity_key"] for k in expected["kpis"]} <= keys
    calc = {k for c in model["columns"] for k in c.get("keys", [])}
    assert {harness.parity_key(d) for k in expected["kpis"] for d in k["dims"] if d.startswith("=")} <= calc
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert queries["unmapped"] == [] and "role" not in queries
    assert len(queries["queries"]) == sum(len(k["results"]) for k in expected["kpis"])
    assert not (SM / "roles").exists() and "ref role" not in (SM / "model.tmdl").read_text()
    assert "INLFED[eMetric]" in (SM / "tables" / "Main Data.tmdl").read_text()
    assert not (SM / "tables" / "INLFED-1.tmdl").exists()
    assert "VAR Levels" not in json.dumps(queries) + (SM / "tables" / "Main Data.tmdl").read_text()


def test_report_pages_rebuild_list_boxes_as_slicers():
    inv = json.loads((POWERBI / "inventory" / "sheet_objects" / f"{APP}.json").read_text())
    report = json.loads((PBIP / "Chapter14_Airline_Operations.Report" / "report.json").read_text())
    model = json.loads((PBIP / "model.json").read_text())
    assert [s["displayName"] for s in report["sections"]][:3] == ["Dashboard", "Analysis", "Reports"]
    assert len(report["sections"]) == len(inv["sheets"]) == 15
    slicers = [json.loads(v["config"])["singleVisual"] for s in report["sections"] for v in s["visualContainers"]]
    assert all(v["visualType"] == "slicer" for v in slicers)
    dashboard = model["report"][0]["slicers"]
    assert dashboard["LB33"] == "Main Data[Carrier Name]" and dashboard["LB32"] == "Master Calendar[Year]"
    assert model["report"][9]["slicers"]["LB36"] == "INLFED[Metric Name]"
    assert any("LB10 'Aircraft Type', LB11 'Aircraft Group'" in g for g in model["semantic_gaps"])
