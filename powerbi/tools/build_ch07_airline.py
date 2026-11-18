"""Generate the Chapter 07 Airline Operations PBIP, derived from the Chapter 15 base model.

Chapter 07's script only does plain loads (Flight Data, the QVD/Access/CSV dimensions), so the tables,
Power Query and %-key relationships come from scaffold_pbip.py. The measures are the Chapter 15 base
measures (build_airline_base.MEASURES) for this chapter's ParityKeys, the Funnel Chart's calculated
dimension is the base's 'Deal Status' column, and the report gets one page per QlikView sheet.

    python powerbi/tools/build_ch07_airline.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_airline_base import CALC_DIMS, DEFAULT_ROOT, MEASURES  # noqa: E402
from scaffold_pbip import APPS, POWERBI, scaffold, show, tag, tname  # noqa: E402

sys.path.insert(0, str(POWERBI / "parity"))
from harness import kpi_list, parity_key  # noqa: E402

APP = "Chapter07__Solution_Chapter 7_Airline Operations"
SLUG = "Chapter07_Airline_Operations"
MD = "Main Data"

# Report pages = QlikView sheets. Sheet object lists and list box captions are decoded from the .qvw document
# block; a list box caption is its field name, and all 22 captions are fields of the model.
FIELD_TABLE = {"Carrier Group": "Carrier Groups", "Airline": "Airlines", "Flight Type": "Flight Types",
               "Aircraft Group": "Aircraft Groups", "Aircraft Type": "Aircraft Types",
               "Distance Interval": "Distance Groups", "Carrier's Operating Region": "Carrier Operating Region",
               "Deal Status": "Flight Types"}
LIST_BOXES = {"LB01": "Destination Country", "LB02": "Destination State", "LB03": "Destination City",
              "LB04": "Origin Country", "LB05": "Origin State", "LB06": "Origin City", "LB07": "Carrier Name",
              "LB09": "Distance Interval", "LB10": "Aircraft Type", "LB11": "Aircraft Group", "LB12": "Flight Type",
              "LB13": "Carrier's Operating Region", "LB15": "Carrier Group", "LB26": "Aircraft Group",
              "LB27": "Flight Type", "LB28": "Carrier's Operating Region", "LB29": "Carrier Group",
              "LB30": "Month", "LB31": "Quarter", "LB32": "Year", "LB33": "Carrier Name", "LB34": "Aircraft Type"}
# LB26-LB34 are linked objects shown on every sheet except Main and Gauge Styles
LINKED = ["LB32", "LB31", "LB30", "LB29", "LB33", "LB27", "LB26", "LB34", "LB28"]
UNMAPPED = {"MB01": "multi box 'Flight Information' (its fields are not decoded from the .qvw)",
            "SB01": "statistics box on Distance (count/sum/avg/min/max of a field; no measure counterpart)",
            "SO01": "search object (Power BI slicers have a search box)",
            "CS01": "current selections (Power BI filter pane)", "BM01": "bookmark object (Power BI bookmarks)",
            "BU01": "button", "BU02": "button", "BU03": "button",
            "TX01": "text object", "TX02": "text object", "TX03": "text object", "TX04": "text object",
            "TX05": "text object"}
# chart id -> (visual type, {role: [field or measure name]}) ; measures are prefixed with '='
CHARTS = {
    "CH01": ("lineChart", {"Category": ["Year", "Month"], "Y": ["=# of Flights", "=# of Enplanned Passengers",
                                                                "=Transported Freight", "=Transported Mail"]}),
    "CH02": ("tableEx", {"Values": ["From - To City", "=# of Flights", "=# of Enplanned Passengers",
                                    "=Transported Freight", "=Transported Mail"]}),
    "CH03": ("lineClusteredColumnComboChart", {"Category": ["Flight Type"], "Y": [
        "=# of Passengers (millions)", "=# of Available Seats (millions)"], "Y2": ["=Load Factor"]}),
    "CH04": ("scatterChart", {"Category": ["Carrier Name"], "X": ["=Transported Mail"],
                              "Y": ["=# of Enplanned Passengers"], "Size": ["=# of Flights"]}),
    "CH05": ("gauge", {"Y": ["=Load Factor"]}),
    "CH06": ("gauge", {"Y": ["=Performed vs Scheduled"]}),
    **{ch: ("gauge", {"Y": ["=Air Time %"]}) for ch in ("CH07", "CH08", "CH09", "CH11", "CH12", "CH13", "CH14")},
    "CH15": ("pieChart", {"Category": ["Carrier Name"], "Y": ["=# of Enplanned Passengers"]}),
    "CH21": ("tableEx", {"Values": ["Airline", "=Load Factor", "=Performed vs Scheduled", "=Air Time % (CH21)"]}),
    "CH22": ("pivotTable", {"Rows": ["Carrier Group", "Airline"], "Columns": ["Year", "Month"],
                            "Values": ["=# of Passengers (millions)", "=Departures Performed (thousands)"]}),
    "CH24": ("lineChart", {"Category": ["Month"], "Y": ["=# of Passengers (millions)"]}),
    "CH25": ("columnChart", {"Category": ["Flight Type"], "Series": ["Year"], "Y": ["=# of Passengers (millions)"]}),
    "CH26": ("pivotTable", {"Rows": ["Year", "Quarter"], "Columns": ["Flight Type"],
                            "Values": ["=# of Passengers (millions)"]}),
    "CH27": ("funnel", {"Category": ["Deal Status"], "Y": ["=# of Passengers (millions)"]}),
    "CH28": ("treemap", {"Group": ["Destination Country"], "Details": ["Destination City"],
                         "Values": ["=# of Passengers (millions)"]}),
    "CH38": ("tableEx", {"Values": ["Aircraft Group", "=Load Factor", "=Performed vs Scheduled",
                                    "=Air Time % (CH21)"]}),
}
PAGES = [("Main", [], ["LB04", "LB01", "LB13", "LB07", "LB02", "LB06", "LB05", "LB03", "LB15", "LB10", "LB12",
                      "LB11", "LB09"]),
         ("Dashboard", ["CH05", "CH06", "CH07", "CH15"], LINKED),
         ("Analysis", ["CH01", "CH02", "CH03", "CH04"], LINKED),  # CH01-CH03 sit in container CT01
         ("Reports", ["CH21", "CH22"], LINKED),
         ("Gauge Styles", ["CH08", "CH09", "CH11", "CH12", "CH13", "CH14"], []),
         ("Other Charts", ["CH24", "CH25", "CH26", "CH27", "CH28"], LINKED),
         ("Other representations", ["CH38"], LINKED)]

GAPS = [
    "Origin/Destination Airports come from the repo's Dimension Tables.mdb (6,209 rows each); the .qvw was reloaded "
    "from an older copy (2,104 / 2,169 rows, inventory/row_count_exceptions.json). Every airport ID Flight Data uses "
    "is in both, so measures are unaffected; airport list boxes show more members.",
    "$$SysTable 12-14 (synthetic keys) are not reproduced; the %-keys are single-column relationships.",
    "Time (drill-down Year > Month) -> Year, Month hierarchy on the axis; Airline_Origin_Destination (cyclic) -> "
    "Airline on the KPIs per Airline table (Origin/Destination Country are columns of Main Data for re-pivoting).",
    "Radar, Mekko, Grid and Block charts have no native visual: line chart, stacked column, matrix and treemap.",
    "List boxes -> slicers on the same sheet, field = list box caption (all 22 map). QlikView selections are "
    "document-wide, so each of the 16 list box fields is a sync-slicer group on every page (hidden where the sheet "
    "has no list box for it): a selection on Main filters every page. Objects with no Power BI "
    "counterpart are listed under unmapped_objects; the container CT01 (CH01-CH03) becomes three visuals on one page.",
    "Chart presentation (Top 10 routes, gauge bands, traffic lights, mini charts) is not reproduced; the full result "
    "sets are, and parity compares them.",
]


def report(sm_tables: set[str]) -> dict:
    def ref(name: str) -> tuple[str, str, bool]:
        if name.startswith("="):
            return MD, name[1:], True
        return FIELD_TABLE.get(name, MD), name, False

    sections = []
    for i, (page, charts, slicers) in enumerate(PAGES):
        visuals = []
        n = len(charts)
        cols = 1 if n == 0 else 2 if len(slicers) > 6 else 1
        rows = max(1, -(-len(slicers) // cols))
        for j, lb in enumerate(slicers):
            sh = min(100, 700 // rows) - 10 if n else 330
            sx, sy = (20 + (j % 7) * 180, 20 + (j // 7) * 350) if not n else (20 + (j % cols) * 150,
                                                                               20 + (j // cols) * (sh + 10))
            visuals.append(("slicer", {"Values": [LIST_BOXES[lb]]}, sx, sy, 170 if not n else 140 * (2 // cols), sh))
        # QlikView selections are global: every list box field is a sync group present on every page,
        # hidden where the sheet has no list box for it
        shown = {LIST_BOXES[lb] for lb in slicers}
        for field in dict.fromkeys(LIST_BOXES.values()):
            if field not in shown:
                visuals.append(("slicer", {"Values": [field]}, 0, 0, 140, 90))
        for j, ch in enumerate(charts):
            vt, roles = CHARTS[ch]
            per_row = 3 if n > 4 else 2 if n > 1 else 1
            w, h = (1280 - 340) // per_row - 20, (700 // ((n + per_row - 1) // per_row)) - 20
            visuals.append((vt, roles, 340 + (j % per_row) * (w + 20), 20 + (j // per_row) * (h + 20), w, h))
        containers = []
        for z, (vt, roles, x, y, w, h) in enumerate(visuals):
            frm, sel, proj = {}, [], {}
            for role, names in roles.items():
                for name in names:
                    table, prop, is_m = ref(name)
                    assert table in sm_tables, table
                    alias = frm.setdefault(table, f"t{len(frm)}")
                    qref = f"{table}.{prop}"
                    if all(s["Name"] != qref for s in sel):
                        sel.append({("Measure" if is_m else "Column"): {
                            "Expression": {"SourceRef": {"Source": alias}}, "Property": prop}, "Name": qref})
                    proj.setdefault(role, []).append({"queryRef": qref})
            name = tag(SLUG, "visual", page, str(z))
            pos = {"x": x, "y": y, "z": z, "width": w, "height": h}
            single = {"visualType": vt, "projections": proj, "prototypeQuery": {
                "Version": 2, "From": [{"Name": a, "Entity": t, "Type": 0} for t, a in frm.items()],
                "Select": sel}, "drillFilterOtherVisuals": True}
            if vt == "slicer":
                field = roles["Values"][0]
                single["syncGroup"] = {"groupName": field, "fieldChanges": True, "filterChanges": True}
                if field not in shown:
                    single["display"] = {"mode": "hidden"}
            containers.append({**pos, "config": json.dumps({
                "name": name, "layouts": [{"id": 0, "position": pos}], "singleVisual": single}), "filters": "[]"})
        sections.append({"name": f"ReportSection{i}", "displayName": page, "displayOption": 1, "ordinal": i,
                         "width": 1280, "height": 720, "config": "{}", "filters": "[]",
                         "visualContainers": containers})
    return {"config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
            "layoutOptimization": 0, "resourcePackages": [], "sections": sections}


def build(data_root: str = DEFAULT_ROOT) -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = scaffold(APP, data_root)
    (root / "scaffold.json").unlink()
    tables = root / f"{SLUG}.SemanticModel" / "definition" / "tables"
    measures: dict[str, dict] = {}
    for k in kpi_list(manifest):
        pk = k["parity_key"]
        if pk not in MEASURES:
            raise SystemExit(f"{k['kpi']}: no base measure for ParityKey {pk}: {k['expression']}")
        name, dax, fmt = MEASURES[pk]
        mz = measures.setdefault(pk, {"parity_key": pk, "name": name, "dax": dax, "fmt": fmt, "kpis": [],
                                      "qlik": " ".join(k["expression"].split())})
        mz["kpis"].append(k["kpi"])
    calc = [x for x in CALC_DIMS if x[2] in {d for k in kpi_list(manifest) for d in k["dims"] if d.startswith("=")}]

    md = tables / f"{MD}.tmdl"
    text = md.read_text(encoding="utf-8")
    head, cols = text.split("\n\tcolumn ", 1)
    head = head.split("\n\tmeasure ", 1)[0].rstrip("\n")
    block = []
    for mz in measures.values():
        block.append(f"\tmeasure {tname(mz['name'])} = {mz['dax']}")
        if mz["fmt"]:
            block.append(f"\t\tformatString: {mz['fmt']}")
        block += [f"\t\tlineageTag: {tag(SLUG, MD, 'm', mz['parity_key'])}", "",
                  f"\t\tannotation ParityKey = {mz['parity_key']}", f"\t\tannotation QlikExpression = {mz['qlik']}",
                  f"\t\tannotation QlikObjects = {', '.join(mz['kpis'])}", ""]
    md.write_text(head + "\n\n" + "\n".join(block) + "\n\tcolumn " + cols, encoding="utf-8")

    for table, col, qlik, dax, typ in calc:
        p = tables / f"{re.sub(r'[<>:\"/\\\\|?*]', '_', table)}.tmdl"
        body, part = p.read_text(encoding="utf-8").split(f"\tpartition {tname(table)} = m", 1)
        extra = [f"\tcolumn {tname(col)} = {dax}", f"\t\tdataType: {typ}",
                 f"\t\tlineageTag: {tag(SLUG, table, 'c', col)}", "\t\tsummarizeBy: none", "",
                 f"\t\tannotation ParityKey = {parity_key(qlik)}",
                 f"\t\tannotation QlikDimension = {' '.join(qlik.split())}", "", ""]
        p.write_text(body + "\n".join(extra) + f"\tpartition {tname(table)} = m" + part, encoding="utf-8")

    sm_tables = {t["name"] for t in manifest["data_model"]["tables"] if not t["name"].startswith("$$")}
    (root / f"{SLUG}.Report" / "report.json").write_text(json.dumps(report(sm_tables), indent=2) + "\n")
    (root / "model.json").write_text(json.dumps(
        {"app": APP, "generated_by": "powerbi/tools/build_ch07_airline.py",
         "base": "powerbi/tools/build_airline_base.py (Chapter 15)",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in measures.values()],
         "calculated_dimensions": [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q, "dax": d}
                                   for t, col, q, d, _ in calc],
         "pages": [{"page": p, "charts": c, "slicers": {lb: LIST_BOXES[lb] for lb in s}} for p, c, s in PAGES],
         "unmapped_objects": UNMAPPED,
         "semantic_gaps": GAPS}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(measures)} measures from the Chapter 15 base, {len(calc)} calculated columns, "
          f"{len(PAGES)} report pages")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
