"""Chapter10/Production Planning.qvw: the report-style text file parsed like QlikView's transformation steps."""
import copy
import json
import zlib

import pytest

import compare
import dax
import harness
from engine import SourceModel

APP = "Chapter10__Production Planning"
PBIP = harness.REPO / "powerbi/apps/Chapter10_Production_Planning"
QVW = harness.REPO / "Chapter10/Production Planning.qvw"
FIELDS = ["Date", "Plant #", "Product Line ID", "Estimated Production"]


@pytest.fixture(scope="module")
def expected():
    return harness.load_expected(APP)


def test_committed_expected_results_are_reproducible(expected):
    fresh = harness.cmd_source(APP)
    for k in ("status", "model_tables", "kpis", "objects"):
        assert fresh[k] == expected[k], k


def test_model_has_the_qlik_row_count(expected):
    assert expected["status"] == "ok"
    assert expected["model_tables"] == [{"table": "Production Planning - Legacy", "inventory_rows": 50, "model_rows": 50}]
    rows = {o["object"]: o["results"][0]["rows"] for o in expected["objects"]}
    assert rows["ROWS"] == [[50]]
    assert len(rows["TB01"]) == 50 and len(rows["LB01"]) == 37 and len(rows["LB02"]) == 40


def _symbols(block: bytes) -> list[str] | None:
    """A QVW symbol table: int32 0, int32 count, then per value 04 <len> <text> (text) or
    05 <len> <text> <int32> / 06 <len> <text> <double> (dual); returns the texts."""
    if len(block) < 8 or block[:4] != bytes(4):
        return None
    count, out, i = int.from_bytes(block[4:8], "little"), [], 8
    while i < len(block):
        t = block[i]
        if t not in (4, 5, 6) or i + 2 + block[i + 1] > len(block):
            return None
        n = block[i + 1]
        out.append(block[i + 2:i + 2 + n].decode("latin-1"))
        i += 2 + n + {4: 0, 5: 4, 6: 8}[t]
    return out if len(out) == count else None


def _qvw_rows() -> list[list[str]]:
    """The 50 rows QlikView stored in the .qvw: the four field symbol tables, then the bit-packed record table."""
    data, blocks = QVW.read_bytes(), []
    pos = 23
    while pos < len(data):
        d = zlib.decompressobj()
        try:
            blocks.append(d.decompress(data[pos:]))
        except zlib.error:
            pos += 1
            continue
        pos = len(data) - len(d.unused_data)
    sizes = {"Date": 40, "Plant #": 2, "Product Line ID": 3, "Estimated Production": 37}
    for i in range(len(blocks) - 4):
        syms = [_symbols(b) for b in blocks[i:i + 4]]
        if [len(s or []) for s in syms] == list(sizes.values()):
            break
    else:
        raise AssertionError("field symbol tables not found")
    table = dict(zip(FIELDS, syms))
    record = next(b for b in blocks[i + 4:] if len(b) == 100)  # 50 rows x 16 bits
    # Bit layout (low to high): Date 6, Estimated Production 6, Product Line ID 2, Plant # 1
    layout = [("Date", 6), ("Estimated Production", 6), ("Product Line ID", 2), ("Plant #", 1)]
    rows = []
    for r in range(50):
        word, shift, row = int.from_bytes(record[2 * r:2 * r + 2], "little"), 0, {}
        for f, bits in layout:
            row[f] = table[f][(word >> shift) & ((1 << bits) - 1)]
            shift += bits
        rows.append([row[f] for f in FIELDS])
    return rows


def test_source_model_matches_the_rows_stored_in_the_qvw():
    model = SourceModel(APP)
    ours = model.con.execute('SELECT * FROM "Production Planning - Legacy"').fetchall()
    assert sorted(map(lambda r: [str(x) for x in r], ours)) == sorted(_qvw_rows())


def test_pbip_table_and_partition_follow_the_qlik_load():
    tmdl = (PBIP / "Chapter10_Production_Planning.SemanticModel/definition/tables/Production Planning - Legacy.tmdl")
    text = tmdl.read_text(encoding="utf-8")
    model = dax.read_tmdl(PBIP)
    assert [c["name"] for c in model["columns"]] == FIELDS
    assert "dataType: string" in text.split("column 'Product Line ID'")[1].split("column")[0]
    for step in ("Pos(Top, 6)", "StrCnd(contain, 'Total')", "Unwrap(Col, Pos(Top, 5))", "contain 'Date'",
                 "Replace(1, top, StrCnd(null))", "Csv.Document", "Table.FillDown", "Table.PromoteHeaders"):
        assert step in text, step
    rels = PBIP / "Chapter10_Production_Planning.SemanticModel/definition/relationships.tmdl"
    assert rels.read_text().strip() == ""


def test_every_result_gets_a_dax_query(tmp_path, monkeypatch, expected):
    monkeypatch.setattr(dax, "DAX", tmp_path)
    dax.write_queries(APP, PBIP)
    spec = json.loads((tmp_path / f"{APP}.queries.json").read_text())
    assert spec["unmapped"] == []
    ids = {r["id"] for o in expected["objects"] for r in o["results"]}
    assert {q["id"] for q in spec["queries"]} == ids
    q = {q["id"]: q["query"] for q in spec["queries"]}
    assert q["LB02@Date"] == ("EVALUATE FILTER(SUMMARIZECOLUMNS('Production Planning - Legacy'[Date]), "
                              "NOT ISBLANK('Production Planning - Legacy'[Date]))")
    assert q["TB01@Date+Plant #+Product Line ID+Estimated Production"].startswith("EVALUATE SUMMARIZECOLUMNS(")
    assert q["ROWS@Production Planning - Legacy"] == "EVALUATE ROW(\"value\", COUNTROWS('Production Planning - Legacy'))"


def _as_dax_results(expected):
    results = []
    for o in expected["objects"]:
        for r in o["results"]:
            cols = [f"'Production Planning - Legacy'[{f}]" for f in r["grain"]] or ["[value]"]
            results.append({"id": r["id"], "columns": cols, "rows": [[x for x in row] for row in r["rows"]]})
    return {"app": APP, "produced_by": "test", "results": results}


def test_compare_passes_on_identical_rows(expected):
    report = compare.compare(expected, _as_dax_results(expected))
    assert set(report["summary"]) == {"pass"} and report["summary"]["pass"] == 4


def test_compare_flags_a_missing_and_a_wrong_row(expected):
    bad = copy.deepcopy(_as_dax_results(expected))
    tb = next(r for r in bad["results"] if r["id"].startswith("TB01@"))
    tb["rows"].pop()
    lb = next(r for r in bad["results"] if r["id"] == "LB02@Date")
    lb["rows"][0] = [19990101]
    report = compare.compare(expected, bad)
    status = {r["id"]: r["status"] for r in report["results"]}
    assert status[tb["id"]] == "fail" and status["LB02@Date"] == "fail"
    assert status["ROWS@Production Planning - Legacy"] == "pass"


def test_compare_keeps_text_labels_exact(expected):
    bad = copy.deepcopy(_as_dax_results(expected))
    tb = next(r for r in bad["results"] if r["id"].startswith("TB01@"))
    tb["rows"] = [[d, p, str(int(pl)), e] for d, p, pl, e in tb["rows"]]  # '03' -> '3'
    status = {r["id"]: r["status"] for r in compare.compare(expected, bad)["results"]}
    assert status[tb["id"]] == "fail"
