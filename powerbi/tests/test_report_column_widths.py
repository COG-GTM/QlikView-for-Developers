"""Tables and pivots with fixed column widths fit inside their visual: the widths sum to less than the visual width,
so Power BI Desktop shows no horizontal scroll and no measure column is cut off."""
import json
from pathlib import Path

import pytest

APPS = Path(__file__).resolve().parents[1] / "apps"
REPORTS = sorted(APPS.glob("*/*.Report/report.json"))


def sized_tables(report: Path):
    for sec in json.loads(report.read_text(encoding="utf-8"))["sections"]:
        for vc in sec["visualContainers"]:
            single = json.loads(vc["config"])["singleVisual"]
            widths = single.get("objects", {}).get("columnWidth")
            if single["visualType"] in ("tableEx", "pivotTable") and widths:
                yield sec["displayName"], vc, single, widths


@pytest.mark.parametrize("report", REPORTS, ids=[r.parts[-3] for r in REPORTS])
def test_table_columns_fit_visual(report):
    for page, vc, single, widths in sized_tables(report):
        total = sum(float(w["properties"]["value"]["expr"]["Literal"]["Value"].rstrip("D")) for w in widths)
        assert total < vc["width"], f"{page}: {single['visualType']} columns sum to {total} in a {vc['width']}px visual"
        refs = {s["Name"] for s in single["prototypeQuery"]["Select"]}
        assert refs == {w["selector"]["metadata"] for w in widths}, f"{page}: column without a fixed width"
