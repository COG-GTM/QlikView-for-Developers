"""Chapter 15 (Airline Operations base model): source-side parity, Section Access and the PBIP's coverage.

The harness's KPI results (DuckDB over models/<app>.sql) are re-derived here with pandas straight from the
Parquet of the original QVDs, as the ADMIN user's Section Access reduction leaves them.
"""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

import harness
from dax import read_tmdl
from engine import SourceModel

APP = "Chapter15__Solution_Chapter 15_Airline Operations"
POWERBI = Path(__file__).resolve().parents[1]
PARQUET = POWERBI / "data" / "parquet"
PBIP = POWERBI / "apps" / "Chapter15_Airline_Operations"
SM = PBIP / "Chapter15_Airline_Operations.SemanticModel" / "definition"
DEP = "# Departures Performed"
USERS = {"DF": "DOMESTIC_FOREIGN", "DU": "DOMESTIC_US", "IF": "INTERNATIONAL_FOREIGN"}
FLIGHT_TYPES = {"DOMESTIC_FOREIGN": "Domestic, Foreign Carriers", "DOMESTIC_US": "Domestic, US Carriers Only",
                "INTERNATIONAL_FOREIGN": "International, Foreign Carriers",
                "INTERNATIONAL_US": "International, US Carriers Only"}


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def flights():
    return pd.read_parquet(PARQUET / "QVD/Source/Flight Data.parquet",
                           columns=["%Datasource ID", "Period", DEP, "Carrier Name", "From - To State Code"])


@pytest.fixture(scope="module")
def flight_types():
    return pd.read_parquet(PARQUET / "QVD/Source/Flight Types.parquet")


def _results(expected, kpi):
    k = next(k for k in expected["kpis"] if k["kpi"] == kpi)
    assert k["status"] == "ok", k.get("reason")
    return {r["id"].split("@")[1]: r["rows"] for r in k["results"]}


def _total(expected, kpi):
    rows = _results(expected, kpi)["total"]
    return rows[0][0] if rows else None


def test_every_kpi_evaluated_and_model_matches_inventory(expected):
    assert expected["status"] == "ok"
    assert len(expected["kpis"]) == 92 and all(k["status"] == "ok" for k in expected["kpis"])
    assert len(expected["model_tables"]) == 14
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])


@pytest.mark.needs_parquet
def test_section_access_reduction_per_user(flights, flight_types):
    model = SourceModel(APP)
    q = model.con.execute
    # ADMIN ('*' = every listed flight type): all flight rows, none of the Employment Statistics rows
    assert q('SELECT count(*) FROM "Main Data"').fetchone()[0] == len(flights)
    assert q('SELECT count(*) FROM src."Main Data"').fetchone()[0] == len(flights) + 2688
    assert q('SELECT count(*) FROM "Main Data" WHERE "# Equivalent FTEs" IS NOT NULL').fetchone()[0] == 0
    for user, ft in {**USERS, "NOCARRIER": None}.items():
        q(f"UPDATE src.current_user SET USERID = '{user}'")
        ids = set(flight_types["%Datasource ID"]) if ft is None else \
            set(flight_types.loc[flight_types["Flight Type"] == FLIGHT_TYPES[ft], "%Datasource ID"])
        mine = flights[flights["%Datasource ID"].isin(ids)]
        rows, dep = q(f'SELECT count(*), sum("{DEP}") FROM "Main Data"').fetchone()
        assert (rows, dep) == (len(mine), mine[DEP].sum()), user
        assert sorted(q('SELECT list("%FLIGHTTYPE") FROM "INLFED"').fetchone()[0]) == ([ft] if ft else sorted(FLIGHT_TYPES))


@pytest.mark.needs_parquet
def test_flight_and_point_in_time_kpis_match_pandas(expected, flights):
    by_period = flights.groupby("Period")[DEP].sum()
    ytd, ly = by_period[by_period.index // 100 == 2011].sum(), by_period[by_period.index // 100 == 2010].sum()
    assert _total(expected, "CH01#1") == flights[DEP].sum()
    assert _total(expected, "CH65#1") == ytd
    assert _total(expected, "CH60#1") == pytest.approx(ytd / ly - 1, rel=1e-12)
    assert _total(expected, "CH61#1") == pytest.approx(by_period[201112] / by_period[201012] - 1, rel=1e-12)
    assert _total(expected, "CH62#1") == pytest.approx(by_period[201112] / by_period[201111] - 1, rel=1e-12)
    assert [_total(expected, f"CH65#{i}") for i in (2, 3, 4)] == [by_period[201112], by_period[201111], by_period[201110]]
    assert {r[0]: r[1] for r in _results(expected, "CH66#1")["Period"]} == {int(p): float(v) for p, v in by_period.items()}
    assert _results(expected, "CH59#1")["Year"] == []  # e(Year) with no selections: no excluded years
    assert _results(expected, "CH69#1")["Carrier Name"] == []  # Employment rows are reduced away for ADMIN
    assert _results(expected, "CH46#1") == {"total": [], "Carrier Group": []}  # no Metric Name selected


@pytest.mark.needs_parquet
def test_calculated_dimension_buckets_match_pandas(expected, flights):
    states = flights.groupby("Carrier Name")["From - To State Code"].nunique()
    lo = states // 100 * 100
    bands = (lo.astype(str) + "  -  " + (lo + 100).astype(str)).value_counts()
    res = _results(expected, "CH52#1")
    assert {r[0]: r[1] for r in next(v for k, v in res.items() if k != "total")} == bands.to_dict()


def test_pbip_covers_every_kpi_and_calculated_dimension(expected):
    model = read_tmdl(PBIP)
    keys = {k for m in model["measures"] for k in m.get("keys", [])}
    assert {k["parity_key"] for k in expected["kpis"]} <= keys
    calc = {k for c in model["columns"] for k in c.get("keys", [])}
    assert {harness.parity_key(d) for k in expected["kpis"] for d in k["dims"] if d.startswith("=")} <= calc
    queries = json.loads((POWERBI / "parity" / "dax" / f"{APP}.queries.json").read_text())
    assert queries["unmapped"] == [] and queries["role"] == "ADMIN"
    assert len(queries["queries"]) == sum(len(k["results"]) for k in expected["kpis"])


def test_roles_reproduce_section_access():
    roles = {f.stem: f.read_text() for f in (SM / "roles").glob("*.tmdl")}
    assert set(roles) == {"ADMIN", "DF", "DU", "IF", "NOCARRIER"}

    def allowed(text):
        return sorted(re.findall(r'"([A-Z_]+)"', re.search(r"tablePermission INLFED = (.+)", text).group(1)))
    assert allowed(roles["ADMIN"]) == allowed(roles["NOCARRIER"]) == sorted(FLIGHT_TYPES)
    assert all(allowed(roles[u]) == [ft] for u, ft in USERS.items())
    assert "columnPermission 'Carrier Name' = none" in roles["NOCARRIER"]
    assert all("columnPermission" not in roles[u] for u in roles if u != "NOCARRIER")
    for text in roles.values():  # reduction also restricts dimension rows, as in QlikView
        assert {"'Aircraft Types'", "'Origin Markets'", "'Master Calendar'", "'Group A'"} <= \
            set(re.findall(r"^\ttablePermission ('[^']+'|\w+) = ", text, re.M))
    assert "'Flight Types'[Flight Type] IN {\"Domestic, US Carriers Only\"}" in roles["DU"]
    assert "PASSWORD" not in "".join(roles.values()) and "123" not in "".join(roles.values())


@pytest.mark.needs_parquet
def test_element_functions_honour_their_set(flights):
    from engine import Evaluator
    ev = Evaluator(SourceModel(APP))
    by_year = flights.groupby(flights["Period"] // 100)[DEP].sum()

    def total(expr):
        return ev.evaluate(ev.compile(expr), [])["value"].iloc[0]
    assert total(f"Sum({{1<Year = p({{1<Year={{2010}}>}} Year)>}} [{DEP}])") == by_year[2010]
    assert total(f"Sum({{1<Year = e({{1<Year={{2010}}>}} Year)>}} [{DEP}])") == by_year[2009] + by_year[2011]
    assert pd.isna(total(f"Sum({{1<Year = e(Year)>}} [{DEP}])"))
