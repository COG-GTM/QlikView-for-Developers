"""Chapter 11 Airline Operations (derived from the Chapter 15 base model): source parity and the PBIP's coverage.

The harness's KPI results (DuckDB over models/<app>.sql) are re-derived here with pandas straight from the Parquet of
the original QVDs / CSVs, and the Aircraft Types transformation is checked against the QVD the same tab STOREs.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_tmdl
from engine import SourceModel

APP = "Chapter11__Solution_Chapter 11_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter11_Airline_Operations"
SM = PBIP / "Chapter11_Airline_Operations.SemanticModel" / "definition"
DEP = "# Departures Performed"


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def flights():
    return pd.read_parquet(PARQUET / "Data Files/QVDs/Flight Data.parquet",
                           columns=["%Aircraft Type ID", "Period", DEP, "Carrier Name", "From - To State Code",
                                    "# Transported Passengers", "# Available Seats"])


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def _total(expected, kpi):
    rows = _results(expected, kpi)["total"]
    return rows[0][0] if rows else None


def test_every_kpi_evaluated_and_model_matches_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 66 and all(k["status"] == "ok" for k in expected["kpis"])
    assert len(expected["model_tables"]) == 13
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])


@pytest.mark.needs_parquet
def test_kpis_match_pandas(expected, flights):
    assert _total(expected, "CH01#1") == flights[DEP].sum()
    by_year = flights.groupby(flights["Period"] // 100)[DEP].sum()
    assert {r[0]: r[1] for r in _results(expected, "CH01#1")["Year"]} == {int(y): float(v) for y, v in by_year.items()}
    lf = flights["# Transported Passengers"].sum() / flights["# Available Seats"].sum()
    assert _total(expected, "CH03#3") == pytest.approx(lf, rel=1e-12)
    emp = pd.read_parquet(PARQUET / "Data Files/QVDs/T_F41SCHEDULE_P1A_EMP.parquet")
    assert _total(expected, "CH44#1") == emp["# Equivalent FTEs"].sum()  # no Section Access: Employment rows stay
    assert _results(expected, "CH46#1") == {"total": [], "Carrier Group": []}  # no Metric Name selected
    shares = {r[0]: r[1] for r in _results(expected, "CH43#1")["Carrier Name"]}  # $(vTotalFTEs): selection total
    by_carrier = emp.groupby("Carrier Name")["# Equivalent FTEs"].sum() / emp["# Equivalent FTEs"].sum()
    assert shares == pytest.approx(by_carrier[by_carrier.notna()].to_dict(), rel=1e-12)


@pytest.mark.needs_parquet
def test_calculated_dimension_buckets_match_pandas(expected, flights):
    emp = pd.read_parquet(PARQUET / "Data Files/QVDs/T_F41SCHEDULE_P1A_EMP.parquet", columns=["Carrier Name"])
    rows = pd.concat([flights[["Carrier Name", "From - To State Code"]], emp])  # Employment-only carriers: 0 states
    states = rows.groupby("Carrier Name")["From - To State Code"].nunique()
    lo = states // 100 * 100
    bands = (lo.astype(str) + "  -  " + (lo + 100).astype(str)).value_counts()
    res = _results(expected, "CH52#1")
    assert {r[0]: r[1] for r in next(v for k, v in res.items() if k != "total")} == bands.to_dict()


@pytest.mark.needs_parquet
def test_aircraft_types_match_the_stored_transformed_qvd(flights):
    model = SourceModel(APP)
    mine = model.con.execute('SELECT * FROM "Aircraft Types"').df()
    stored = pd.read_parquet(PARQUET / "Data Files/QVDs/Aircraft Types Transformed.parquet")
    stored = stored[stored["%Aircraft Type ID"].isin(flights["%Aircraft Type ID"])]
    key = "%Aircraft Type ID"
    def norm(df):  # the CSV export reads an empty MANUFACTURER as null, the QVD stores ''
        df = df.sort_values(key).reset_index(drop=True)[list(stored.columns)]
        df["Aircraft Begin Date"] = pd.to_datetime(df["Aircraft Begin Date"]).dt.date
        df = df.astype(object)
        return df.where(df.notna(), "").astype(str)
    assert len(mine) == 180 and mine[key].is_unique
    pd.testing.assert_frame_equal(norm(mine), norm(stored))


def test_pbip_covers_every_kpi_and_calculated_dimension(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m.get("keys", [])}
    assert {k["parity_key"] for k in expected["kpis"]} == keys
    calc = {k for c in model["columns"] for k in c.get("keys", [])}
    assert {harness.parity_key(d) for k in expected["kpis"] for d in k["dims"] if d.startswith("=")} <= calc
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert queries["unmapped"] == [] and "role" not in queries
    assert len(queries["queries"]) == sum(len(k["results"]) for k in expected["kpis"])


def test_model_follows_the_chapter_11_script():
    tables = {f.stem for f in (SM / "tables").glob("*.tmdl")}
    assert {"INLFED", "Aircraft Types", "Master Calendar"} <= tables
    assert not {"INLFED-1", "Group A", "Group B"} & tables  # Chapter 15 only
    assert not (SM / "roles").exists()  # no Section Access
    main = (SM / "tables" / "Main Data.tmdl").read_text()
    assert "SELECTEDVALUE(INLFED[eMetric])" in main and "INLFED-1" not in main
    assert "VAR Levels" not in main
    aircraft = (SM / "tables" / "Aircraft Types.tmdl").read_text()
    assert aircraft.startswith("/// Dimension containing information on aircrafts")  # COMMENT TABLES
    assert "\t/// The number of engines on the aircraft\n\tcolumn 'Aircraft Number Of Engines'" in aircraft
    assert "Aircraft_Base_File.parquet" in aircraft and "Aircraft_Manufacturers.parquet" in aircraft
    report = json.loads((PBIP / "Chapter11_Airline_Operations.Report" / "report.json").read_text())
    pages = {s["displayName"]: [json.loads(v["config"])["singleVisual"] for v in s["visualContainers"]]
             for s in report["sections"]}
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    assert list(pages) == [sh["name"] for sh in manifest["sheets"]]  # one page per sheet
    charts = {json.loads(v["config"])["name"] for s in report["sections"] for v in s["visualContainers"]}
    from scaffold_pbip import tag
    sheet_of = {json.loads(s["config"])["QlikSheet"] for s in report["sections"]}
    for k in harness.kpi_list(manifest):  # every chart of the .qvw is a visual on some page
        oid = k["kpi"].split("#")[0]
        assert any(tag("Chapter11_Airline_Operations", "visual", sh, oid) in charts for sh in sheet_of), oid
    groups = {p: {v["syncGroup"]["groupName"] for v in vs if v["visualType"] == "slicer"} for p, vs in pages.items()}
    assert len(groups["Dashboard"]) == 16 and all(g == groups["Dashboard"] for g in groups.values())  # global selections
    top = [json.loads(v["filters"]) for s in report["sections"] for v in s["visualContainers"] if json.loads(v["filters"])]
    assert len(top) == 1 and top[0][0]["type"] == "TopN"
    assert top[0][0]["filter"]["From"][0]["Expression"]["Subquery"]["Query"]["Top"] == 10
    columns = {(c["table"], c["name"]) for c in read_tmdl(PBIP)["columns"]}
    measures = {m["name"] for m in read_tmdl(PBIP)["measures"]}
    for visuals in pages.values():  # every slicer / chart field exists in the model
        for v in visuals:
            entities = {f["Name"]: f["Entity"] for f in v["prototypeQuery"]["From"]}
            for sel in v["prototypeQuery"]["Select"]:
                kind, ref = next(iter(sel.items()))
                prop, entity = ref["Property"], entities[ref["Expression"]["SourceRef"]["Source"]]
                assert (entity, prop) in columns if kind == "Column" else prop in measures, sel["Name"]
