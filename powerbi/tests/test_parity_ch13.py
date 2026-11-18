"""Chapter 13 (Airline Operations, derived from the Chapter 15 base): source-side parity and the PBIP's coverage.

Same load script as Chapter 15 without its hidden Section Access script, so the model is unreduced: [Main Data]
keeps the Employment Statistics rows. KPI results (DuckDB over models/<app>.sql) are re-derived with pandas from
the Parquet of the original QVDs.
"""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_tmdl
from engine import SourceModel
from scaffold_pbip import tag

APP = "Chapter13__Solution_Chapter 13_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter13_Airline_Operations"
SM = PBIP / "Chapter13_Airline_Operations.SemanticModel" / "definition"
REPORT = PBIP / "Chapter13_Airline_Operations.Report" / "report.json"
DEP = "# Departures Performed"


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def flights():
    return pd.read_parquet(PARQUET / "QVD/Source/Flight Data.parquet",
                           columns=["Period", DEP, "Carrier Name", "From - To State Code"])


@pytest.fixture(scope="module")
def employment():
    return pd.read_parquet(PARQUET / "QVD/Transformed/Employment Statistics.parquet")


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
    rows = {m["table"]: m["model_rows"] for m in expected["model_tables"]}
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])
    assert len(rows) == 13 and "Section Access" not in rows and "INLFED-1" not in rows
    assert (rows["Main Data"], rows["Airlines"], rows["Carrier Operating Region"], rows["INLFED"]) == (1258763, 337, 8, 3)


@pytest.mark.needs_parquet
def test_main_data_keeps_employment_rows(flights, employment):
    q = SourceModel(APP).con.execute
    assert q('SELECT count(*) FROM "Main Data"').fetchone()[0] == len(flights) + len(employment)
    assert q('SELECT count(*) FROM "Main Data" WHERE "# Equivalent FTEs" IS NOT NULL').fetchone()[0] == len(employment)


@pytest.mark.needs_parquet
def test_flight_employment_and_point_in_time_kpis_match_pandas(expected, flights, employment):
    by_period = flights.groupby("Period")[DEP].sum()
    ytd, ly = by_period[by_period.index // 100 == 2011].sum(), by_period[by_period.index // 100 == 2010].sum()
    assert _total(expected, "CH01#1") == flights[DEP].sum()
    assert _total(expected, "CH65#1") == ytd
    assert _total(expected, "CH60#1") == pytest.approx(ytd / ly - 1, rel=1e-12)
    assert _total(expected, "CH62#1") == pytest.approx(by_period[201112] / by_period[201111] - 1, rel=1e-12)
    assert _total(expected, "CH44#1") == employment["# Equivalent FTEs"].sum()
    ftes = employment.groupby("Carrier Name")["# Equivalent FTEs"].sum()
    assert {r[0]: r[1] for r in _results(expected, "CH44#1")["Carrier Name"]} == \
        {k: float(v) for k, v in ftes.items()}
    share = {r[0]: r[1] for r in _results(expected, "CH43#1")["Carrier Name"]}  # $(vTotalFTEs): '=' variable
    assert share == pytest.approx({k: v / ftes.sum() for k, v in ftes.items() if v}, rel=1e-12)
    assert _total(expected, "CH43#1") == pytest.approx(1.0)
    delta = employment.groupby("Carrier Name")["# M-Delta Total Employees"].sum()
    assert {r[0]: r[1] for r in _results(expected, "CH69#3")["Carrier Name"]} == \
        {k: float(v) for k, v in delta.items() if not pd.isna(v)}
    assert _results(expected, "CH46#1") == {"total": [], "Carrier Group": []}  # no Metric Name selected


@pytest.mark.needs_parquet
def test_calculated_dimension_buckets_match_pandas(expected, flights, employment):
    # Unreduced: carriers that only have Employment Statistics rows count 0 states (the '0 - 100' band)
    states = flights.groupby("Carrier Name")["From - To State Code"].nunique()
    states = states.reindex(states.index.union(employment["Carrier Name"].dropna().unique()), fill_value=0)
    lo = states // 100 * 100
    bands = (lo.astype(str) + "  -  " + (lo + 100).astype(str)).value_counts()
    res = _results(expected, "CH52#1")
    assert {r[0]: r[1] for r in next(v for k, v in res.items() if k != "total")} == bands.to_dict()


def test_pbip_covers_every_kpi_without_section_access(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m.get("keys", [])}
    assert {k["parity_key"] for k in expected["kpis"]} <= keys
    calc = {k for c in model["columns"] for k in c.get("keys", [])}
    assert {harness.parity_key(d) for k in expected["kpis"] for d in k["dims"] if d.startswith("=")} <= calc
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert queries["unmapped"] == [] and "role" not in queries
    assert len(queries["queries"]) == sum(len(k["results"]) for k in expected["kpis"])
    assert not (SM / "roles").exists() and "ref role" not in (SM / "model.tmdl").read_text()
    tables = {f.stem for f in (SM / "tables").glob("*.tmdl")}
    assert "INLFED" in tables and "INLFED-1" not in tables
    assert "SELECTEDVALUE(INLFED[eMetric])" in (SM / "tables" / "Main Data.tmdl").read_text()
    assert "INLFED" not in (SM / "relationships.tmdl").read_text()
    assert json.loads((PBIP / "model.json").read_text())["roles"] == {}


def test_no_reserved_looking_dax_variables():
    text = "".join(f.read_text() for f in SM.rglob("*.tmdl"))
    names = set(re.findall(r"\bVAR\s+(\w+)", text))
    assert names and not names & {"Levels", "Level", "Path", "Value", "Values", "Table", "Date", "Year"}


def test_report_has_one_page_per_sheet_bound_to_model_fields():
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    pages = json.loads(REPORT.read_text())["sections"]
    assert [p["displayName"] for p in pages] == [s["name"] for s in manifest["sheets"]]
    model = read_tmdl(PBIP)
    measures = {m["name"] for m in model["measures"]}
    columns = {(c["table"], c["name"]) for c in model["columns"]}
    titles = []
    for page in pages:
        assert page["visualContainers"], page["displayName"]
        for container in page["visualContainers"]:
            visual = json.loads(container["config"])["singleVisual"]
            entities = {f["Name"]: f["Entity"] for f in visual["prototypeQuery"]["From"]}
            for sel in visual["prototypeQuery"]["Select"]:
                kind, ref = next(iter((k, v) for k, v in sel.items() if k in ("Column", "Measure")))
                table = entities[ref["Expression"]["SourceRef"]["Source"]]
                assert (ref["Property"] in measures) if kind == "Measure" else ((table, ref["Property"]) in columns), sel
            names = {s["Name"] for s in visual["prototypeQuery"]["Select"]}
            assert all(p["queryRef"] in names for refs in visual["projections"].values() for p in refs)
            titles.append(visual["vcObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"])
    assert "'Enplaned passengers (millions)'" in titles  # Chapter 13's caption (Chapter 15 renamed it)
    assert sum(len(p["visualContainers"]) for p in pages) >= 50


def test_list_boxes_become_slicers_and_every_chart_has_a_visual():
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    pages = {p["displayName"]: [json.loads(c["config"]) for c in p["visualContainers"]]
             for p in json.loads(REPORT.read_text())["sections"]}

    def slicers(page):
        return {v["singleVisual"]["projections"]["Values"][0]["queryRef"] for v in pages[page]
                if v["singleVisual"]["visualType"] == "slicer"}
    assert {"Main Data.Carrier Name", "Main Data.Origin Country", "Distance Groups.Distance Interval",
            "Flight Types.Flight Type"} <= slicers("Associations")
    assert slicers("Data Consistency") == {"Aircraft Types.Aircraft Name", "Master Calendar.Year"}
    assert "INLFED.Metric Name" in slicers("Variables")  # drives 'Selected Metric'
    assert {"Group A.Group A Year - Month", "Group B.Group B Year - Month"} <= slicers("Comparative Analysis")
    model = json.loads((PBIP / "model.json").read_text())
    assert model["unmapped_list_boxes"] == {"MB01": "Flight Information", "MB02": "Aircraft",
                                            "LB10": "Aircraft Type", "LB11": "Aircraft Group"}
    assert any("unmapped_list_boxes" in g for g in model["semantic_gaps"])
    charts = {c["id"].split(" ")[0] for c in manifest["charts"]}
    names = {v["name"] for vs in pages.values() for v in vs}
    placed = {cid for page in manifest["sheets"] for cid in charts
              if tag(PBIP.name, "visual", page["id"], cid) in names}
    assert placed == charts


def test_text_measures_are_not_plotted_and_slicers_sync_across_pages():
    for page in json.loads(REPORT.read_text())["sections"]:
        for container in page["visualContainers"]:
            visual = json.loads(container["config"])["singleVisual"]
            for role in ("Y", "X", "Size", "Values"):
                if visual["visualType"] not in ("tableEx", "pivotTable", "card"):
                    assert {"queryRef": "Main Data.Carrier"} not in visual["projections"].get(role, [])
            if visual["visualType"] == "slicer":
                assert visual["syncGroup"]["groupName"] == visual["projections"]["Values"][0]["queryRef"]
