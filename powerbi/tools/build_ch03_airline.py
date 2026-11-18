"""Build the Chapter 3 Airline Operations PBIP: the Chapter 15 base model cut down to what Chapter 3 loads and shows.

  python powerbi/tools/build_ch03_airline.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]

Chapter 3's script is plain QVD loads: [Main Data] (Flight Data.qvd) and seven dimension tables, associated on their
% key fields. Unlike Chapter 15 there is no calendar, Exists() filtering, Section Access or calculated dimension, so
every table reads its converted Parquet file as is. The report rebuilds both sheets: Main (13 list boxes) and
Dashboard (7 list boxes, the search object, "Traffic per Year" over the Year > Month drill-down group, and
"Top 10 Routes").
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_airline_base import DEFAULT_ROOT, MEASURES, catalog_types, m_let, m_list, m_types  # noqa: E402
from scaffold_pbip import APPS, POWERBI, TYPE_MAP, show, tag, tname  # noqa: E402

sys.path.insert(0, str(POWERBI / "parity"))
from harness import kpi_list  # noqa: E402

APP = "Chapter03__Solution_Chapter 3_Airline Operations"
SLUG = "Chapter03_Airline_Operations"
QVDS = "Data Files/QVDs"
MD = "Main Data"

MAIN_COLS = [
    "%Airline ID", "%Carrier Group ID", "%Unique Carrier Code", "%Unique Carrier Entity Code", "%Region Code",
    "%Origin Airport ID", "%Origin Airport Sequence ID", "%Origin Airport Market ID", "%Origin World Area Code",
    "%Destination Airport ID", "%Destination Airport Sequence ID", "%Destination Airport Market ID",
    "%Destination World Area Code", "%Aircraft Group ID", "%Aircraft Type ID", "%Aircraft Configuration ID",
    "%Distance Group ID", "%Service Class ID", "%Datasource ID", "# Departures Scheduled", "# Departures Performed",
    "# Payload", "Distance", "# Available Seats", "# Transported Passengers", "# Transported Freight",
    "# Transported Mail", "# Ramp-To-Ramp Time", "# Air Time", "Unique Carrier", "Carrier Code", "Carrier Name",
    "Origin Airport Code", "Origin City", "Origin State Code", "Origin State FIPS", "Origin State",
    "Origin Country Code", "Origin Country", "Destination Airport Code", "Destination City",
    "Destination State Code", "Destination State FIPS", "Destination State", "Destination Country Code",
    "Destination Country", "Year", "Period", "Quarter", "Month (#)", "Month", "Month__num",
    "From - To Airport Code", "From - To Airport ID", "From - To City", "From - To State Code", "From - To State"]

# (table, QVD, key, label) in script order; Qlik associates each on its % key field with [Main Data].
DIMENSIONS = [
    ("Carrier Groups", "Carrier Groups", "%Carrier Group ID", "Carrier Group"),
    ("Airlines", "Airlines", "%Airline ID", "Airline"),
    ("Carrier Operating Region", "Carrier Operating Region", "%Region Code", "Carrier's Operating Region"),
    ("Flight Types", "Flight Types", "%Datasource ID", "Flight Type"),
    ("Aircraft Groups", "Aircraft Groups", "%Aircraft Group ID", "Aircraft Group"),
    ("Aircraft Types", "Aircraft Types", "%Aircraft Type ID", "Aircraft Type"),
    ("Distance Groups", "Distance Groups", "%Distance Group ID", "Distance Interval"),
]

# Qlik drill-down group "Time" (CH01's dimension) -> Power BI hierarchy on [Main Data].
HIERARCHY = ("Time", ["Year", "Month"])

# Sheet list boxes, (object id, field) in layout order.
SHEET_MAIN = [("LB01", "Destination Country"), ("LB02", "Destination State"), ("LB03", "Destination City"),
              ("LB04", "Origin Country"), ("LB05", "Origin State"), ("LB06", "Origin City"),
              ("LB07", "Carrier Name"), ("LB15", "Carrier Group"), ("LB13", "Carrier's Operating Region"),
              ("LB12", "Flight Type"), ("LB11", "Aircraft Group"), ("LB10", "Aircraft Type"),
              ("LB09", "Distance Interval")]
SHEET_DASHBOARD = [("LB32", "Year"), ("LB31", "Quarter"), ("LB30", "Month"), ("LB29", "Carrier Group"),
                   ("LB28", "Carrier's Operating Region"), ("LB27", "Flight Type"), ("LB26", "Aircraft Group")]

GAPS = [
    "QlikView's synthetic $$SysTable tables are engine metadata, not data: not reproduced.",
    "SO01 search object (cross-field search over all fields): Power BI has no cross-field search box; each Dashboard "
    "slicer is search-enabled instead, and the search is a slicer on 'From - To City'.",
    "QlikView list boxes show excluded values greyed; Power BI slicers hide or dim them depending on the visual's "
    "'Show items with no data' setting.",
]


def field_table(field: str) -> str:
    return next((t for t, _, _, label in DIMENSIONS if label == field), MD)


def table_specs(types: dict) -> dict[str, dict]:
    flight = f"{QVDS}/Flight Data.parquet"
    cols = [(c, types[flight][c]) for c in MAIN_COLS]
    specs = {MD: {"cols": cols, "m": m_let([
        f'Source = fnReadParquet("{flight}")',
        f"Selected = Table.SelectColumns(Source, {m_list(MAIN_COLS)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(cols)})"], "Typed")}}
    for name, qvd, key, label in DIMENSIONS:
        path = f"{QVDS}/{qvd}.parquet"
        dcols = [(key, types[path][key]), (label, types[path][label])]
        specs[name] = {"cols": dcols, "m": m_let([
            f'Source = fnReadParquet("{path}")',
            f"Selected = Table.SelectColumns(Source, {m_list([key, label])})",
            f"Typed = Table.TransformColumnTypes(Selected, {m_types(dcols)})"], "Typed")}
    return specs


def write_table(path: Path, name: str, spec: dict, measures: list[dict]):
    names = {n for n, _ in spec["cols"]}
    lines = [f"table {tname(name)}", f"\tlineageTag: {tag(SLUG, name)}", ""]
    for mz in measures:
        lines += [f"\tmeasure {tname(mz['name'])} = {mz['dax']}", f"\t\tformatString: {mz['fmt']}",
                  f"\t\tlineageTag: {tag(SLUG, name, 'm', mz['parity_key'])}", "",
                  f"\t\tannotation ParityKey = {mz['parity_key']}", f"\t\tannotation QlikExpression = {mz['qlik']}",
                  f"\t\tannotation QlikObjects = {', '.join(mz['kpis'])}", ""]
    for col, typ in spec["cols"]:
        dtype, _, fmt = TYPE_MAP[typ]
        lines += [f"\tcolumn {tname(col)}", f"\t\tdataType: {dtype}"]
        if col.startswith("%") or col.endswith("__num"):
            lines.append("\t\tisHidden")
        if f"{col}__num" in names:
            lines.append(f"\t\tsortByColumn: {tname(col + '__num')}")
        if fmt and col not in ("Period", "Year"):
            lines.append(f"\t\tformatString: {fmt}")
        lines += [f"\t\tlineageTag: {tag(SLUG, name, 'c', col)}",
                  f"\t\tsummarizeBy: {'sum' if col.startswith('#') else 'none'}", f"\t\tsourceColumn: {col}", "",
                  "\t\tannotation SummarizationSetBy = Automatic", ""]
    if name == MD:
        hname, levels = HIERARCHY
        lines += [f"\thierarchy {tname(hname)}", f"\t\tlineageTag: {tag(SLUG, name, 'h', hname)}", ""]
        for lvl in levels:
            lines += [f"\t\tlevel {tname(lvl)}", f"\t\t\tlineageTag: {tag(SLUG, name, 'h', hname, lvl)}",
                      f"\t\t\tcolumn: {tname(lvl)}", ""]
        lines += [f"\t\tannotation QlikGroup = drill-down {hname}: {' > '.join(levels)}", ""]
    lines += [f"\tpartition {tname(name)} = m", "\t\tmode: import", "\t\tsource =", spec["m"], ""]
    (path / f"{name}.tmdl").write_text("\n".join(lines), encoding="utf-8")


# --- report (PBIR-legacy report.json) -------------------------------------------------------------------------------

def _src(alias: str) -> dict:
    return {"SourceRef": {"Source": alias}}


def _alias(table: str) -> str:
    return "m" if table == MD else "d" + str([t for t, *_ in DIMENSIONS].index(table))


def _query(selects: list[dict], tables: list[str], order: list[dict] | None = None) -> dict:
    q = {"Version": 2, "From": [{"Name": _alias(t), "Entity": t, "Type": 0} for t in dict.fromkeys(tables)],
         "Select": selects}
    if order:
        q["OrderBy"] = order
    return q


def _col(field: str) -> tuple[dict, str, str]:
    table = field_table(field)
    return ({"Column": {"Expression": _src(_alias(table)), "Property": field}, "Name": f"{table}.{field}"},
            f"{table}.{field}", table)


def _measure(name: str) -> tuple[dict, str]:
    return {"Measure": {"Expression": _src("m"), "Property": name}, "Name": f"{MD}.{name}"}, f"{MD}.{name}"


def _container(vid: str, x: int, y: int, w: int, h: int, z: int, visual: dict, filters: list | None = None) -> dict:
    cfg = {"name": vid, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
           "singleVisual": visual}
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "config": json.dumps(cfg),
            "filters": json.dumps(filters or [])}


def _title(text: str) -> dict:
    return {"title": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                                      "text": {"expr": {"Literal": {"Value": json.dumps(text).replace('"', "'")}}}}}]}


def _slicer(oid: str, field: str, x: int, y: int, w: int, h: int, z: int) -> dict:
    sel, ref, table = _col(field)
    visual = {"visualType": "slicer", "projections": {"Values": [{"queryRef": ref, "active": True}]},
              "prototypeQuery": _query([sel], [table]),
              "objects": {"data": [{"properties": {"mode": {"expr": {"Literal": {"Value": "'Basic'"}}}}}],
                          "general": [{"properties": {"selfFilterEnabled": {"expr": {"Literal": {"Value": "true"}}}}}]},
              "vcObjects": _title(field)}
    return _container(f"{SLUG}_{oid}", x, y, w, h, z, visual)


def _measure_refs(measures: list[dict]):
    return [_measure(mz["name"]) for mz in measures]


def traffic_per_year(measures: list[dict], x, y, w, h, z) -> dict:
    hname, levels = HIERARCHY
    sels = [{"HierarchyLevel": {"Expression": {"Hierarchy": {"Expression": _src("m"), "Hierarchy": hname}},
                                "Level": lvl}, "Name": f"{MD}.{hname}.{lvl}"} for lvl in levels]
    ms = _measure_refs(measures)
    visual = {"visualType": "clusteredColumnChart",
              "projections": {"Category": [{"queryRef": s["Name"], "active": i == 0} for i, s in enumerate(sels)],
                              "Y": [{"queryRef": r} for _, r in ms]},
              "prototypeQuery": _query(sels + [s for s, _ in ms], [MD]),
              "drillFilterOtherVisuals": True, "vcObjects": _title("Traffic per Year")}
    return _container(f"{SLUG}_CH01", x, y, w, h, z, visual)


def top_routes(measures: list[dict], x, y, w, h, z) -> dict:
    sel, ref, _ = _col("From - To City")
    ms = _measure_refs(measures)
    flights = {"Measure": {"Expression": _src("m"), "Property": measures[0]["name"]}}
    visual = {"visualType": "tableEx",
              "projections": {"Values": [{"queryRef": ref}] + [{"queryRef": r} for _, r in ms]},
              "prototypeQuery": _query([sel] + [s for s, _ in ms], [MD], [{"Direction": 2, "Expression": flights}]),
              "vcObjects": _title("Top 10 Routes")}
    col = {"Column": {"Expression": _src("m"), "Property": "From - To City"}}
    top_n = {"name": "Top10Routes", "type": "TopN", "howCreated": 1,
             "expression": {"Column": {"Expression": {"SourceRef": {"Entity": MD}}, "Property": "From - To City"}},
             "filter": {"Version": 2, "From": [
                 {"Name": "subquery", "Type": 2, "Expression": {"Subquery": {"Query": {
                     "Version": 2, "From": [{"Name": "m", "Entity": MD, "Type": 0}],
                     "Select": [{**col, "Name": "field"}],
                     "OrderBy": [{"Direction": 2, "Expression": flights}], "Top": 10}}}},
                 {"Name": "m", "Entity": MD, "Type": 0}],
                 "Where": [{"Condition": {"In": {"Expressions": [col], "Table": {"SourceRef": {"Source": "subquery"}}}}}]}}
    return _container(f"{SLUG}_CH02", x, y, w, h, z, visual, [top_n])


def sections(measures: list[dict]) -> list[dict]:
    main = [_slicer(oid, f, 20 + (i % 5) * 248, 20 + (i // 5) * 230, 236, 218, i)
            for i, (oid, f) in enumerate(SHEET_MAIN)]
    dash = [_slicer(oid, f, 20, 20 + i * 96, 220, 88, i) for i, (oid, f) in enumerate(SHEET_DASHBOARD)]
    dash.append(_slicer("SO01", "From - To City", 260, 20, 1000, 60, len(dash)))
    dash.append(traffic_per_year(measures, 260, 96, 1000, 300, len(dash)))
    dash.append(top_routes(measures, 260, 412, 1000, 300, len(dash)))
    return [{"name": f"{SLUG}_{sid}", "displayName": label, "displayOption": 1, "ordinal": i, "width": 1280,
             "height": 720 if sid == "SH01" else 760, "config": "{}", "filters": "[]", "visualContainers": vcs}
            for i, (sid, label, vcs) in enumerate([("SH01", "Main", main), ("SH02", "Dashboard", dash)])]


def build(data_root: str = DEFAULT_ROOT) -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = APPS / SLUG
    sm, rp = root / f"{SLUG}.SemanticModel", root / f"{SLUG}.Report"
    (sm / "definition" / "tables").mkdir(parents=True, exist_ok=True)
    rp.mkdir(parents=True, exist_ok=True)
    for f in (sm / "definition" / "tables").glob("*.tmdl"):
        f.unlink()
    (root / "scaffold.json").unlink(missing_ok=True)
    measures: dict[str, dict] = {}
    for k in kpi_list(manifest):
        pk = k["parity_key"]
        if pk not in MEASURES:
            raise SystemExit(f"{k['kpi']}: no measure for ParityKey {pk}: {k['expression']}")
        name, dax, fmt = MEASURES[pk]
        mz = measures.setdefault(pk, {"parity_key": pk, "name": name, "dax": dax, "fmt": fmt, "kpis": [],
                                      "qlik": " ".join(k["expression"].split())})
        mz["kpis"].append(k["kpi"])
        for d in k["dims"]:
            if d != HIERARCHY[0] and d not in MAIN_COLS:
                raise SystemExit(f"{k['kpi']}: dimension {d!r} is not a [Main Data] field")
    specs = table_specs(catalog_types())
    for name, spec in specs.items():
        write_table(sm / "definition" / "tables", name, spec, list(measures.values()) if name == MD else [])
    rels = []
    for name, _, key, _ in DIMENSIONS:
        rels += [f"relationship {tag(SLUG, 'rel', MD, key, name)}", f"\tfromColumn: {tname(MD)}.{tname(key)}",
                 f"\ttoColumn: {tname(name)}.{tname(key)}", ""]
    (sm / "definition" / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")
    (sm / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n", encoding="utf-8")
    refs = "\n".join(f"ref table {tname(t)}" for t in specs)
    order = ["DataRoot", "fnReadParquet", *specs]
    (sm / "definition" / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        f"\tannotation PBI_QueryOrder = {json.dumps(order)}\n\n{refs}\n", encoding="utf-8")
    (sm / "definition" / "expressions.tmdl").write_text(
        f'expression DataRoot = "{data_root}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f"\tlineageTag: {tag(SLUG, 'DataRoot')}\n\n"
        "expression fnReadParquet =\n"
        "\t\t(relativePath as text) as table =>\n"
        "\t\tlet\n"
        '\t\t    FullPath = DataRoot & Text.Replace(relativePath, "/", "\\"),\n'
        "\t\t    Source = Parquet.Document(File.Contents(FullPath))\n"
        "\t\tin\n"
        "\t\t    Source\n"
        f"\tlineageTag: {tag(SLUG, 'fnReadParquet')}\n", encoding="utf-8")
    (sm / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2) + "\n")
    (rp / "definition.pbir").write_text(json.dumps(
        {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{SLUG}.SemanticModel"}}}, indent=2) + "\n")
    pages = sections(list(measures.values()))
    (rp / "report.json").write_text(json.dumps({
        "config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 1}),
        "layoutOptimization": 0, "resourcePackages": [], "sections": pages}, indent=2) + "\n")
    (root / f"{SLUG}.pbip").write_text(json.dumps(
        {"version": "1.0", "artifacts": [{"report": {"path": f"{SLUG}.Report"}}], "settings": {"enableAutoRecovery": True}},
        indent=2) + "\n")
    (root / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    (root / "model.json").write_text(json.dumps(
        {"app": APP, "generated_by": "powerbi/tools/build_ch03_airline.py", "base": "powerbi/tools/build_airline_base.py",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in measures.values()],
         "hierarchies": {HIERARCHY[0]: {"table": MD, "levels": HIERARCHY[1]}},
         "pages": {p["displayName"]: [json.loads(v["config"])["name"].split("_")[-1] for v in p["visualContainers"]]
                   for p in pages},
         "semantic_gaps": GAPS}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(specs)} tables, {len(DIMENSIONS)} relationships, {len(measures)} measures, "
          f"{sum(len(p['visualContainers']) for p in pages)} visuals on {len(pages)} pages")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
