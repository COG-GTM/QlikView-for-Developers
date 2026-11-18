"""Chapter 07 (Airline Operations, plain loads): source-side parity and the PBIP built from the Chapter 15 base."""
import json
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_tmdl

APP = "Chapter07__Solution_Chapter 7_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter07_Airline_Operations"
EXCEPTIONS = {"Origin Airports": (2104, 6209), "Destination Airports": (2169, 6209)}


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def test_every_kpi_evaluated_and_rows_match_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 41 and all(k["status"] == "ok" for k in expected["kpis"])
    assert len(expected["model_tables"]) == 12
    for m in expected["model_tables"]:
        assert (m["inventory_rows"], m["model_rows"]) == EXCEPTIONS.get(m["table"], (m["model_rows"],) * 2)


@pytest.mark.needs_parquet
def test_flight_kpis_match_pandas(expected):
    df = pd.read_parquet(PARQUET / "Data Files/QVDs/Flight Data.parquet",
                         columns=["# Departures Performed", "# Transported Passengers", "# Available Seats",
                                  "Carrier Name"])
    assert _results(expected, "CH01#1")["total"][0][0] == df["# Departures Performed"].sum()
    lf = df["# Transported Passengers"].sum() / df["# Available Seats"].sum()
    assert _results(expected, "CH05#1")["total"][0][0] == pytest.approx(lf)
    pie = dict(map(tuple, _results(expected, "CH15#1")["Carrier Name"]))
    want = df.groupby("Carrier Name")["# Transported Passengers"].sum()
    assert {k: pie[k] for k in want.index} == want.to_dict()
    carrier = dict(map(tuple, _results(expected, "CH15#2")["Carrier Name"]))
    assert all(carrier[c] == c for c in want.index)
    assert _results(expected, "CH15#2")["total"][0][0] == "Others"


def test_pbip_covers_every_kpi_and_calculated_dimension(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m["keys"]} | {k for c in model["columns"] for k in c.get("keys", [])}
    assert {k["parity_key"] for k in harness.kpi_list(json.loads((harness.INVENTORY / "manifests" / f"{APP}.json").read_text()), APP)} <= keys
    assert any(c["name"] == "Deal Status" and c["table"] == "Flight Types" for c in model["columns"])
    names = [m["name"].lower() for m in model["measures"]]
    assert len(names) == len(set(names))
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert not queries["unmapped"] and len(queries["relationships"]) == 11


def test_report_has_one_page_per_sheet():
    report = json.loads((PBIP / "Chapter07_Airline_Operations.Report" / "report.json").read_text())
    pages = [s["displayName"] for s in report["sections"]]
    assert pages == ["Main", "Dashboard", "Analysis", "Reports", "Gauge Styles", "Other Charts",
                     "Other representations"]
    charts = {c for p in json.loads((PBIP / "model.json").read_text())["pages"] for c in p["charts"]}
    assert len(charts) == 22
