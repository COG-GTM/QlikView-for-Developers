"""Build PBIP report pages for a scaffolded plain-load app from its sheet layout.

Each page is a list of visuals; charts take their Qlik caption, dimensions and expressions
from the manifest and their measures from the PBIP's `ParityKey` annotations, so the report
only shows measures that the parity harness checks.
"""
import argparse
import json
import re
import sys
from pathlib import Path

POWERBI = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(POWERBI / "parity")]
from harness import parity_key  # noqa: E402

PAGE_W, PAGE_H = 1280, 720

# Sheet layouts per app: list boxes (Qlik id, caption = field) become slicers, charts by Qlik id.
# Captions are read from the .qvw document block, where each object's caption precedes its id.
LAYOUTS = {
    "Chapter04__Solution_Chapter 4_Airline Operations": [
        {"name": "Main", "id": "SH01", "charts": [], "list_boxes": [
            ("LB09", "Distance Interval"), ("LB11", "Aircraft Group"), ("LB12", "Flight Type"),
            ("LB10", "Aircraft Type"), ("LB15", "Carrier Group"), ("LB03", "Destination City"),
            ("LB05", "Origin State"), ("LB06", "Origin City"), ("LB02", "Destination State"),
            ("LB07", "Carrier Name"), ("LB13", "Carrier's Operating Region"),
            ("LB01", "Destination Country"), ("LB04", "Origin Country")]},
        {"name": "Dashboard", "id": "SH02", "charts": ["CH01", "CH02"], "list_boxes": [
            ("LB32", "Year"), ("LB31", "Quarter"), ("LB30", "Month"), ("LB29", "Carrier Group"),
            ("LB28", "Carrier's Operating Region"), ("LB26", "Aircraft Group"), ("LB27", "Flight Type")],
         # SO01 (search object) has no Power BI equivalent; slicers have built-in search.
         "gaps": ["SO01"]},
    ],
}
# Qlik dimension -> model columns (a Qlik drill group becomes a drillable axis).
DIMENSIONS = {"Time": [("Main Data", "Year"), ("Main Data", "Month")]}
VISUAL_TYPES = {"Bar Chart": "clusteredColumnChart", "Straight Table": "tableEx"}
TOP_N = re.compile(r"\bTop (\d+)\b")


def measures(pbip: Path) -> dict[str, tuple[str, str]]:
    """ParityKey -> (table, measure) from the TMDL."""
    out = {}
    for f in sorted((pbip.parent / f"{pbip.name}.SemanticModel" / "definition" / "tables").glob("*.tmdl")):
        table, name = None, None
        for line in f.read_text().splitlines():
            if line.startswith("table "):
                table = line[6:].strip().strip("'").replace("''", "'")
            elif m := re.match(r"\tmeasure ('(?:[^']|'')+'|\S+)", line):
                name = m.group(1).strip("'").replace("''", "'")
            elif name and (m := re.match(r"\t\tannotation ParityKey = (\w+)", line)):
                out[m.group(1)] = (table, name)
    return out


def columns(pbip: Path) -> dict[str, str]:
    """Visible column name -> table, from the TMDL."""
    out = {}
    for f in sorted((pbip.parent / f"{pbip.name}.SemanticModel" / "definition" / "tables").glob("*.tmdl")):
        table = None
        for line in f.read_text().splitlines():
            if line.startswith("table "):
                table = line[6:].strip().strip("'").replace("''", "'")
            elif m := re.match(r"\tcolumn ('(?:[^']|'')+'|\S+)", line):
                name = m.group(1).strip("'").replace("''", "'")
                if not name.startswith("%"):
                    out.setdefault(name, table)
    return out


def slicers(spec: dict, cols: dict) -> list[tuple[str, str, str]]:
    """(object id, table, field) per list box; fails on a caption that is not a model field."""
    missing = [cap for _, cap in spec["list_boxes"] if cap not in cols]
    if missing:
        raise SystemExit(f"{spec['name']}: list boxes {missing} match no model field")
    return [(oid, cols[cap], cap) for oid, cap in spec["list_boxes"]]


def lit(s: str) -> dict:
    return {"expr": {"Literal": {"Value": "'" + s.replace("'", "''") + "'"}}}


def field(kind: str, alias: str, prop: str) -> dict:
    return {kind: {"Expression": {"SourceRef": {"Source": alias}}, "Property": prop}}


def visual(name: str, vtype: str, pos: tuple, columns: list, meas: list, title: str | None,
           role_cols: str, role_meas: str | None, order_by: tuple | None = None, filters: list | None = None) -> dict:
    x, y, w, h = pos
    tables = list(dict.fromkeys([t for t, _ in columns] + [t for t, _ in meas]))
    alias = {t: f"t{i}" for i, t in enumerate(tables)}
    select = [{**field("Column", alias[t], c), "Name": f"{t}.{c}"} for t, c in columns]
    select += [{**field("Measure", alias[t], m), "Name": f"{t}.{m}"} for t, m in meas]
    proj = {role_cols: [{"queryRef": f"{t}.{c}", "active": True} for t, c in columns]}
    if role_meas:
        proj.setdefault(role_meas, []).extend({"queryRef": f"{t}.{m}"} for t, m in meas)
    query = {"Version": 2, "From": [{"Name": a, "Entity": t, "Type": 0} for t, a in alias.items()], "Select": select}
    if order_by:
        t, m = order_by
        query["OrderBy"] = [{"Direction": 2, "Expression": field("Measure", alias[t], m)}]
    single = {"visualType": vtype, "projections": proj, "prototypeQuery": query, "drillFilterOtherVisuals": True}
    if title:
        single["vcObjects"] = {"title": [{"properties": {"show": lit_bool(True), "text": lit(title)}}]}
    config = {"name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": 0, "width": w, "height": h}}],
              "singleVisual": single}
    return {"x": x, "y": y, "z": 0, "width": w, "height": h, "config": json.dumps(config),
            "filters": json.dumps(filters or [])}


def lit_bool(v: bool) -> dict:
    return {"expr": {"Literal": {"Value": "true" if v else "false"}}}


def top_n_filter(column: tuple, by: tuple, n: int) -> dict:
    """Visual-level Top N filter: keep the n `column` values with the highest `by` measure."""
    (ct, cc), (mt, mm) = column, by
    sub = {"Version": 2, "From": [{"Name": "m", "Entity": mt, "Type": 0}] + ([] if ct == mt else [{"Name": "c", "Entity": ct, "Type": 0}]),
           "Select": [{**field("Column", "m" if ct == mt else "c", cc), "Name": "field"}],
           "OrderBy": [{"Direction": 2, "Expression": field("Measure", "m", mm)}], "Top": n}
    return {"name": f"TopN_{cc}", "type": "TopN", "howCreated": 1,
            "expression": {"Column": {"Expression": {"SourceRef": {"Entity": ct}}, "Property": cc}},
            "filter": {"Version": 2,
                       "From": [{"Name": "subquery", "Expression": {"Subquery": {"Query": sub}}, "Type": 2},
                                {"Name": "d", "Entity": ct, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [field("Column", "d", cc)],
                                                       "Table": {"SourceRef": {"Source": "subquery"}}}}}]}}


def chart_visual(chart: dict, by_key: dict, pos: tuple) -> dict:
    cols = [c for d in chart["dimensions"] for c in DIMENSIONS.get(d, [("Main Data", d)])]
    meas = [by_key[parity_key(e["expression"])] for e in chart["expressions"]]
    vtype = VISUAL_TYPES[chart["type"]]
    filters, order = [], None
    if m := TOP_N.search(chart["caption"]):
        filters = [top_n_filter(cols[0], meas[0], int(m.group(1)))]
        order = meas[0]
    if vtype == "tableEx":
        return visual(chart["id"], vtype, pos, cols, meas, chart["caption"], "Values", "Values", order, filters)
    return visual(chart["id"], vtype, pos, cols, meas, chart["caption"], "Category", "Y", order, filters)


def page(i: int, spec: dict, charts: dict, by_key: dict, cols: dict) -> dict:
    visuals = []
    boxes = slicers(spec, cols)
    n = len(boxes)
    if spec["charts"]:
        sw, sh = 220, (PAGE_H - 20 - 10 * (n - 1)) // n
        for j, (oid, t, c) in enumerate(boxes):
            visuals.append(visual(oid, "slicer", (10, 10 + j * (sh + 10), sw, sh), [(t, c)], [], None, "Values", None))
        cw = PAGE_W - sw - 30
        ch = (PAGE_H - 30) // len(spec["charts"])
        for j, cid in enumerate(spec["charts"]):
            visuals.append(chart_visual(charts[cid], by_key, (sw + 20, 10 + j * (ch + 10), cw, ch)))
    else:
        per_row = 5
        w, h = (PAGE_W - 10 * (per_row + 1)) // per_row, (PAGE_H - 40) // 3
        for j, (oid, t, c) in enumerate(boxes):
            r, k = divmod(j, per_row)
            visuals.append(visual(oid, "slicer", (10 + k * (w + 10), 10 + r * (h + 10), w, h), [(t, c)], [], None, "Values", None))
    return {"name": spec["id"], "displayName": spec["name"], "displayOption": 1, "ordinal": i, "width": PAGE_W,
            "height": PAGE_H, "config": "{}", "filters": "[]", "visualContainers": visuals}


def build(app: str, pbip_dir: Path) -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{app}.json").read_text())
    charts = {c["id"]: c for c in manifest["charts"]}
    by_key = measures(pbip_dir / pbip_dir.name)
    cols = columns(pbip_dir / pbip_dir.name)
    report = {"config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
              "layoutOptimization": 0, "resourcePackages": [],
              "sections": [page(i, s, charts, by_key, cols) for i, s in enumerate(LAYOUTS[app])]}
    out = pbip_dir / f"{pbip_dir.name}.Report" / "report.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", required=True)
    ap.add_argument("--pbip", required=True, type=Path, help="powerbi/apps/<Slug>")
    a = ap.parse_args(argv)
    out = build(a.app, a.pbip.resolve())
    print(f"{a.app}: {len(LAYOUTS[a.app])} pages -> {out.relative_to(POWERBI.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
