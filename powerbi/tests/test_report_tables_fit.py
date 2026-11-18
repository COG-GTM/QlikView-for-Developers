"""Every table / pivot the shared report generator emits fits its visual: fixed column widths, no horizontal scroll."""
import json
from pathlib import Path

import pytest

APPS = Path(__file__).resolve().parents[1] / "apps"
SHARED_GENERATOR_APPS = ["Chapter08_Airline_Operations", "Chapter09_Concatenated_tables", "Chapter09_Link_table",
                         "Chapter11_Airline_Operations", "Chapter12_Airline_Operations", "Chapter13_Airline_Operations",
                         "Chapter14_Airline_Operations", "Chapter15_Airline_Operations"]


@pytest.mark.parametrize("app", SHARED_GENERATOR_APPS)
def test_every_table_column_fits_inside_its_visual(app):
    report = json.loads((APPS / app / f"{app}.Report" / "report.json").read_text())
    tables = [(c, json.loads(c["config"])["singleVisual"]) for p in report["sections"] for c in p["visualContainers"]]
    tables = [(c, v) for c, v in tables if v["visualType"] in ("tableEx", "pivotTable")]
    assert tables
    for c, v in tables:
        o = v["objects"]
        assert o["columnHeaders"][0]["properties"]["autoSizeColumnWidth"]["expr"]["Literal"]["Value"] == "false"
        widths = [float(w["properties"]["value"]["expr"]["Literal"]["Value"][:-1]) for w in o["columnWidth"]]
        assert len(widths) == len(v["prototypeQuery"]["Select"]), c["config"][:120]
        assert sum(widths) <= c["width"] - 40, (app, c["width"], widths)
