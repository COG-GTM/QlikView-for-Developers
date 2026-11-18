"""Chapter 08 (Airline Operations, derived from the Chapter 15 base model): source-side parity and PBIP coverage.

The harness's KPI results (DuckDB over models/<app>.sql) are re-derived here with pandas straight from the Parquet
of the original sources; [Aircraft Types] (ApplyMap, LEFT JOIN, CONCATENATE) is rebuilt independently.
"""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_relationships, read_tmdl

APP = "Chapter08__Solution_Chapter 8_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter08_Airline_Operations"
SM = PBIP / "Chapter08_Airline_Operations.SemanticModel" / "definition"
CSV = PARQUET / "Data Files" / "CSVs"
MDB_EXCEPTIONS = {"Origin Airports", "Destination Airports"}


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def flights():
    return pd.read_parquet(PARQUET / "Data Files/QVDs/Flight Data.parquet")


@pytest.fixture(scope="module")
def aircraft():
    """[Aircraft Types] rebuilt from the CSVs with pandas, following the load script."""
    countries = pd.read_parquet(CSV / "Aircraft_Manufacturers.parquet").drop_duplicates("Company")
    country = dict(zip(countries["Company"], countries["Country"]))
    base = pd.read_parquet(CSV / "Aircraft_Base_File.parquet")
    groups = pd.read_parquet(CSV / "Aircraft_Group.parquet")
    base = base.merge(groups, how="left", left_on="AC_GROUP", right_on="Aircraft Group ID")
    base["Aircraft Age Classification"] = [
        "Classic" if pd.notna(d) and pd.Timestamp(d).year < 1990 else "Current" for d in base["BEGIN_DATE"]]
    upd = pd.read_parquet(CSV / "Aircraft_2010_Update.parquet")
    parts = upd["AC_GROUPNAME"].str.split(", ")
    upd["Aircraft Engine Type"] = parts.str[0]
    upd["Aircraft Number Of Engines"] = parts.str[1]
    upd["Aircraft Age Classification"] = "Current"
    out = pd.concat([base, upd], ignore_index=True)
    out["Aircraft Manufacturer Country"] = out["MANUFACTURER"].map(country).fillna("Unknown")
    return out.rename(columns={"AC_TYPEID": "%Aircraft Type ID"})


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def _total(expected, kpi):
    rows = _results(expected, kpi)["total"]
    return rows[0][0] if rows else None


def test_every_kpi_evaluated_and_model_matches_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 42 and all(k["status"] == "ok" for k in expected["kpis"])
    assert len(expected["model_tables"]) == 11
    for t in expected["model_tables"]:  # airports: documented older-.mdb exception (row_count_exceptions.json)
        assert (t["model_rows"] == 6209) if t["table"] in MDB_EXCEPTIONS else (t["inventory_rows"] == t["model_rows"]), t


@pytest.mark.needs_parquet
def test_committed_expected_results_are_reproducible(tmp_path, monkeypatch):
    committed = (harness.EXPECTED / f"{APP}.json.gz").read_bytes()
    monkeypatch.setattr(harness, "EXPECTED", tmp_path)
    harness.write_expected(APP)
    assert (tmp_path / f"{APP}.json.gz").read_bytes() == committed


@pytest.mark.needs_parquet
def test_flight_kpis_match_pandas(expected, flights):
    dep, pax, seats = "# Departures Performed", "# Transported Passengers", "# Available Seats"
    assert _total(expected, "CH01#1") == flights[dep].sum()
    by_ym = flights.groupby(["Year", "Month"])[pax].sum()
    assert {(r[0], r[1]): r[2] for r in _results(expected, "CH01#2")["Year+Month"]} == \
        {(int(y), m): float(v) for (y, m), v in by_ym.items()}
    lf = flights.groupby("%Datasource ID")[[pax, seats]].sum()
    types = pd.read_parquet(PARQUET / "Data Files/QVDs/Flight Types.parquet").set_index("%Datasource ID")["Flight Type"]
    lf.index = lf.index.map(types)
    got = {r[0]: r[1] for r in _results(expected, "CH03#3")["Flight Type"]}
    assert got == pytest.approx((lf[pax] / lf[seats]).to_dict(), rel=1e-12)
    pvs = _results(expected, "CH06#1")["total"][0][0]
    assert pvs == pytest.approx(flights[dep].sum() / flights["# Departures Scheduled"].sum(), rel=1e-12)


@pytest.mark.needs_parquet
def test_aircraft_types_transformation_matches_pandas(expected, flights, aircraft):
    from engine import SourceModel
    model = SourceModel(APP).con.execute('SELECT * FROM "Aircraft Types"').df()
    assert len(model) == len(aircraft) == 378
    cols = ["%Aircraft Type ID", "Aircraft Manufacturer Country", "Aircraft Age Classification",
            "Aircraft Engine Type", "Aircraft Number Of Engines"]
    a = model[cols].astype(object).where(model[cols].notna(), None).sort_values(cols[0]).values.tolist()
    b = aircraft[cols].astype(object).where(aircraft[cols].notna(), None).sort_values(cols[0]).values.tolist()
    assert a == b
    # CH38: Load Factor per engine configuration, joined on %Aircraft Type ID
    pax, seats = "# Transported Passengers", "# Available Seats"
    j = flights.merge(aircraft, how="left", on="%Aircraft Type ID")
    keys = ["Aircraft Engine Type", "Aircraft Number Of Engines"]
    g = j.groupby(keys, dropna=False)[[pax, seats]].sum()
    want = {tuple(None if pd.isna(x) else x for x in k): v for k, v in (g[pax] / g[seats]).dropna().items()}
    got = {(r[0], r[1]): r[2] for r in _results(expected, "CH38#1")["+".join(keys)]}
    assert got == pytest.approx(want, rel=1e-12)


def test_pbip_covers_every_kpi_and_has_one_relationship_per_key(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m.get("keys", [])}
    assert {k["parity_key"] for k in expected["kpis"]} == keys  # only what this chapter's sheets use
    calc = {k for c in model["columns"] for k in c.get("keys", [])}
    assert {harness.parity_key(d) for k in expected["kpis"] for d in k["dims"] if d.startswith("=")} == calc
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert queries["unmapped"] == [] and "role" not in queries
    assert len(queries["queries"]) == sum(len(k["results"]) for k in expected["kpis"])
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    rels = {(r["fromColumn"][1], r["toColumn"][0]) for r in read_relationships(PBIP)}
    assert rels == {(r["key"], r["tables"][1]) for r in manifest["pbip_plan"]["relationships_from_keys"]}
    assert not (SM / "roles").exists()
    tables = {t.stem for t in (SM / "tables").glob("*.tmdl")}
    assert tables == {t["name"] for t in manifest["data_model"]["tables"] if not t["name"].startswith("$$")}


def test_comments_become_descriptions():
    text = (SM / "tables" / "Aircraft Types.tmdl").read_text()
    assert text.startswith("/// Dimension containing information on aircrafts")
    assert re.search(r"\t/// The engine type of the aircraft[^\n]*\n\tcolumn 'Aircraft Engine Type'", text)
    assert "\t/// Primary key of the Aircraft Type dimension\n\tcolumn '%Aircraft Type ID'" in \
        (SM / "tables" / "Main Data.tmdl").read_text()


def test_measures_avoid_reserved_var_names():
    text = (SM / "tables" / "Main Data.tmdl").read_text()
    assert not re.search(r"\bVAR\s+(Levels|Level|Value|Values|Table|Date|Year|Month)\b", text, re.I)


def test_list_boxes_become_slicers_on_their_sheet_page():
    model = json.loads((PBIP / "model.json").read_text())
    report = json.loads((PBIP / "Chapter08_Airline_Operations.Report" / "report.json").read_text())
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    assert [s["displayName"] for s in report["sections"]] == [s["name"] for s in manifest["sheets"]]
    boxes = [o for o in manifest["objects"]["ids"] if o.startswith("LB")]
    assert sorted(b["id"] for b in model["slicers"] + model["unmapped_list_boxes"]) == sorted(boxes)
    assert {b["id"]: b["field"] for b in model["unmapped_list_boxes"]} == {"LB10": "Aircraft Type",
                                                                            "LB11": "Aircraft Group"}
    columns = {(c["table"], c["name"]) for c in read_tmdl(PBIP)["columns"] if not c["hidden"]}
    sheet = {s["id"]: s["name"] for s in manifest["sheets"]}
    pages = {s["displayName"]: [json.loads(v["config"]) for v in s["visualContainers"]] for s in report["sections"]}
    for b in model["slicers"]:
        assert (b["table"], b["column"]) in columns and b["caption"] == b["field"]
        v = next(v for v in pages[sheet[b["sheet"]]] if v["name"] == b["id"])
        assert v["singleVisual"]["visualType"] == "slicer"
        assert v["singleVisual"]["projections"]["Values"][0]["queryRef"] == f"{b['table']}.{b['column']}"
    assert {b["id"] for b in model["slicers"] if b["sheet"] == "SH03"} == {
        "LB27", "LB28", "LB29", "LB30", "LB31", "LB32", "LB33"}


def test_slicers_sync_selections_across_every_page():
    model = json.loads((PBIP / "model.json").read_text())
    report = json.loads((PBIP / "Chapter08_Airline_Operations.Report" / "report.json").read_text())
    fields = {f"{b['table']}.{b['column']}" for b in model["slicers"]}
    for page in report["sections"]:
        configs = [json.loads(v["config"])["singleVisual"] for v in page["visualContainers"]]
        assert sorted(c["syncGroup"]["groupName"] for c in configs) == sorted(fields), page["displayName"]
        for c in configs:
            assert c["syncGroup"]["groupName"] == c["projections"]["Values"][0]["queryRef"]
            assert c["syncGroup"]["filterChanges"] and c["syncGroup"]["fieldChanges"]
        shown = sum(c.get("display", {}).get("mode") != "hidden" for c in configs)
        assert shown == {"Dashboard": 7, "Associations": 11}.get(page["displayName"], 0)
