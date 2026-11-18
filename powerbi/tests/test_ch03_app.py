"""Ch03 Airline Operations PBIP: model, list-box parity and report pages match the .qvw."""
import gzip
import json
import re

import pytest

import build_ch03_airline as ch03
import dax
import harness
from conftest import CH03

APP = harness.REPO / "powerbi/apps/Chapter03_Airline_Operations"
needs_parquet = pytest.mark.needs_parquet


def _expected():
    return json.loads(gzip.open(harness.REPO / f"powerbi/parity/expected/{CH03}.json.gz").read())


def _report():
    return json.loads((APP / "Chapter03_Airline_Operations.Report/report.json").read_text())


def test_every_sheet_list_box_is_a_parity_object_and_a_slicer():
    objects = {o["id"]: o["fields"][0] for o in json.loads(
        (harness.REPO / f"powerbi/parity/objects/{CH03}.json").read_text())["objects"]}
    assert objects == dict(ch03.SHEET_MAIN + ch03.SHEET_DASHBOARD)
    slicers = {}
    for page in _report()["sections"]:
        for v in page["visualContainers"]:
            cfg = json.loads(v["config"])
            if cfg["singleVisual"]["visualType"] == "slicer" and "display" not in cfg["singleVisual"]:
                slicers[cfg["name"].split("_")[-1]] = cfg["singleVisual"]["prototypeQuery"]["Select"][0]["Column"]["Property"]
    assert {k: v for k, v in slicers.items() if k != "SO01"} == objects


def test_selections_are_synced_across_pages():
    groups = {}
    for page in _report()["sections"]:
        for v in page["visualContainers"]:
            sv = json.loads(v["config"])["singleVisual"]
            if sv["visualType"] == "slicer":
                field = sv["prototypeQuery"]["Select"][0]["Column"]["Property"]
                assert sv["syncGroup"]["groupName"] == field
                groups.setdefault(field, set()).add(page["displayName"])
    assert all(pages == {"Main", "Dashboard"} for pages in groups.values()), groups


def test_report_pages_mirror_qlik_sheets():
    pages = {p["displayName"]: p for p in _report()["sections"]}
    assert list(pages) == ["Main", "Dashboard"]
    visuals = {json.loads(v["config"])["name"].removeprefix(ch03.SLUG + "_"): json.loads(v["config"])["singleVisual"]
               for v in pages["Dashboard"]["visualContainers"]}
    ch01, ch02 = visuals["CH01"], visuals["CH02"]
    assert ch01["visualType"] == "clusteredColumnChart"
    assert [p["queryRef"] for p in ch01["projections"]["Category"]] == ["Main Data.Time.Year", "Main Data.Time.Month"]
    measures = ["# of Flights", "# of Enplanned Passengers", "Transported Freight", "Transported Mail"]
    assert [p["queryRef"] for p in ch01["projections"]["Y"]] == [f"Main Data.{m}" for m in measures]
    assert ch02["visualType"] == "tableEx"
    assert [p["queryRef"] for p in ch02["projections"]["Values"]] == \
        ["Main Data.From - To City"] + [f"Main Data.{m}" for m in measures]
    ch02_filters = json.loads(next(v for v in pages["Dashboard"]["visualContainers"]
                                   if json.loads(v["config"])["name"].endswith("_CH02"))["filters"])
    assert ch02_filters[0]["type"] == "TopN"
    assert ch02_filters[0]["filter"]["From"][0]["Expression"]["Subquery"]["Query"]["Top"] == 10


def test_time_drill_down_is_a_hierarchy_on_year_then_month():
    text = (APP / "Chapter03_Airline_Operations.SemanticModel/definition/tables/Main Data.tmdl").read_text()
    block = text[text.index("\thierarchy Time"):text.index("\tpartition")]
    assert re.findall(r"column: (\S+)", block) == ["Year", "Month"]


def test_key_fields_hidden_and_every_dimension_related():
    model = dax.read_tmdl(APP)
    assert all(c["hidden"] for c in model["columns"] if c["name"].startswith("%"))
    text = (APP / "Chapter03_Airline_Operations.SemanticModel/definition/relationships.tmdl").read_text()
    pairs = re.findall(r"fromColumn: (.+)\n\ttoColumn: (.+)", text)
    assert pairs == [(f"'Main Data'.'{key}'", f"{dax.dax_table(t) if not t.isidentifier() else t}.'{key}'")
                     for t, _, key, _ in ch03.DIMENSIONS]
    assert len(dax.read_relationships(APP)) == len(ch03.DIMENSIONS)


def test_no_reserved_looking_dax_vars():
    texts = [f.read_text() for f in APP.rglob("*.tmdl")]
    texts.append((harness.REPO / f"powerbi/parity/dax/{CH03}.queries.json").read_text())
    names = {n.lower() for t in texts for n in re.findall(r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)", t)}
    assert not names & {"levels", "level", "values", "filter", "all", "table", "column", "measure", "year", "month"}


@needs_parquet
def test_list_boxes_match_parquet_distinct_values():
    import pandas as pd
    flight = pd.read_parquet(harness.REPO / "powerbi/data/parquet/Data Files/QVDs/Flight Data.parquet")
    dims = {label: pd.read_parquet(harness.REPO / f"powerbi/data/parquet/Data Files/QVDs/{qvd}.parquet")
            for _, qvd, _, label in ch03.DIMENSIONS}
    for o in _expected()["objects"]:
        field = o["fields"][0]
        col = dims[field][field] if field in dims else flight[field]
        values = sorted(str(v) for v in col.dropna().unique())
        assert sorted(str(r[0]) for r in o["results"][0]["rows"]) == values, o["object"]
