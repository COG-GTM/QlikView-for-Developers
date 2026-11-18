"""Generate the Chapter 06 Airline Operations PBIP.

Chapter 06's load script is plain loads only (Flight Data QVD, eight dimension QVDs, two Access tables, two
CSVs), so none of the Chapter 15 base model's transformations apply (no master calendar, WHERE Exists,
'Unknown' members, inline tables or Section Access). The semantic model is therefore the scaffold of the
script itself; this script adds the report page that reproduces the Dashboard sheet's two charts.

    python powerbi/tools/build_airline_ch06.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaffold_pbip import scaffold, tag  # noqa: E402

APP = "Chapter06__Solution_Chapter 6_Airline Operations"
SLUG = "Chapter06_Airline_Operations"
DEFAULT_ROOT = "C:\\QlikView-for-Developers\\powerbi\\data\\parquet\\"
MD = "Main Data"
# Qlik chart -> (visual type, position, category columns of Main Data, measures, sort measure)
VISUALS = [
    ("CH01", "Traffic per Year", "clusteredColumnChart", (20, 20, 1240, 330), ["Year", "Month"],
     ["# of Flights", "# of Enplanned Passengers", "Transported Freight", "Transported Mail"], None),
    ("CH02", "Top 10 Routes", "tableEx", (20, 370, 1240, 330), ["From - To City"],
     ["# of Flights", "# of Enplanned Passengers", "Transported Freight", "Transported Mail"], "# of Flights"),
]


def visual(oid: str, title: str, vtype: str, pos: tuple, cats: list[str], measures: list[str], sort: str | None,
           z: int) -> dict:
    x, y, w, h = pos
    ref = lambda f: f"{MD}.{f}"  # noqa: E731
    select = [{"Column": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": c}, "Name": ref(c)} for c in cats]
    select += [{"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": mz}, "Name": ref(mz)}
               for mz in measures]
    query = {"Version": 2, "From": [{"Name": "m", "Entity": MD, "Type": 0}], "Select": select}
    if vtype == "tableEx":
        projections = {"Values": [{"queryRef": ref(f)} for f in cats + measures]}
    else:
        projections = {"Category": [{"queryRef": ref(c), "active": True} for c in cats],
                       "Y": [{"queryRef": ref(mz)} for mz in measures]}
    if sort:
        query["OrderBy"] = [{"Direction": 2, "Expression": {"Measure": {
            "Expression": {"SourceRef": {"Source": "m"}}, "Property": sort}}}]
    title_obj = [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                                 "text": {"expr": {"Literal": {"Value": f"'{title}'"}}}}}]
    config = {"name": tag(SLUG, "visual", oid), "layouts": [{"id": 0, "position": {
        "x": x, "y": y, "z": z, "width": w, "height": h}}],
        "singleVisual": {"visualType": vtype, "projections": projections, "prototypeQuery": query,
                         "drillFilterOtherVisuals": True, "vcObjects": {"title": title_obj}}}
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "config": json.dumps(config), "filters": "[]"}


def build(data_root: str = DEFAULT_ROOT) -> Path:
    root = scaffold(APP, data_root)
    containers = [visual(*v, z=i) for i, v in enumerate(VISUALS)]
    report = root / f"{SLUG}.Report" / "report.json"
    report.write_text(json.dumps({
        "config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
        "layoutOptimization": 0, "resourcePackages": [],
        "sections": [{"name": "ReportSection", "displayName": "Dashboard", "displayOption": 1, "ordinal": 0,
                      "width": 1280, "height": 720, "config": "{}", "filters": "[]",
                      "visualContainers": containers}]}, indent=2) + "\n")
    print(f"{report.parent.name}: page Dashboard, {len(containers)} visuals")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
