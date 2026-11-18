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

# Report pages = QlikView sheets. The .qvw stores object ids in sheet order (each sheet id followed by its objects;
# the container's charts precede the first sheet); list boxes, buttons and text objects carry no decoded field, so
# their slicers use this chapter's dimension fields.
SLICERS = [("Main Data", "Year"), ("Main Data", "Quarter"), ("Main Data", "Month"), ("Carrier Groups", "Carrier Group"),
           ("Airlines", "Airline"), ("Main Data", "Carrier Name"), ("Flight Types", "Flight Type"),
           ("Aircraft Groups", "Aircraft Group"), ("Aircraft Types", "Aircraft Type"),
           ("Distance Groups", "Distance Interval"), ("Main Data", "Origin Country"),
           ("Main Data", "Destination Country"), ("Carrier Operating Region", "Carrier's Operating Region")]
F = {f: t for t, f in SLICERS} | {"From - To City": MD, "Destination City": MD, "Deal Status": "Flight Types"}
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
PAGES = [("Main", [], [f for _, f in SLICERS]),
         ("Dashboard", ["CH05", "CH06", "CH07"], ["Year", "Month", "Carrier Group", "Flight Type"]),
         ("Analysis", ["CH01", "CH02", "CH03", "CH15", "CH04"], ["Year", "Carrier Name"]),
         ("Reports", ["CH21", "CH22"], ["Year", "Carrier Group"]),
         ("Gauge Styles", ["CH08", "CH09", "CH11", "CH12", "CH13", "CH14"], ["Year"]),
         ("Other Charts", ["CH24", "CH25", "CH26", "CH27", "CH28"], ["Year"]),
         ("Other representations", ["CH38"], ["Year"])]

GAPS = [
    "Origin/Destination Airports come from the repo's Dimension Tables.mdb (6,209 rows each); the .qvw was reloaded "
    "from an older copy (2,104 / 2,169 rows, inventory/row_count_exceptions.json). Every airport ID Flight Data uses "
    "is in both, so measures are unaffected; airport list boxes show more members.",
    "$$SysTable 12-14 (synthetic keys) are not reproduced; the %-keys are single-column relationships.",
    "Time (drill-down Year > Month) -> Year, Month hierarchy on the axis; Airline_Origin_Destination (cyclic) -> "
    "Airline on the KPIs per Airline table (Origin/Destination Country are columns of Main Data for re-pivoting).",
    "Radar, Mekko, Grid and Block charts have no native visual: line chart, stacked column, matrix and treemap.",
    "Text objects, buttons, the bookmark object, current selections, search object, multi box and statistics box "
    "have no Power BI equivalent: slicers, the filter pane and bookmarks replace them. List box fields are not "
    "decoded from the .qvw, so page slicers use this chapter's dimension fields.",
    "Chart presentation (Top 10 routes, gauge bands, traffic lights, mini charts) is not reproduced; the full result "
    "sets are, and parity compares them.",
]


def report(sm_tables: set[str]) -> dict:
    def ref(name: str) -> tuple[str, str, bool]:
        if name.startswith("="):
            return MD, name[1:], True
        return F.get(name, MD), name, False

    sections = []
    for i, (page, charts, slicers) in enumerate(PAGES):
        visuals = []
        for j, field in enumerate(slicers):
            cols = 2 if len(slicers) > 6 else 1
            visuals.append(("slicer", {"Values": [field]}, 20 + (j % cols) * 150, 20 + (j // cols) * 100,
                            140 * (2 // cols), 90))
        n = len(charts)
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
            containers.append({**pos, "config": json.dumps({
                "name": name, "layouts": [{"id": 0, "position": pos}],
                "singleVisual": {"visualType": vt, "projections": proj, "prototypeQuery": {
                    "Version": 2, "From": [{"Name": a, "Entity": t, "Type": 0} for t, a in frm.items()],
                    "Select": sel}, "drillFilterOtherVisuals": True}}), "filters": "[]"})
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
         "pages": [{"page": p, "charts": c, "slicers": s} for p, c, s in PAGES],
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
