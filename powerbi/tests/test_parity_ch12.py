"""Chapter 12 (Airline Operations, derived from the Chapter 15 base): source-side parity and the PBIP's coverage.

Chapter 12 has no Section Access, so its model is unreduced, and it builds Aircraft Types from CSVs in the script.
"""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_tmdl
from engine import SourceModel

APP = "Chapter12__Solution_Chapter 12_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter12_Airline_Operations"
SM = PBIP / "Chapter12_Airline_Operations.SemanticModel" / "definition"
DEP = "# Departures Performed"


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def flights():
    return pd.read_parquet(PARQUET / "Data Files/QVDs/Flight Data.parquet",
                           columns=["Period", DEP, "Carrier Name", "From - To State Code"])


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def _total(expected, kpi):
    rows = _results(expected, kpi)["total"]
    return rows[0][0] if rows else None


def test_every_kpi_evaluated_and_model_matches_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 85 and all(k["status"] == "ok" for k in expected["kpis"])
    assert len(expected["model_tables"]) == 13
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])


@pytest.mark.needs_parquet
def test_aircraft_types_reproduce_the_stored_transformed_qvd():
    # The script STOREs [Aircraft Types] into Data Files\QVDs\Aircraft Types Transformed.qvd.
    built = SourceModel(APP).con.execute('SELECT * FROM "Aircraft Types"').df()
    stored = pd.read_parquet(PARQUET / "Data Files/QVDs/Aircraft Types Transformed.parquet")
    key = "%Aircraft Type ID"
    stored["Aircraft Begin Date"] = pd.to_datetime(stored["Aircraft Begin Date"])
    pd.testing.assert_frame_equal(built.sort_values(key).reset_index(drop=True)[list(stored.columns)],
                                  stored.sort_values(key).reset_index(drop=True), check_dtype=False)


@pytest.mark.needs_parquet
def test_main_data_is_unreduced(flights):
    q = SourceModel(APP).con.execute
    assert q('SELECT count(*) FROM "Main Data"').fetchone()[0] == len(flights) + 2688
    assert q('SELECT count(*) FROM "Main Data" WHERE "# Equivalent FTEs" IS NOT NULL').fetchone()[0] == 2688


@pytest.mark.needs_parquet
def test_flight_and_point_in_time_kpis_match_pandas(expected, flights):
    by_period = flights.groupby("Period")[DEP].sum()
    ytd, ly = by_period[by_period.index // 100 == 2011].sum(), by_period[by_period.index // 100 == 2010].sum()
    assert _total(expected, "CH01#1") == flights[DEP].sum()
    assert _total(expected, "CH65#1") == ytd
    assert _total(expected, "CH60#1") == pytest.approx(ytd / ly - 1, rel=1e-12)
    assert _total(expected, "CH61#1") == pytest.approx(by_period[201112] / by_period[201012] - 1, rel=1e-12)
    assert _total(expected, "CH62#1") == pytest.approx(by_period[201112] / by_period[201111] - 1, rel=1e-12)
    assert {r[0]: r[1] for r in _results(expected, "CH66#1")["Period"]} == {int(p): float(v) for p, v in by_period.items()}
    assert _results(expected, "CH46#1") == {"total": [], "Carrier Group": []}  # no Metric Name selected


@pytest.mark.needs_parquet
def test_calculated_dimension_buckets_match_pandas(expected, flights):
    employment = pd.read_parquet(PARQUET / "Data Files/QVDs/T_F41SCHEDULE_P1A_EMP.parquet", columns=["Carrier Name"])
    # Unreduced model: carriers with only employment rows have no states and fall in the lowest band.
    states = pd.concat([flights, employment]).groupby("Carrier Name")["From - To State Code"].nunique()
    lo = states // 100 * 100
    bands = (lo.astype(str) + "  -  " + (lo + 100).astype(str)).value_counts()
    res = _results(expected, "CH52#1")
    assert {r[0]: r[1] for r in next(v for k, v in res.items() if k != "total")} == bands.to_dict()


def test_pbip_covers_every_kpi_without_section_access(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m.get("keys", [])}
    assert {k["parity_key"] for k in expected["kpis"]} == keys
    calc = {k for c in model["columns"] for k in c.get("keys", [])}
    assert {harness.parity_key(d) for k in expected["kpis"] for d in k["dims"] if d.startswith("=")} <= calc
    assert not list((SM / "roles").glob("*.tmdl")) and "ref role" not in (SM / "model.tmdl").read_text()
    tables = {f.stem for f in (SM / "tables").glob("*.tmdl")}
    assert "INLFED" in tables and "INLFED-1" not in tables
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert queries["unmapped"] == [] and queries.get("role") is None
    assert len(queries["queries"]) == sum(len(k["results"]) for k in expected["kpis"])
    dax = (SM / "tables" / "Main Data.tmdl").read_text() + json.dumps(queries)
    assert "Levels" not in re.findall(r"VAR (\w+)", dax) and "INLFED-1" not in dax


def test_report_pages_rebuild_list_boxes_as_slicers():
    report = json.loads((PBIP / "Chapter12_Airline_Operations.Report" / "report.json").read_text())
    pages = {s["displayName"]: [json.loads(v["config"]) for v in s["visualContainers"]] for s in report["sections"]}
    assert len(pages) == 13 and len(pages["Dashboard"]) == 7
    model = read_tmdl(PBIP)
    fields = {(c["table"], c["name"]) for c in model["columns"]}
    for visuals in pages.values():
        for v in visuals:
            assert v["singleVisual"]["visualType"] == "slicer"
            (sel,) = v["singleVisual"]["prototypeQuery"]["Select"]
            entity = v["singleVisual"]["prototypeQuery"]["From"][0]["Entity"]
            assert (entity, sel["Column"]["Property"]) in fields
            title = v["singleVisual"]["vcObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"]
            assert title == "'" + sel["Column"]["Property"].replace("'", "''") + "'"
