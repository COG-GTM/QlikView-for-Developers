"""Chapter 10 Hierarchy example: Qlik HIERARCHY() -> parent/child table + DAX PATH columns.

The source model (parity/models/Chapter10__Hierarchy example.sql) must reproduce the expanded
nodes Qlik stored in the .qvw, checked against an independent pandas walk of the original .xls
and against the Path values found in the .qvw itself; the TMDL must expose every Qlik field.
"""
import copy
import gzip
import json
import zlib

import pandas as pd
import pytest

import compare
import dax
import harness

APP = "Chapter10__Hierarchy example"
PBIP = harness.REPO / "powerbi/apps/Chapter10_Hierarchy_example"
FIELDS = ["Parent_ID", "Child_ID", "Parent", "Child", "Child1", "Child2", "Child3", "Child4", "ParentName", "Path", "Depth"]


@pytest.fixture(scope="module")
def table():
    t = harness.load_expected(APP)["tables"]
    assert [x["table"] for x in t] == ["Sheet1$-ExpandedNodes"]
    return t[0]


def _expand(src: pd.DataFrame) -> list[list]:
    parent = {int(r.Child_ID): (None if pd.isna(r.Parent_ID) else int(r.Parent_ID)) for r in src.itertuples()}
    name = {int(r.Child_ID): r.Child for r in src.itertuples()}
    rows = []
    for r in src.itertuples():
        chain, node = [], int(r.Child_ID)
        while node is not None:
            chain.insert(0, name[node])
            node = parent[node]
        pid = parent[int(r.Child_ID)]
        rows.append([pid, int(r.Child_ID), None if pd.isna(r.Parent) else r.Parent, r.Child,
                     *(chain + [None] * 4)[:4], name.get(pid), " - ".join(chain), len(chain)])
    return sorted(rows, key=lambda r: [str(x) for x in r])


def test_expected_snapshot_matches_independent_walk_of_original_xls(table):
    src = pd.read_excel(harness.REPO / "Chapter10/Hierarchy example.xls", sheet_name="Sheet1", engine="xlrd")
    assert table["columns"] == FIELDS
    assert table["row_count"] == 10
    assert table["rows"] == _expand(src)


def _inflate(raw: bytes, at: int) -> bytes:
    try:
        return zlib.decompressobj().decompress(raw[at:])
    except zlib.error:
        return b""


def test_paths_match_the_values_stored_in_the_qvw(table):
    raw = (harness.REPO / "Chapter10/Hierarchy example.qvw").read_bytes()
    blob = raw + b"".join(_inflate(raw, i) for i in range(len(raw) - 1) if raw[i] == 0x78 and raw[i + 1] in (0x01, 0x9C, 0xDA))
    for path in (r[FIELDS.index("Path")] for r in table["rows"]):
        assert path.encode("latin-1") in blob, path


def test_expected_is_reproducible():
    committed = gzip.decompress((harness.EXPECTED / f"{APP}.json.gz").read_bytes())
    assert json.loads(committed)["tables"] == harness.cmd_source(APP)["tables"]


def test_every_qlik_field_maps_to_a_tmdl_column(tmp_path, monkeypatch, table):
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    spec = json.loads((tmp_path / f"{APP}.queries.json").read_text())
    assert spec["unmapped"] == []
    [q] = spec["queries"]
    assert q["id"] == "table:Sheet1$-ExpandedNodes" and q["columns"] == FIELDS
    t = "'Sheet1$-ExpandedNodes'"
    assert q["query"].startswith(f"EVALUATE SELECTCOLUMNS({t}, \"Parent_ID\", {t}[Parent_ID], \"Child_ID\", {t}[Child_ID],")


def test_table_compare_passes_on_same_rows_and_catches_a_wrong_path(table):
    expected = harness.load_expected(APP)
    shuffled = {"app": APP, "produced_by": "test", "results": [{"id": table["id"], "rows": list(reversed(table["rows"]))}]}
    assert compare.compare(expected, shuffled, 1e-9, 1e-6)["summary"] == {"pass": 1}
    wrong = copy.deepcopy(shuffled)
    wrong["results"][0]["rows"][0][FIELDS.index("Path")] = "World - Atlantis"
    res = compare.compare(expected, wrong, 1e-9, 1e-6)
    assert res["summary"] == {"fail": 1} and res["results"][0]["mismatches"] == 2
