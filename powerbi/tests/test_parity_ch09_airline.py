"""Chapter 09 Airline Operations (derived from the Chapter 15 base model): source model, KPIs and PBIP coverage.

The harness's results (DuckDB over models/<app>.sql) are re-derived with pandas from the Parquet of the original
QVDs and CSVs; the Aircraft Types table the script builds is compared with the QVD the same script STOREs.
"""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_relationships, read_tmdl
from engine import SourceModel

APP = "Chapter09__Solution_Chapter 9_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter09_Airline_Operations"
SM = PBIP / "Chapter09_Airline_Operations.SemanticModel" / "definition"
DEP = "# Departures Performed"


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def flights():
    return pd.read_parquet(PARQUET / "Data Files/QVDs/Flight Data.parquet")


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def test_every_kpi_evaluated_and_model_matches_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 42 and all(k["status"] == "ok" for k in expected["kpis"])
    assert len(expected["model_tables"]) == 12
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])


@pytest.mark.needs_parquet
def test_kpis_match_pandas(expected, flights):
    emp = pd.read_parquet(PARQUET / "Data Files/QVDs/T_F41SCHEDULE_P1A_EMP.parquet")
    assert len(flights) + len(emp) == 1258763
    by_year = flights.groupby(flights["Period"] // 100)[DEP].sum()
    assert _results(expected, "CH01#1")["total"] == [[flights[DEP].sum()]]
    assert {r[0]: r[1] for r in _results(expected, "CH01#1")["Year"]} == by_year.to_dict()
    assert len(_results(expected, "CH01#1")["Year+Month"]) == 36
    lf = flights["# Transported Passengers"].sum() / flights["# Available Seats"].sum()
    assert _results(expected, "CH05#1")["total"][0][0] == pytest.approx(lf, rel=1e-12)
    types = pd.read_parquet(PARQUET / "Data Files/QVDs/Flight Types.parquet")
    merged = flights.merge(types, on="%Datasource ID")
    status = merged["Flight Type"].map({"Domestic, US Carriers Only": "Open",
                                        "International, Foreign Carriers": "Negotiating"}).fillna("Closed")
    funnel = (merged.groupby(status)["# Transported Passengers"].sum() / 1e6).to_dict()
    got = {r[0]: r[1] for k, rows in _results(expected, "CH27#1").items() if k != "total" for r in rows}
    assert got == pytest.approx(funnel, rel=1e-12)


@pytest.mark.needs_parquet
def test_aircraft_types_match_the_stored_qvd():
    """The script STOREs [Aircraft Types] into Aircraft Types Transformed.qvd; rebuilding it must give the same rows."""
    con = SourceModel(APP).con
    qvd = (PARQUET / "Data Files/QVDs/Aircraft Types Transformed.parquet").as_posix()
    diff = con.execute(f"""SELECT "%Aircraft Type ID" FROM (SELECT * FROM "Aircraft Types"
                           EXCEPT SELECT * FROM read_parquet('{qvd}'))""").fetchall()
    assert diff == [(91,)]  # only the empty manufacturer: '' in the QVD, null in the CSV's Parquet
    row = con.execute('SELECT "Aircraft Manufacturer", "Aircraft Manufacturer Country" FROM "Aircraft Types" '
                      'WHERE "%Aircraft Type ID" = 91').fetchone()
    assert row == (None, "Unknown")


def test_pbip_covers_every_kpi_and_has_no_chapter15_only_parts(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m.get("keys", [])}
    assert {k["parity_key"] for k in expected["kpis"]} == keys  # exactly this chapter's expressions
    calc = {k for c in model["columns"] for k in c.get("keys", [])}
    assert {harness.parity_key(d) for k in expected["kpis"] for d in k["dims"] if d.startswith("=")} == calc
    tables = {c["table"] for c in model["columns"]}
    assert tables == {t["table"] for t in expected["model_tables"]}
    assert not (SM / "roles").exists()  # no Section Access in Chapter 9
    assert not {"PeriodID", "QuarterID"} & {c["name"] for c in model["columns"] if c["table"] == "Master Calendar"}
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert queries["unmapped"] == [] and "role" not in queries
    assert len(queries["queries"]) == sum(len(k["results"]) for k in expected["kpis"]) + len(expected["objects"])
    assert len(queries["relationships"]) == 11


def test_relationships_follow_the_key_fields():
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    want = {(k["tables"][0], k["key"], k["tables"][1]) for k in manifest["pbip_plan"]["relationships_from_keys"]}
    got = {(r["fromColumn"][0], r["fromColumn"][1], r["toColumn"][0]) for r in read_relationships(PBIP)}
    assert got == want


def test_comments_become_descriptions():
    text = (SM / "tables" / "Aircraft Types.tmdl").read_text()
    assert text.startswith("/// Dimension containing information on aircrafts")
    assert "\t/// The engine type of the aircraft" in text
    assert "\t/// Primary key of the Aircraft Type dimension\n\tcolumn '%Aircraft Type ID'" in \
        (SM / "tables" / "Main Data.tmdl").read_text()


def test_report_visuals_use_model_fields():
    model = read_tmdl(PBIP)
    fields = {(c["table"], c["name"]) for c in model["columns"]} | {(m["table"], m["name"]) for m in model["measures"]}
    report = json.loads((PBIP / "Chapter09_Airline_Operations.Report" / "report.json").read_text())
    assert [s["displayName"] for s in report["sections"]] == ["Dashboard", "Analysis", "Reports", "Gauge Styles", "Associations",
                                                              "Other Charts", "Other representations", "Data Consistency"]
    for s in report["sections"]:
        for v in s["visualContainers"]:
            q = json.loads(v["config"])["singleVisual"]["prototypeQuery"]
            alias = {f["Name"]: f["Entity"] for f in q["From"]}
            for sel in q["Select"]:
                kind, body = next(iter((k, b) for k, b in sel.items() if k != "Name"))
                assert (alias[body["Expression"]["SourceRef"]["Source"]], body["Property"]) in fields, sel["Name"]


NATIVE_VISUALS = {"slicer", "gauge", "lineChart", "lineClusteredColumnComboChart", "tableEx", "pieChart", "scatterChart",
                  "pivotTable", "hundredPercentStackedColumnChart", "funnel", "treemap"}


def test_report_uses_native_visuals_and_keeps_chart_measures():
    report = json.loads((PBIP / "Chapter09_Airline_Operations.Report" / "report.json").read_text())
    visuals = {json.loads(v["config"])["singleVisual"]["visualType"] for s in report["sections"]
               for v in s["visualContainers"]}
    assert visuals <= NATIVE_VISUALS and not report["resourcePackages"]
    traffic = next(json.loads(v["config"])["singleVisual"] for s in report["sections"] for v in s["visualContainers"]
                   if "'Traffic per Year'" in v["config"])
    assert [r["queryRef"] for r in traffic["projections"]["Y"]] == [
        "Main Data.# of Flights", "Main Data.# of Enplanned Passengers", "Main Data.Transported Freight",
        "Main Data.Transported Mail"]


def test_dax_has_no_reserved_looking_vars():
    text = "".join(f.read_text() for f in (SM / "tables").glob("*.tmdl"))
    names = set(re.findall(r"\bVAR\s+(\w+)", text))
    assert not names & {"Levels", "Level", "Values", "Filter", "Table", "Date", "Time"}


def test_list_boxes_become_slicers_and_parity_objects(expected):
    """Every list box whose caption is a model field is a slicer; the parity objects check their values."""
    import build_airline_ch09 as b
    report = json.loads((PBIP / "Chapter09_Airline_Operations.Report" / "report.json").read_text())
    slicers = {(s["displayName"], json.loads(v["config"])["singleVisual"]["projections"]["Values"][0]["queryRef"])
               for s in report["sections"] for v in s["visualContainers"]
               if json.loads(v["config"])["singleVisual"]["visualType"] == "slicer"}
    by_page = {}
    for page, ref in slicers:
        by_page.setdefault(page, set()).add(ref)
    panel = {".".join(b.LIST_BOXES[lb]) for lb in b.FILTER_PANEL}
    assert all(by_page[p] == panel for p in ("Dashboard", "Analysis", "Reports", "Gauge Styles", "Other Charts",
                                              "Other representations"))
    assert by_page["Associations"] == {".".join(b.LIST_BOXES[lb]) for lb in
                                       ("LB01", "LB02", "LB03", "LB04", "LB05", "LB06", "LB07", "LB09", "LB12", "LB13",
                                        "LB15")}
    assert by_page["Data Consistency"] == {"Master Calendar.Year", "Aircraft Types.Aircraft Name"}
    flights = next(json.loads(v["config"])["singleVisual"] for s in report["sections"] if s["displayName"] == "Data Consistency"
                   for v in s["visualContainers"] if "'Flights'" in v["config"])
    assert [r["queryRef"] for r in flights["projections"]["Values"]] == [
        "Master Calendar.Year", "Aircraft Types.Aircraft Name", "Main Data.# of Flights"]
    objs = {o["object"]: o for o in expected["objects"]}
    assert set(objs) == set(b.LIST_BOXES) - {"LB15", "LB29"}
    assert all(objs[lb]["fields"] == [b.LIST_BOXES[lb][1]] and objs[lb]["status"] == "ok" for lb in objs)
    assert not set(b.UNMAPPED_LIST_BOXES) & set(b.LIST_BOXES)
    months = [r[0] for r in objs["LB30"]["results"][0]["rows"]]
    assert sorted(months) == sorted(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    lb = next(q for q in queries["queries"] if q["id"] == "LB06@Origin City")
    assert lb["query"] == "EVALUATE FILTER(SUMMARIZECOLUMNS('Main Data'[Origin City]), NOT ISBLANK('Main Data'[Origin City]))"


def test_every_sheet_chart_is_a_visual_on_its_page():
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    report = json.loads((PBIP / "Chapter09_Airline_Operations.Report" / "report.json").read_text())
    titles = {json.loads(v["config"])["singleVisual"]["vcObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]
              ["Value"].strip("'").replace("''", "'") for s in report["sections"] for v in s["visualContainers"]}
    for ch in manifest["charts"]:
        assert ch["caption"] in titles or f"{ch['caption']} ({ch['id']})" in titles, ch["id"]
