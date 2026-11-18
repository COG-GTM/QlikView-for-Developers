"""Chapter 09 "Concatenated tables": source-side parity and the PBIP's coverage.

The harness's results (DuckDB over models/<app>.sql) are re-derived here with pandas straight from the Parquet of
the original QVDs / CSVs: the concatenated [Main Data], the Aircraft Types mapping + join + 2010 update, and the
'Unknown' members.
"""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_tmdl
from scaffold_pbip import tag

APP = "Chapter09__Solution_Chapter 9_Concatenated tables"
POWERBI = Path(__file__).resolve().parents[1]
DATA = POWERBI / "data" / "parquet" / "Data Files"
PBIP = POWERBI / "apps" / "Chapter09_Concatenated_tables"
SM = PBIP / "Chapter09_Concatenated_tables.SemanticModel" / "definition"
PAX, SEATS = "# Transported Passengers", "# Available Seats"


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def main_data():
    flights = pd.read_parquet(DATA / "QVDs/Flight Data.parquet")
    emp = pd.read_parquet(DATA / "QVDs/T_F41SCHEDULE_P1A_EMP.parquet")
    emp["Quarter"] = "Q" + (emp["Month (#)"] / 3).apply(lambda x: -(-x // 1)).astype(int).astype(str)
    return pd.concat([flights, emp], ignore_index=True)


@pytest.fixture(scope="module")
def aircraft(main_data):
    keys = set(main_data["%Aircraft Type ID"].dropna())
    country = dict(pd.read_parquet(DATA / "CSVs/Aircraft_Manufacturers.parquet").values)
    base = pd.read_parquet(DATA / "CSVs/Aircraft_Base_File.parquet")
    base = base[base["AC_TYPEID"].isin(keys)]
    groups = pd.read_parquet(DATA / "CSVs/Aircraft_Group.parquet")
    base = base.merge(groups, how="left", left_on="AC_GROUP", right_on="Aircraft Group ID")
    base["Age"] = ["Classic" if pd.notna(d) and d.year < 1990 else "Current" for d in base["BEGIN_DATE"]]
    upd = pd.read_parquet(DATA / "CSVs/Aircraft_2010_Update.parquet")
    upd = upd[upd["AC_TYPEID"].isin(keys)].copy()
    parts = upd["AC_GROUPNAME"].str.split(", ")
    upd["Aircraft Engine Type"] = parts.str[0]
    upd["Aircraft Number Of Engines"] = parts.str[1]
    upd["Age"] = "Current"
    out = pd.concat([base, upd], ignore_index=True)
    out["Country"] = out["MANUFACTURER"].map(country).fillna("Unknown")
    return out


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@", 1)[1]: r["rows"] for r in k["results"]}


def test_every_kpi_evaluated_and_model_matches_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 42 and all(k["status"] == "ok" for k in expected["kpis"])
    assert len(expected["model_tables"]) == 11
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])


@pytest.mark.needs_parquet
def test_concatenated_main_data_kpis_match_pandas(expected, main_data):
    assert len(main_data) == 1258763
    assert _results(expected, "CH01#1")["total"][0][0] == main_data["# Departures Performed"].sum()
    by_year = main_data.groupby("Year")["# Departures Performed"].sum()
    assert {y: v for y, v in _results(expected, "CH01#1")["Year"]} == by_year.to_dict()
    lf = main_data[PAX].sum() / main_data[SEATS].sum()
    assert _results(expected, "CH05#1")["total"][0][0] == pytest.approx(lf, rel=1e-12)
    # the Employment rows carry the computed Quarter of their month
    quarters = main_data.loc[main_data["# Equivalent FTEs"].notna(), ["Month (#)", "Quarter"]].drop_duplicates()
    assert all(q == f"Q{(mo + 2) // 3}" for mo, q in quarters.values)


@pytest.mark.needs_parquet
def test_aircraft_types_mapping_join_and_update(expected, main_data, aircraft):
    assert len(aircraft) == 180
    assert set(aircraft.loc[aircraft["AC_GROUPNAME"].notna(), "Age"]) == {"Current"}
    assert (aircraft["Country"] == "Unknown").sum() == 1
    rows = _results(expected, "CH38#2")["Aircraft Engine Type+Aircraft Number Of Engines"]
    md = main_data.merge(aircraft, how="left", left_on="%Aircraft Type ID", right_on="AC_TYPEID")
    md = md[md["%Aircraft Type ID"].notna()]
    g = md.groupby(["Aircraft Engine Type", "Aircraft Number Of Engines"], dropna=False)[[PAX, SEATS]].sum()
    want = {(None if pd.isna(e) else e, None if pd.isna(n) else n): p / s for (e, n), (p, s) in g.iterrows() if s}
    got = {(e, n): v for e, n, v in rows if v is not None}
    assert got.keys() == want.keys()
    assert all(got[k] == pytest.approx(want[k], rel=1e-12) for k in want)
    assert ("Helicopter/Stol", None) in got  # SubField(AC_GROUPNAME, ', ', 2) of 'Helicopter/Stol' is null


@pytest.mark.needs_parquet
def test_deal_status_calculated_dimension(expected, main_data):
    ft = pd.read_parquet(DATA / "QVDs/Flight Types.parquet")
    status = {"Domestic, US Carriers Only": "Open", "International, Foreign Carriers": "Negotiating"}
    ft["Deal"] = ft["Flight Type"].map(status).fillna("Closed")
    md = main_data.merge(ft, on="%Datasource ID")
    want = (md.groupby("Deal")[PAX].sum() / 1e6).to_dict()
    rows = next(v for k, v in _results(expected, "CH27#1").items() if k != "total")
    assert {d: pytest.approx(want[d], rel=1e-12) for d in want} == {d: v for d, v in rows}


def test_pbip_covers_every_kpi_and_relationship(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m.get("keys", [])}
    assert {k["parity_key"] for k in expected["kpis"]} <= keys
    calc = {k for c in model["columns"] for k in c.get("keys", [])}
    assert {harness.parity_key(d) for k in expected["kpis"] for d in k["dims"] if d.startswith("=")} <= calc
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert queries["unmapped"] == [] and "role" not in queries
    assert len(queries["queries"]) == sum(len(k["results"]) for k in expected["kpis"])
    assert not re.search(r"\bVAR\s+Levels\b", json.dumps(queries), re.I)
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    rel_text = (SM / "relationships.tmdl").read_text()
    for r in manifest["pbip_plan"]["relationships_from_keys"]:
        dim = next(t for t in r["tables"] if t != "Main Data")
        pattern = rf"fromColumn: 'Main Data'\.'{re.escape(r['key'])}'\n\ttoColumn: '?{re.escape(dim)}'?\."
        assert re.search(pattern, rel_text)
    assert len(queries["relationships"]) == len(manifest["pbip_plan"]["relationships_from_keys"]) == 10


def test_power_query_reproduces_the_script_transformations():
    aircraft = (SM / "tables" / "Aircraft Types.tmdl").read_text()
    for step in ("Record.FieldOrDefault(CountryMap", "JoinKind.LeftOuter", "Table.Combine({Dropped, UpdateRows})",
                 'Table.RemoveColumns(Expanded, {"%Aircraft Group Type"})', 'Text.Split(s, ", ")'):
        assert step in aircraft
    assert aircraft.startswith("/// Dimension containing information on aircrafts")  # COMMENT TABLES
    for t in ("Carrier Groups", "Carrier Operating Region", "Origin Markets", "Destination Markets"):
        assert '"Unknown"' in (SM / "tables" / f"{t}.tmdl").read_text()
    main = (SM / "tables" / "Main Data.tmdl").read_text()
    assert "Table.Combine({Flight, EmploymentQ})" in main and "sortByColumn: Month__num" in main


def test_report_pages_have_the_sheets_charts_and_slicers():
    report = json.loads((PBIP / "Chapter09_Concatenated_tables.Report" / "report.json").read_text())
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    assert [p["displayName"] for p in report["sections"]] == [s["name"] for s in manifest["sheets"]]
    model = read_tmdl(PBIP)
    fields = {f"{c['table']}.{c['name']}" for c in model["columns"]} | \
        {f"Main Data.{m['name']}" for m in model["measures"]}
    kinds = {}
    for page in report["sections"]:
        visuals = [json.loads(v["config"])["singleVisual"] for v in page["visualContainers"]]
        assert any(v["visualType"] != "slicer" for v in visuals), page["displayName"]
        for v in visuals:
            kinds.setdefault(page["displayName"], []).append(v["visualType"])
            assert {s["Name"] for s in v["prototypeQuery"]["Select"]} <= fields
    charts = {c["id"].split(" ")[0] for c in manifest["charts"]}
    names = {json.loads(v["config"])["name"] for p in report["sections"] for v in p["visualContainers"]}
    placed = {cid for page in manifest["sheets"] for cid in charts
              if tag(PBIP.name, "visual", page["id"], cid) in names}
    assert placed == charts
    assert kinds["Dashboard"].count("slicer") == 7 and "gauge" in kinds["Dashboard"]
    assert kinds["Associations"].count("slicer") == 11
    unmapped = json.loads((PBIP / "model.json").read_text())["unmapped_list_boxes"]
    assert unmapped == {"LB10": "Aircraft Type", "LB11": "Aircraft Group", "MB01": "Flight Information",
                        "MB02": "Aircraft"}


def test_case_variant_carrier_is_a_listed_known_difference(expected):
    import compare
    results = [{"id": r["id"], "rows": [row for row in r["rows"]
                                        if r["id"] != "CH15#2@Carrier Name" or "d/b/a Mn" not in row[0]]}
               for k in expected["kpis"] for r in k["results"]]
    doc = {"app": APP, "results": results}
    assert compare.compare(expected, doc)["summary"] == {"pass": 84, "fail": 1}
    exceptions = json.loads((compare.EXCEPTIONS / f"{APP}.json").read_text())
    report = compare.compare(expected, doc, exceptions=exceptions)
    assert report["summary"] == {"pass": 84, "known_difference": 1}
    names = {row[0] for r in results if r["id"] == "CH15#2@Carrier Name" for row in r["rows"]}
    assert {n.casefold() for n in names} == {n.casefold() for n in names if "d/b/a Mn" not in n}
