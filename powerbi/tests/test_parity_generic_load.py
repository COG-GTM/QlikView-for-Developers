"""Chapter 10 Generic Load: source-side parity and the DAX checks for the pivoted Power BI table.

QlikView's GENERIC LOAD builds one table per attribute (GenericDB.Color, ...); the PBIP pivots
the same rows into one GenericDB table. The harness records every Qlik table's content and maps
it to a GROUPBY over GenericDB. The tests cross-check the harness against the Excel workbook read
independently with openpyxl, and simulate the Power Query pivot + DAX queries with pandas.
"""
import re
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

import compare
import dax
import harness

REPO = Path(__file__).resolve().parents[2]
APP = "Chapter10__Generic Load"
PBIP = REPO / "powerbi/apps/Chapter10_Generic_Load"
TMDL = PBIP / "Chapter10_Generic_Load.SemanticModel/definition/tables/GenericDB.tmdl"


@pytest.fixture(scope="module")
def workbook_rows():
    ws = openpyxl.load_workbook(REPO / "Chapter10/Generic DB.xlsx", read_only=True)["GenericDB"]
    header, *rows = list(ws.values)
    assert header == ("Object", "Attribute", "Value")
    return rows


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


def _pbi_table(workbook_rows) -> pd.DataFrame:
    """What the GenericDB partition produces: Table.Pivot(Object, Attribute -> Value) with the TMDL's types."""
    df = pd.DataFrame(workbook_rows, columns=["Object", "Attribute", "Value"])
    assert not df.duplicated(["Object", "Attribute"]).any()  # Table.Pivot without aggregation needs this
    pivot_list = re.search(r'Table\.Pivot\(Selected, \{([^}]*)\}', TMDL.read_text()).group(1)
    attrs = re.findall(r'"([^"]+)"', pivot_list)
    wide = df.pivot(index="Object", columns="Attribute", values="Value").reindex(columns=attrs).reset_index()
    wide["Value"] = wide["Value"].astype("Int64")
    return wide


def _simulate_dax(spec: dict, table: pd.DataFrame) -> dict:
    results = []
    for q in spec["queries"]:
        q_text = q["query"]
        assert q_text.startswith("EVALUATE GROUPBY(") and q_text.endswith(', "__rows", SUMX(CURRENTGROUP(), 1))'), q_text
        filt = re.match(r"EVALUATE GROUPBY\(FILTER\('GenericDB', NOT ISBLANK\('GenericDB'\[(\w+)\]\)\), (.+), \"__rows\"", q_text)
        group_part = filt.group(2) if filt else q_text[len("EVALUATE GROUPBY('GenericDB', "):]
        cols = re.findall(r"'GenericDB'\[(\w+)\]", group_part.split(', "__rows"')[0])
        df = table if not filt else table[table[filt.group(1)].notna()]
        g = df.groupby(cols, dropna=False).size().reset_index(name="__rows")
        rows = [[None if pd.isna(x) else (x.item() if hasattr(x, "item") else x) for x in r]
                for r in g.itertuples(index=False)]
        results.append({"id": q["id"], "columns": cols + ["[__rows]"], "rows": rows})
    return {"app": APP, "produced_by": "pandas simulation of the PBIP", "results": results}


def test_every_generic_table_evaluated_from_source(expected):
    assert expected["status"] == "ok"
    names = [k["kpi"] for k in expected["kpis"]]
    assert names == [f"table:GenericDB.{a}" for a in ("Color", "Weight", "Diameter", "Value", "Thickness")]
    assert all(m["inventory_rows"] == m["model_rows"] for m in expected["model_tables"])


def test_source_tables_match_workbook(expected, workbook_rows):
    for k in expected["kpis"]:
        attr = k["object"].split(".", 1)[1]
        want = sorted([[o, v, 1] for o, a, v in workbook_rows if a == attr], key=lambda r: [str(x) for x in r])
        assert k["results"][0]["rows"] == want, attr


def test_pbip_columns_cover_every_attribute(workbook_rows):
    model = dax.read_tmdl(PBIP)
    assert [c["name"] for c in model["columns"]] == ["Object", "Color", "Weight", "Diameter", "Value", "Thickness"]
    assert {a for _, a, _ in workbook_rows} == {c["name"] for c in model["columns"]} - {"Object"}


def test_dax_queries_map_every_table(tmp_path, monkeypatch, expected):
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    spec = (tmp_path / f"{APP}.queries.json").read_text()
    assert '"unmapped": []' in spec
    assert "EVALUATE GROUPBY(FILTER('GenericDB', NOT ISBLANK('GenericDB'[Color])), 'GenericDB'[Object], " \
           "'GenericDB'[Color], \\\"__rows\\\", SUMX(CURRENTGROUP(), 1))" in spec


def test_simulated_pbip_passes_and_wrong_pivot_fails(tmp_path, monkeypatch, expected, workbook_rows):
    import json
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    spec = json.loads((tmp_path / f"{APP}.queries.json").read_text())
    table = _pbi_table(workbook_rows)
    report = compare.compare(expected, _simulate_dax(spec, table))
    assert report["summary"] == {"pass": 5}
    broken = table.copy()
    broken.loc[broken["Object"] == "Coin", "Diameter"] = None  # e.g. a pivot that drops a value
    status = {r["id"]: r["status"] for r in compare.compare(expected, _simulate_dax(spec, broken))["results"]}
    assert status["table:GenericDB.Diameter"] == "fail" and status["table:GenericDB.Color"] == "pass"


@pytest.mark.needs_parquet
def test_committed_expected_results_are_reproducible(tmp_path, monkeypatch):
    committed = (harness.EXPECTED / f"{APP}.json.gz").read_bytes()
    monkeypatch.setattr(harness, "EXPECTED", tmp_path)
    harness.write_expected(APP)
    assert (tmp_path / f"{APP}.json.gz").read_bytes() == committed


def test_count_column_does_not_collide_with_a_grouped_column(tmp_path, monkeypatch):
    """DAX column names are case-insensitive: GenericDB has a column named Value, so the count can't be "value"."""
    import json
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    for q in json.loads((tmp_path / f"{APP}.queries.json").read_text())["queries"]:
        grouped = {c.lower() for c in re.findall(r"'GenericDB'\[(\w+)\]", q["query"].split(", \"__rows\"")[0])}
        names = {n.lower() for n in re.findall(r', "(\w+)", SUMX', q["query"])}
        assert names and not names & grouped, q["query"]


def test_committed_dax_queries_are_current(tmp_path, monkeypatch):
    committed = (dax.DAX / f"{APP}.queries.json").read_text()
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    assert (tmp_path / f"{APP}.queries.json").read_text() == committed
