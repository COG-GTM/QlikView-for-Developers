"""Chapter 9 Link table: source model, link-table semantics and the PBIP's coverage."""
import json
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_relationships
from engine import SourceModel

APP = "Chapter09__Solution_Chapter 9_Link table"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet" / "Data Files"
PBIP = POWERBI / "apps" / "Chapter09_Link_table"
DEP = "# Departures Performed"


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def test_every_kpi_evaluated_and_model_matches_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 42 and all(k["status"] == "ok" for k in expected["kpis"])
    assert len(expected["model_tables"]) == 13
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])


@pytest.mark.needs_parquet
def test_link_table_counts_each_flight_once(expected):
    flights = pd.read_parquet(PARQUET / "QVDs/Flight Data.parquet", columns=["Year", DEP])
    by_year = flights.groupby("Year")[DEP].sum()
    assert {r[0]: r[1] for r in _results(expected, "CH01#1")["Year"]} == by_year.to_dict()
    assert _results(expected, "CH01#1")["total"][0][0] == flights[DEP].sum()


@pytest.mark.needs_parquet
def test_link_table_and_aircraft_types_match_the_script():
    model = SourceModel(APP)
    q = model.con.execute
    rows, keys = q('SELECT count(*), count(DISTINCT "%Key Field") FROM "Link Table"').fetchone()
    assert (rows, keys) == (10073, 10068)
    assert q('SELECT count(*) FROM "Employment Statistics" WHERE "%Key Field" NOT IN '
             '(SELECT "%Key Field" FROM "Link Table")').fetchone()[0] == 0
    # the script STOREs [Aircraft Types]; the stored QVD is the reference (manufacturer '' converts to null)
    stored = pd.read_parquet(PARQUET / "QVDs/Aircraft Types Transformed.parquet").replace("", None)
    mine = q('SELECT * FROM "Aircraft Types"').df()
    for df in (stored, mine):
        df["Aircraft Begin Date"] = pd.to_datetime(df["Aircraft Begin Date"])
    key = "%Aircraft Type ID"
    pd.testing.assert_frame_equal(mine.sort_values(key).reset_index(drop=True),
                                  stored[mine.columns].sort_values(key).reset_index(drop=True), check_dtype=False)


def test_pbip_covers_every_kpi_with_many_to_many_link():
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    text = "\n".join(p.read_text() for p in (PBIP / "Chapter09_Link_table.SemanticModel").rglob("*.tmdl"))
    for k in harness.kpi_list(manifest):
        assert f"annotation ParityKey = {k['parity_key']}" in text, k["kpi"]
    assert "VAR Levels" not in text
    rels = {(r["fromColumn"], r["toColumn"]): r["to_many"] for r in read_relationships(PBIP)}
    assert rels[(("Main Data", "%Key Field"), ("Link Table", "%Key Field"))]
    assert rels[(("Employment Statistics", "%Key Field"), ("Link Table", "%Key Field"))]
    assert not rels[(("Link Table", "%Airline ID"), ("Airlines", "%Airline ID"))]


@pytest.mark.needs_parquet
def test_link_table_dual_fields_keep_their_numbers():
    """A field joined from the non-unique link table keeps its __num companion (numeric selections, Min/Max)."""
    model = SourceModel(APP)
    frm, cols = model.from_clause({"Month", DEP})
    assert "Month__num" in cols and cols["Month"].split(".")[0] == cols["Month__num"].split(".")[0]
    jan = model.con.execute(f'SELECT sum({cols[DEP]}) FROM {frm} WHERE {cols["Month__num"]} = 1').fetchone()[0]
    flights = pd.read_parquet(PARQUET / "QVDs/Flight Data.parquet", columns=["Month (#)", DEP])
    assert jan == flights.loc[flights["Month (#)"] == 1, DEP].sum()
