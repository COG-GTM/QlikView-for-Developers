"""Generate the Chapter 06 Airline Operations PBIP.

Chapter 06's load script is plain loads only (Flight Data QVD, eight dimension QVDs, two Access tables, two
CSVs), so none of the Chapter 15 base model's transformations apply (no master calendar, WHERE Exists,
'Unknown' members, inline tables or Section Access). The semantic model is therefore the scaffold of the
script itself; this script adds the report pages that reproduce the Main and Dashboard sheets. Each list box
becomes a slicer on the field its caption names, and the multi box becomes one dropdown slicer per field. The
object ids, captions and multi box fields were read from the .qvw document block, because the manifest only
records object ids.

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
# Sheet -> list boxes as (object id, field), in sheet object order
LIST_BOXES = {
    "Main": [("LB09", "Distance Interval"), ("LB11", "Aircraft Group"), ("LB12", "Flight Type"),
             ("LB10", "Aircraft Type"), ("LB15", "Carrier Group"), ("LB03", "Destination City"),
             ("LB05", "Origin State"), ("LB06", "Origin City"), ("LB02", "Destination State"),
             ("LB07", "Carrier Name"), ("LB13", "Carrier's Operating Region"), ("LB01", "Destination Country"),
             ("LB04", "Origin Country")],
    "Dashboard": [("LB32", "Year"), ("LB31", "Quarter"), ("LB30", "Month"), ("LB28", "Carrier's Operating Region"),
                  ("LB29", "Carrier Group"), ("LB33", "Carrier Name"), ("LB27", "Flight Type"),
                  ("LB26", "Aircraft Group"), ("LB34", "Aircraft Type")],
}
MULTI_BOX = ("MB01", "Flight Information", ["Destination City", "Destination Country", "Distance Interval",
                                            "From - To City", "Origin City", "Origin Country"])
# Qlik chart -> (visual type, position, category columns of Main Data, measures, sort measure)
VISUALS = [
    ("CH01", "Traffic per Year", "clusteredColumnChart", (10, 140, 1260, 280), ["Year", "Month"],
     ["# of Flights", "# of Enplanned Passengers", "Transported Freight", "Transported Mail"], None),
    ("CH02", "Top 10 Routes", "tableEx", (10, 430, 1260, 280), ["From - To City"],
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


def lit(v: str) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def slicer(oid: str, title: str, table: str, field: str, pos: tuple, z: int, dropdown: bool) -> dict:
    x, y, w, h = pos
    ref = f"{table}.{field}"
    config = {"name": tag(SLUG, "visual", oid, field), "layouts": [{"id": 0, "position": {
        "x": x, "y": y, "z": z, "width": w, "height": h}}],
        "singleVisual": {"visualType": "slicer", "projections": {"Values": [{"queryRef": ref, "active": True}]},
                         "prototypeQuery": {"Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}],
                                            "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}},
                                                                   "Property": field}, "Name": ref}]},
                         "drillFilterOtherVisuals": True,
                         "objects": {"data": [{"properties": {"mode": lit("'Dropdown'" if dropdown else "'Basic'")}}]},
                         "vcObjects": {"title": [{"properties": {"show": lit("true"),
                                                                 "text": lit("'" + title.replace("'", "''") + "'")}}]}}}
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "config": json.dumps(config), "filters": "[]"}


def field_tables(root: Path) -> dict[str, str]:
    out = {}
    for f in sorted((root / f"{SLUG}.SemanticModel" / "definition" / "tables").glob("*.tmdl")):
        for line in f.read_text().splitlines():
            if line.startswith("\tcolumn "):
                col = line[len("\tcolumn "):].strip()
                col = col[1:-1].replace("''", "'") if col.startswith("'") else col
                out.setdefault(col, f.stem)
    return out


def section(name: str, ordinal: int, containers: list[dict]) -> dict:
    return {"name": f"ReportSection{ordinal}", "displayName": name, "displayOption": 1, "ordinal": ordinal,
            "width": 1280, "height": 720, "config": "{}", "filters": "[]", "visualContainers": containers}


def build(data_root: str = DEFAULT_ROOT) -> Path:
    root = scaffold(APP, data_root)
    tables = field_tables(root)
    main = [slicer(oid, f, tables[f], f, (10 + 254 * (i % 5), 10 + 236 * (i // 5), 244, 226), i, False)
            for i, (oid, f) in enumerate(LIST_BOXES["Main"])]
    mb_id, mb_caption, mb_fields = MULTI_BOX
    top = [(oid, f, f) for oid, f in LIST_BOXES["Dashboard"]] + [(mb_id, f"{mb_caption}: {f}", f) for f in mb_fields]
    dash = [slicer(oid, title, tables[f], f, (10 + 157 * (i % 8), 10 + 62 * (i // 8), 152, 56), i, True)
            for i, (oid, title, f) in enumerate(top)]
    dash += [visual(*v, z=len(dash) + i) for i, v in enumerate(VISUALS)]
    report = root / f"{SLUG}.Report" / "report.json"
    report.write_text(json.dumps({
        "config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
        "layoutOptimization": 0, "resourcePackages": [],
        "sections": [section("Main", 0, main), section("Dashboard", 1, dash)]}, indent=2) + "\n")
    print(f"{report.parent.name}: page Main {len(main)} visuals, page Dashboard {len(dash)} visuals")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
