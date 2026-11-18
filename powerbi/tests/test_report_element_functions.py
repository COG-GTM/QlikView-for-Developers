"""Ch12-15 report fixes: e(Year) charts list the years the selection excludes (rows from a disconnected year table, not
the selection-filtered calendar), and QlikView 'Always One Selected' list boxes open with their default selected."""
import json
from pathlib import Path

import pytest

APPS = Path(__file__).resolve().parents[1] / "apps"
SLUGS = [f"Chapter{n}_Airline_Operations" for n in (12, 13, 14, 15)]


def visuals(slug: str):
    report = json.loads((APPS / slug / f"{slug}.Report" / "report.json").read_text())
    for sec in report["sections"]:
        for vc in sec["visualContainers"]:
            yield sec["displayName"], json.loads(vc["config"])["singleVisual"]


def title(single: dict) -> str:
    return single["vcObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"]


@pytest.mark.parametrize("slug", SLUGS)
def test_element_functions_rows_come_from_excluded_years(slug):
    tables = [s for _, s in visuals(slug) if title(s) == "'Element Functions example'"]
    assert len(tables) == 1
    single = tables[0]
    entities = {f["Entity"] for f in single["prototypeQuery"]["From"]}
    assert "Excluded Years" in entities and "Master Calendar" not in entities
    assert single["columnProperties"]["Excluded Years.Excluded Year"]["displayName"] == "Year"
    tmdl = APPS / slug / f"{slug}.SemanticModel" / "definition"
    assert (tmdl / "tables" / "Excluded Years.tmdl").exists()
    assert "Excluded Years" not in (tmdl / "relationships.tmdl").read_text()  # disconnected


@pytest.mark.parametrize("slug", SLUGS)
def test_metric_name_slicers_open_with_one_value_selected(slug):
    slicers = [s for _, s in visuals(slug) if s["visualType"] == "slicer"
               and s["prototypeQuery"]["Select"][0]["Name"].endswith(".Metric Name")]
    assert slicers
    for s in slicers:
        where = s["objects"]["general"][0]["properties"]["filter"]["filter"]["Where"][0]["Condition"]["In"]
        assert where["Values"] == [[{"Literal": {"Value": "'# of Flights'"}}]]
        assert s["objects"]["selection"][0]["properties"]["singleSelect"]["expr"]["Literal"]["Value"] == "true"
