"""Chapter10/Crosstable example: CROSSTABLE parity on the source side, and the PBIP is ready for the DAX run.

The app's only sheet has no charts, so parity/checks/ pins the unpivoted table itself. The
source model (DuckDB UNPIVOT over the Parquet) must equal an independent pandas melt of the
original .xls, and every check must map to an annotated measure of the hand-written PBIP.
"""
import json
import re

import pandas as pd
import pytest
import xlrd

import compare
import dax
import harness
from engine import SourceModel

APP = "Chapter10__Crosstable example"
PBIP = harness.REPO / "powerbi/apps/Chapter10_Crosstable_example"
TMDL = PBIP / "Chapter10_Crosstable_example.SemanticModel/definition/tables/Sheet1$.tmdl"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


@pytest.fixture(scope="module")
def melted():
    """CROSSTABLE(Month, Sales) recomputed from the original workbook, without the converter or DuckDB."""
    sheet = xlrd.open_workbook(harness.REPO / "Chapter10/Crosstable example.xls").sheet_by_name("Sheet1")
    rows = [sheet.row_values(i) for i in range(sheet.nrows)]
    df = pd.DataFrame(rows[1:], columns=rows[0])
    return df.melt(id_vars=["Department"], value_vars=MONTHS, var_name="Month", value_name="Sales")


def _rows(expected, rid):
    return next(r["rows"] for k in expected["kpis"] for r in k["results"] if r["id"] == rid)


def test_all_checks_evaluated(expected):
    assert expected["status"] == "ok"
    assert expected["model_source"] == f"powerbi/parity/models/{APP}.sql"
    assert [k["kpi"] for k in expected["kpis"]] == ["CHK01#1", "CHK02#1", "CHK03#1", "CHK04#1"]
    assert all(k["status"] == "ok" for k in expected["kpis"])
    assert expected["model_tables"] == [{"table": "Sheet1$", "inventory_rows": 48, "model_rows": 48}]


def test_checks_match_independent_melt_of_original_xls(expected, melted):
    assert len(melted) == 48
    assert {(d, m): v for d, m, v in _rows(expected, "CHK01#1@Department+Month")} == \
        {(d, m): float(v) for d, m, v in melted.itertuples(index=False)}
    assert _rows(expected, "CHK01#1@total") == [[float(melted["Sales"].sum())]]
    assert dict(map(tuple, _rows(expected, "CHK02#1@Department"))) == \
        {d: float(v) for d, v in melted.groupby("Department")["Sales"].sum().items()}
    assert dict(map(tuple, _rows(expected, "CHK03#1@Month"))) == \
        {m: float(v) for m, v in melted.groupby("Month")["Sales"].sum().items()}
    assert dict(map(tuple, _rows(expected, "CHK04#1@Department"))) == {d: 12 for d in "ABCD"}


@pytest.mark.needs_parquet
def test_source_model_is_the_crosstable_of_the_parquet(melted):
    model = SourceModel(APP)
    assert model.columns["Sheet1$"] == ["Department", "Month", "Sales"]
    got = model.con.execute('SELECT Department, Month, Sales FROM "Sheet1$"').fetchdf()
    key = ["Department", "Month"]
    pd.testing.assert_frame_equal(got.sort_values(key).reset_index(drop=True),
                                  melted.sort_values(key).reset_index(drop=True), check_dtype=False)


@pytest.mark.needs_parquet
def test_committed_expected_results_are_reproducible(tmp_path, monkeypatch):
    committed = (harness.EXPECTED / f"{APP}.json.gz").read_bytes()
    monkeypatch.setattr(harness, "EXPECTED", tmp_path)
    harness.write_expected(APP)
    assert (tmp_path / f"{APP}.json.gz").read_bytes() == committed


def test_power_query_mirrors_the_load_script():
    """The M partition unpivots exactly the columns the CROSSTABLE LOAD lists, keeping Department as qualifier."""
    script = (harness.INVENTORY / "scripts" / f"{APP}.qvs").read_text(encoding="utf-8")
    m = re.search(r"CrossTable\((\w+),\s*(\w+)\)\s*LOAD\s+(.*?)\s+FROM", script, re.S | re.I)
    attr, data, fields = m.group(1), m.group(2), [f.strip() for f in m.group(3).split(",")]
    tmdl = TMDL.read_text(encoding="utf-8")
    selected = re.search(r"Table\.SelectColumns\(Source, \{(.*?)\}\)", tmdl).group(1)
    assert [c.strip().strip('"') for c in selected.split(",")] == fields
    assert f'Table.UnpivotOtherColumns(Selected, {{"{fields[0]}"}}, "{attr}", "{data}")' in tmdl
    assert fields[1:] == MONTHS


def test_every_check_gets_a_dax_query(tmp_path, monkeypatch, expected):
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    spec = json.loads((tmp_path / f"{APP}.queries.json").read_text())
    assert spec["unmapped"] == []
    assert {q["id"] for q in spec["queries"]} == {r["id"] for k in expected["kpis"] for r in k["results"]}
    q = next(q for q in spec["queries"] if q["id"] == "CHK01#1@Department+Month")
    assert q["query"] == "EVALUATE SUMMARIZECOLUMNS('Sheet1$'[Department], 'Sheet1$'[Month], \"value\", [Total Sales])"


def test_compare_against_melt_shaped_like_dax_output(expected, melted):
    """Results built from the independent melt, shaped like ADOMD output, pass; a changed cell fails."""
    def results(df):
        out = []
        for k in expected["kpis"]:
            for r in k["results"]:
                g = r["grain"]
                agg = "count" if k["expression"].startswith("Count") else "sum"
                if g:
                    rows = [[*((key,) if len(g) == 1 else key), int(v)]
                            for key, v in df.groupby(g)["Sales"].agg(agg).items()]
                else:
                    rows = [[int(df["Sales"].agg(agg))]]
                out.append({"id": r["id"], "columns": g + ["[value]"], "rows": rows})
        return {"app": APP, "produced_by": "test", "results": out}

    assert set(compare.compare(expected, results(melted))["summary"]) == {"pass"}
    broken = melted.copy()
    broken.loc[0, "Sales"] += 1
    assert compare.compare(expected, results(broken))["summary"]["fail"] >= 1
