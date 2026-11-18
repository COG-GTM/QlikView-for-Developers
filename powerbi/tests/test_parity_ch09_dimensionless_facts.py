"""Chapter 09 "Dimensionless Facts" parity proof on the source side.

The app adds an 'Unknown' Aircrafts row for every Flights key that has no aircraft
(CONCATENATE ... WHERE NOT Exists). The harness's results must equal an independent pandas
computation on the raw CSVs, the 'Unknown: <key>' labels must equal the ones stored in the
.qvw, and the PBIP must map every result to a DAX query.
"""
import json
import re
import zlib

import pandas as pd
import pytest

import dax
import harness

APP = "Chapter09__Solution_Dimensionless Facts"
CH09 = harness.REPO / "Chapter09"
PBIP = harness.REPO / "powerbi/apps/Chapter09_Dimensionless_Facts"


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def raw():
    flights = pd.read_csv(CH09 / "Flights.csv", encoding="utf-8-sig", dtype={"%Aircraft Type ID": str})
    aircrafts = pd.read_csv(CH09 / "Aircrafts.csv", encoding="cp1252")
    return flights, aircrafts


def qvw_unknown_names() -> set[str]:
    """'Unknown: ...' values in the .qvw's stored data (zlib blocks of the binary)."""
    data, found = (CH09 / "Solution_Dimensionless Facts.qvw").read_bytes(), set()
    for m in re.finditer(rb"\x78[\x01\x5e\x9c\xda]", data):
        try:
            block = zlib.decompressobj().decompress(data[m.start():])
        except zlib.error:
            continue
        found |= {v.decode() for v in re.findall(rb"Unknown: [0-9]+", block)}
    return found


def test_kpi_evaluated_and_model_matches_inventory(expected):
    assert expected["status"] == "ok"
    assert [(k["kpi"], k["status"]) for k in expected["kpis"]] == [("CH01#1", "ok")]
    assert expected["model_tables"] == [{"table": "Aircrafts", "inventory_rows": 229, "model_rows": 229},
                                        {"table": "Flights", "inventory_rows": 542, "model_rows": 542}]


def test_kpi_matches_independent_pandas_on_raw_csv(expected, raw):
    flights, aircrafts = raw
    flights["key"] = flights["%Aircraft Type ID"].astype(int)
    groups = dict(zip(aircrafts["AC_TYPEID"], aircrafts["Aircraft Group"]))
    flights["group"] = flights["key"].map(groups).fillna("Unknown")
    res = {r["id"]: r["rows"] for r in expected["kpis"][0]["results"]}
    assert res["CH01#1@total"] == [[flights["# Departures Performed"].sum() / 1000]]
    by_group = flights.groupby("group")["# Departures Performed"].sum() / 1000
    assert {g: v for g, v in res["CH01#1@Aircraft Group"]} == pytest.approx(by_group.to_dict(), rel=1e-12)
    assert len(res["CH01#1@Aircraft Group"]) == 10


@pytest.mark.needs_parquet
def test_unknown_aircraft_names_match_the_qvw(raw):
    from engine import SourceModel
    model = SourceModel(APP)
    names = {r[0] for r in model.con.execute(
        "SELECT \"Aircraft Name\" FROM \"Aircrafts\" WHERE \"Aircraft Group\" = 'Unknown'").fetchall()}
    stored = qvw_unknown_names()
    assert len(stored) == 82 and names == stored
    flights, aircrafts = raw
    missing = flights.loc[~flights["%Aircraft Type ID"].astype(int).isin(aircrafts["AC_TYPEID"]), "%Aircraft Type ID"]
    assert {f"Unknown: {k}" for k in missing} == stored  # QlikView keeps the key text as read from the CSV
    # The Power Query rebuilds that text with Text.PadStart(Text.From(key), 3, "0"): it must hold for every key.
    assert all(k == k.lstrip("0").rjust(3, "0") for k in flights["%Aircraft Type ID"])
    tmdl = next(PBIP.glob("*.SemanticModel")).joinpath("definition/tables/Aircrafts.tmdl").read_text()
    assert 'Text.PadStart(Text.From([#"%Aircraft Type ID"]), 3, "0")' in tmdl


@pytest.mark.needs_parquet
def test_committed_expected_results_are_reproducible(tmp_path, monkeypatch):
    committed = (harness.EXPECTED / f"{APP}.json.gz").read_bytes()
    monkeypatch.setattr(harness, "EXPECTED", tmp_path)
    harness.write_expected(APP)
    assert (tmp_path / f"{APP}.json.gz").read_bytes() == committed


def test_every_result_gets_a_dax_query(tmp_path, monkeypatch, expected):
    committed = json.loads((dax.DAX / f"{APP}.queries.json").read_text())
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    spec = json.loads((tmp_path / f"{APP}.queries.json").read_text())
    assert spec == committed and spec["unmapped"] == []
    assert {q["id"] for q in spec["queries"]} == {r["id"] for k in expected["kpis"] for r in k["results"]}
    q = next(q for q in spec["queries"] if q["id"] == "CH01#1@Aircraft Group")
    assert q["query"] == "EVALUATE SUMMARIZECOLUMNS('Aircrafts'[Aircraft Group], \"value\", [Flights by Group])"
