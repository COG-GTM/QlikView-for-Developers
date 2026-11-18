"""DAX side: the Ch03 PBIP maps every Ch03 KPI to a measure, and compare() catches differences."""
import copy
import json

import pytest

import compare
import dax
import harness
import build_ch03_airline
from conftest import CH03


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(CH03)


def test_committed_app_is_up_to_date(tmp_path, monkeypatch):
    monkeypatch.setattr(build_ch03_airline, "APPS", tmp_path)
    out = build_ch03_airline.build()
    committed = harness.REPO / "powerbi/apps" / out.name
    for f in out.rglob("*"):
        if f.is_file():
            assert f.read_bytes() == (committed / f.relative_to(out)).read_bytes(), f.relative_to(out)


def test_every_ch03_result_gets_a_dax_query(tmp_path, monkeypatch, expected):
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(CH03, harness.REPO / "powerbi/apps/Chapter03_Airline_Operations")
    spec = json.loads((tmp_path / f"{CH03}.queries.json").read_text())
    assert spec["unmapped"] == []
    ids = {r["id"] for k in expected["kpis"] for r in k["results"]} | \
        {r["id"] for o in expected["objects"] for r in o["results"]}
    assert {q["id"] for q in spec["queries"]} == ids
    q = next(q for q in spec["queries"] if q["id"] == "CH01#1@Year+Month")
    assert q["query"] == "EVALUATE SUMMARIZECOLUMNS('Main Data'[Year], 'Main Data'[Month], \"value\", [# of Flights])"


def _as_dax_results(expected):
    """Shape the expected rows like ADOMD output: dims as strings/datetimes, values as ints, zero rows dropped."""
    results = []
    for k in expected["kpis"]:
        for r in k["results"]:
            rows = [[str(x) for x in row[:-1]] + [int(row[-1])] for row in r["rows"] if row[-1]]
            results.append({"id": r["id"], "columns": r["grain"] + ["[value]"], "rows": rows})
    for o in expected.get("objects", []):
        for r in o["results"]:
            results.append({"id": r["id"], "columns": r["grain"], "rows": [[str(x) for x in row] for row in r["rows"]]})
    return {"app": expected["app"], "produced_by": "test", "results": results}


def test_compare_passes_on_identical_results(expected):
    report = compare.compare(expected, _as_dax_results(expected))
    assert set(report["summary"]) == {"pass"}


def test_compare_flags_wrong_and_missing_results(expected):
    results = _as_dax_results(expected)
    bad = copy.deepcopy(results)
    year = next(r for r in bad["results"] if r["id"] == "CH01#1@Year")
    year["rows"][0][-1] += 1
    bad["results"] = [r for r in bad["results"] if r["id"] != "CH02#4@total"]
    report = compare.compare(expected, bad)
    status = {r["id"]: r["status"] for r in report["results"]}
    assert status["CH01#1@Year"] == "fail" and status["CH02#4@total"] == "missing"
    assert report["summary"]["pass"] == len(status) - 2


def test_compare_rejects_another_apps_results(expected):
    results = _as_dax_results(expected)
    results["app"] = "Chapter06__Solution_Chapter 6_Airline Operations"
    with pytest.raises(ValueError):
        compare.compare(expected, results)


def test_duplicate_parity_key_is_rejected(tmp_path, monkeypatch):
    import shutil
    src = harness.REPO / "powerbi/apps/Chapter03_Airline_Operations"
    dst = tmp_path / "app"
    shutil.copytree(src, dst)
    main = next(dst.rglob("Main Data.tmdl"))
    text = main.read_text(encoding="utf-8")
    first_key = text.split("annotation ParityKey = ")[1].split()[0]
    second_key = text.split("annotation ParityKey = ")[2].split()[0]
    main.write_text(text.replace(second_key, first_key), encoding="utf-8")
    monkeypatch.setattr(dax, "DAX", tmp_path)
    with pytest.raises(ValueError, match="two measures"):
        dax.write_queries(CH03, dst)


def test_every_relationship_gets_an_integrity_query(tmp_path, monkeypatch):
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(CH03, harness.REPO / "powerbi/apps/Chapter03_Airline_Operations")
    spec = json.loads((tmp_path / f"{CH03}.queries.json").read_text())
    ids = [r["id"] for r in spec["relationships"]]
    assert len(ids) == 7
    assert "REL:'Main Data'[%Airline ID] -> 'Airlines'[%Airline ID]" in ids
    q = spec["relationships"][0]["query"]
    assert q.startswith("DEFINE VAR missing = EXCEPT(") and '"duplicate_keys"' in q


def test_compare_reports_relationship_integrity(expected):
    results = _as_dax_results(expected)
    cols = ["[unmatched_keys]", "[unmatched_rows]", "[duplicate_keys]"]
    results["results"] += [
        {"id": "REL:a -> b", "columns": cols, "rows": [[None, None, 0]]},
        {"id": "REL:c -> d", "columns": cols, "rows": [[2, 12, 0]]},
        {"id": "REL:e -> f", "columns": cols, "rows": [[None, None, 3]]},
    ]
    report = compare.compare(expected, results)
    assert set(report["summary"]) == {"pass"}
    assert report["relationship_summary"] == {"pass": 1, "warn": 1, "fail": 1}
    assert [r["status"] for r in report["relationships"]] == ["pass", "warn", "fail"]
    assert report["relationships"][1]["unmatched_rows"] == 12


def test_compare_flags_missing_relationship_results(expected):
    report = compare.compare(expected, _as_dax_results(expected), relationship_ids=["REL:a -> b"])
    assert report["relationship_summary"] == {"missing": 1}


def test_compare_reports_queries_run_dax_recorded_as_failed():
    """run_dax.ps1 keeps going past a failing query (e.g. OLS under -Role) and records {"id", "error"}."""
    expected = {"app": "X", "kpis": [{"kpi": "K#1", "label": "L", "status": "ok", "results": [
        {"id": "K#1@Carrier Name", "grain": ["Carrier Name"], "rows": [["A", 1.0]]},
        {"id": "K#1@total", "grain": [], "rows": [[1.0]]}]}]}
    err = "Column 'Carrier Name' in table 'Main Data' cannot be found or may not be used in this expression."
    results = {"app": "X", "results": [{"id": "K#1@Carrier Name", "error": err},
                                       {"id": "K#1@total", "columns": ["v"], "rows": [[1.0]]},
                                       {"id": "REL:a", "error": err}]}
    report = compare.compare(expected, results, relationship_ids=["REL:a"])
    assert report["summary"] == {"error": 1, "pass": 1}
    assert report["results"][0]["error"] == err
    assert report["relationship_summary"] == {"error": 1}
