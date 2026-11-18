"""Chapter10/Generic Load: GENERIC LOAD parity on the source side, and the PBIP is ready for the DAX run.

QlikView builds one table per attribute (GenericDB.Color, ...); the PBIP pivots the same rows into one
GenericDB table with Table.Pivot. The app's only sheet has no charts, so parity/checks/ pins each
attribute's value per Object. The expected results must equal the workbook read independently with
openpyxl, and DAX-shaped results computed from a pandas pivot must pass compare.
"""
import json
import re

import openpyxl
import pandas as pd
import pytest

import compare
import dax
import harness

APP = "Chapter10__Generic Load"
PBIP = harness.REPO / "powerbi/apps/Chapter10_Generic_Load"
TMDL = PBIP / "Chapter10_Generic_Load.SemanticModel/definition/tables/GenericDB.tmdl"
ATTRS = ["Color", "Weight", "Diameter", "Value", "Thickness"]


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def long():
    ws = openpyxl.load_workbook(harness.REPO / "Chapter10/Generic DB.xlsx", read_only=True)["GenericDB"]
    header, *rows = list(ws.values)
    assert header == ("Object", "Attribute", "Value")
    return pd.DataFrame(rows, columns=list(header))


@pytest.fixture(scope="module")
def pivoted(long):
    """What the GenericDB partition produces: one row per Object, one column per Attribute."""
    assert not long.duplicated(["Object", "Attribute"]).any()  # Table.Pivot without aggregation needs this
    return long.pivot(index="Object", columns="Attribute", values="Value").reindex(columns=ATTRS).reset_index()


def _rows(expected, rid):
    return next(r["rows"] for k in expected["kpis"] for r in k["results"] if r["id"] == rid)


def test_all_checks_evaluated(expected):
    assert expected["status"] == "ok"
    assert expected["model_source"] == f"powerbi/parity/models/{APP}.sql"
    assert [k["kpi"] for k in expected["kpis"]] == [f"CHK0{i}#1" for i in range(1, 7)]
    assert all(k["status"] == "ok" for k in expected["kpis"])
    assert [(t["table"], t["model_rows"]) for t in expected["model_tables"]] == \
        [(f"GenericDB.{a}", n) for a, n in zip(ATTRS, [3, 2, 3, 1, 1])]
    assert all(t["inventory_rows"] == t["model_rows"] for t in expected["model_tables"])


def test_checks_match_workbook(expected, long):
    for i, attr in enumerate(ATTRS, 1):
        sub = long[long["Attribute"] == attr]
        if attr == "Value":
            assert _rows(expected, "CHK04#1@Object") == [[o, float(v)] for o, v in zip(sub["Object"], sub["Value"])]
            continue
        got = {(o, v): n for o, v, n in _rows(expected, f"CHK0{i}#1@Object+{attr}") if n}
        assert got == {(o, v): 1 for o, v in zip(sub["Object"], sub["Value"])}, attr
        assert _rows(expected, f"CHK0{i}#1@total") == [[len(sub)]]
    assert _rows(expected, "CHK06#1@total") == [[long["Object"].nunique()]]


def test_power_query_mirrors_the_load_script(long):
    script = (harness.INVENTORY / "scripts" / f"{APP}.qvs").read_text(encoding="utf-8")
    assert re.search(r"GENERIC LOAD Object,\s*Attribute,\s*Value\s+FROM\s+\[Generic DB\.xlsx\]", script)
    tmdl = TMDL.read_text(encoding="utf-8")
    pivot = re.search(r'Table\.Pivot\(Selected, \{(.*?)\}, "Attribute", "Value"\)', tmdl).group(1)
    assert re.findall(r'"([^"]+)"', pivot) == ATTRS
    assert set(long["Attribute"]) == set(ATTRS)
    assert [c["name"] for c in dax.read_tmdl(PBIP)["columns"]] == ["Object", *ATTRS]


def test_every_check_gets_a_dax_query(tmp_path, monkeypatch, expected):
    committed = dax.DAX / f"{APP}.queries.json"
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    spec = json.loads((tmp_path / f"{APP}.queries.json").read_text())
    assert spec["unmapped"] == []
    assert {q["id"] for q in spec["queries"]} == {r["id"] for k in expected["kpis"] for r in k["results"]}
    q = next(q for q in spec["queries"] if q["id"] == "CHK01#1@Object+Color")
    assert q["query"] == "EVALUATE SUMMARIZECOLUMNS('GenericDB'[Object], 'GenericDB'[Color], \"value\", [Color Count])"
    assert committed.read_text() == (tmp_path / f"{APP}.queries.json").read_text()  # committed copy is current


def test_compare_against_pivot_shaped_like_dax_output(expected, pivoted):
    """SUMMARIZECOLUMNS over the pivoted table (blank measure rows dropped) passes; a lost value fails."""
    def results(df):
        out = []
        for k in expected["kpis"]:
            for r in k["results"]:
                g, field = r["grain"], re.search(r"(\w+)\)$", k["expression"]).group(1)
                if "DISTINCT" in k["expression"]:
                    rows = [[int(df["Object"].nunique())]]
                elif field == "Value":
                    vals = df[df["Value"].notna()]
                    rows = [[o, int(v)] for o, v in zip(vals["Object"], vals["Value"])] if g else [[int(vals["Value"].sum())]]
                else:
                    vals = df[df[field].notna()]
                    rows = [[*key, int(n)] for key, n in vals.groupby(g).size().items()] if g else [[len(vals)]]
                out.append({"id": r["id"], "columns": g + ["[value]"], "rows": rows})
        return {"app": APP, "produced_by": "test", "results": out}

    assert set(compare.compare(expected, results(pivoted))["summary"]) == {"pass"}
    broken = pivoted.copy()
    broken.loc[broken["Object"] == "Coin", "Diameter"] = None
    assert compare.compare(expected, results(broken))["summary"]["fail"] >= 1


@pytest.mark.needs_parquet
def test_committed_expected_results_are_reproducible(tmp_path, monkeypatch):
    committed = (harness.EXPECTED / f"{APP}.json.gz").read_bytes()
    monkeypatch.setattr(harness, "EXPECTED", tmp_path)
    harness.write_expected(APP)
    assert (tmp_path / f"{APP}.json.gz").read_bytes() == committed
