import json

import pytest

import verify_conversion as vc
from conftest import CH03


@pytest.mark.needs_parquet
def test_every_parquet_table_matches_its_source_row_count():
    rows = vc.check_integrity(json.loads(vc.CATALOG.read_text()))
    assert rows and all(r["ok"] for r in rows), [r for r in rows if not r["ok"]]


def test_inventory_row_counts_have_no_unexplained_mismatch():
    rows = vc.check_inventory(json.loads(vc.CATALOG.read_text()))
    assert not [r for r in rows if r["status"] == "MISMATCH"]


def test_chapter03_tables_all_match_inventory():
    rows = [r for r in vc.check_inventory(json.loads(vc.CATALOG.read_text())) if r["app"] == CH03]
    assert {r["table"]: (r["status"], r["parquet_rows"]) for r in rows} == {
        "Main Data": ("match", 1256075), "Carrier Groups": ("match", 8), "Airlines": ("match", 1548),
        "Carrier Operating Region": ("match", 6), "Flight Types": ("match", 4), "Aircraft Groups": ("match", 10),
        "Aircraft Types": ("match", 379), "Distance Groups": ("match", 25)}


def test_every_qvd_and_access_table_is_converted():
    cat = json.loads(vc.CATALOG.read_text())["sources"]
    qvds = [p for p in vc.REPO.rglob("*") if p.suffix.lower() == ".qvd" and "powerbi" not in p.parts]
    assert {p.relative_to(vc.REPO).as_posix() for p in qvds} <= set(cat)
    assert len(cat["Data Files/MDBs/Dimension Tables.mdb"]["tables"]) == 17


def test_plain_load_with_missing_source_fails():
    catalog = json.loads(vc.CATALOG.read_text())
    del catalog["sources"]["Data Files/CSVs/Origin Markets.csv"]
    rows = [r for r in vc.check_inventory(catalog) if r["table"] == "Origin Markets" and r["app"].startswith("Chapter04")]
    assert [r["status"] for r in rows] == ["MISSING_SOURCE"]


def test_exception_only_covers_the_recorded_counts():
    catalog = json.loads(vc.CATALOG.read_text())
    mdb = catalog["sources"]["Data Files/MDBs/Dimension Tables.mdb"]["tables"]
    next(t for t in mdb if t["table"] == "Origin Airports")["rows"] = 0
    rows = [r for r in vc.check_inventory(catalog) if r["table"] == "Origin Airports" and r["app"].startswith("Chapter04")]
    assert [r["status"] for r in rows] == ["MISMATCH"]


@pytest.mark.needs_parquet
def test_exception_superset_claim_is_checked():
    exc = json.loads(vc.EXCEPTIONS.read_text())["exceptions"][0]
    assert vc.coverage_problem(exc["covers"]) is None
    wrong = {**exc["covers"], "key": "%Origin Airport ID", "table": "powerbi/data/parquet/Data Files/QVDs/Airlines.parquet"}
    wrong["key"] = "%Airline ID"
    assert "missing" in vc.coverage_problem(wrong)
