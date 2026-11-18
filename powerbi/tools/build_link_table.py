"""Generate the PBIP for Chapter09/Solution_Chapter 9_Link table.qvw (derived from build_airline_base.py).

The Chapter 9 script keeps [Main Data] (flights) and [Employment Statistics] apart and associates them through a
[Link Table] on a composite [%Key Field] (Period | Airline | Unique Carrier | Carrier Group). The script moves the
calendar and carrier fields of both facts into the link table, so the facts relate to it, and to Airlines /
Carrier Groups, only through that key. The link table is not unique on the key (five Antonov keys carry two Carrier
Codes), so both fact relationships are many-to-many with the link table filtering the facts.

    python powerbi/tools/build_link_table.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_airline_base as base  # noqa: E402
from build_airline_base import CALC_DIMS, DEFAULT_ROOT, catalog_types, m_let, m_list, m_types  # noqa: E402
from scaffold_pbip import APPS, POWERBI, TYPE_MAP, dcol, show, tag, tname  # noqa: E402

sys.path.insert(0, str(POWERBI / "parity"))
from harness import kpi_list, parity_key  # noqa: E402

APP = "Chapter09__Solution_Chapter 9_Link table"
SLUG = "Chapter09_Link_table"
QVDS = "Data Files/QVDs/"
FLIGHT = QVDS + "Flight Data.parquet"
EMPLOYMENT = QVDS + "T_F41SCHEDULE_P1A_EMP.parquet"
CSVS = "Data Files/CSVs/"
MDB = "Data Files/MDBs/Dimension Tables/"
KEY = "%Key Field"
KEY_PARTS = ["Period", "%Airline ID", "%Unique Carrier Code", "%Carrier Group ID"]
MD, LT = "Main Data", "Link Table"

LINK_COLS = ["Year", "Period", "Month (#)", "Month", "Month__num", "Quarter", "%Airline ID", "%Unique Carrier Code",
             "%Carrier Group ID", "Unique Carrier", "Carrier Code", "Carrier Name"]
FLIGHT_COLS = [x for x in base.FLIGHT_COLS if x not in LINK_COLS]
EMPLOYMENT_COLS = ["# Full Time Employees", "# Part Time Employees", "# Total Employees", "# Equivalent FTEs"]

# (table, parquet, key, label columns, 'Unknown' members for missing fact keys, keys from)
DIMENSIONS = [
    ("Carrier Groups", QVDS + "Carrier Groups.parquet", "%Carrier Group ID", ["Carrier Group"], True, LT),
    ("Airlines", QVDS + "Airlines.parquet", "%Airline ID", ["Airline"], False, LT),
    ("Carrier Operating Region", QVDS + "Carrier Operating Region.parquet", "%Region Code",
     ["Carrier's Operating Region"], True, MD),
    ("Flight Types", QVDS + "Flight Types.parquet", "%Datasource ID", ["Flight Type"], False, MD),
    ("Distance Groups", QVDS + "Distance Groups.parquet", "%Distance Group ID", ["Distance Interval"], False, MD),
    ("Origin Airports", MDB + "Origin Airports.parquet", "%Origin Airport ID", ["Origin Airport"], False, MD),
    ("Destination Airports", MDB + "Destination Airports.parquet", "%Destination Airport ID",
     ["Destination Airport"], False, MD),
    ("Origin Markets", CSVS + "Origin Markets.parquet", "%Origin Airport Market ID", ["Origin Market"], True, MD),
    ("Destination Markets", CSVS + "Destination Markets.parquet", "%Destination Airport Market ID",
     ["Destination Market"], True, MD),
]
AIRCRAFT_COLS = [("%Aircraft Type ID", "int64"), ("Aircraft Name", "string"), ("Aircraft Manufacturer", "string"),
                 ("Aircraft Manufacturer Country", "string"), ("Aircraft Name Full", "string"),
                 ("Aircraft Name Abbreviated", "string"), ("Aircraft Begin Date", "date"),
                 ("Aircraft End Date", "int64"), ("Aircraft Age Classification", "string"),
                 ("Aircraft Engine Type", "string"), ("Aircraft Number Of Engines", "string")]

CN = dcol(LT, "Carrier Name")
# The chapter's sheets use these Ch15 base measures (sums and ratios over Main Data); Carrier reads the link table.
MEASURES = {pk: base.MEASURES[pk] for pk in (
    "1baea265cccd", "7f15ad08b3bb", "aea8a21aee5f", "e0ca719214a7", "0c8ca154aacf", "8dfad31060e3", "213681cc0d2a",
    "7588bff24d2c", "cd4c4a3c94f4", "a1ec8a2cb5ee", "072410d4365a")}
MEASURES["90777bd5df7f"] = ("Carrier", f"IF(DISTINCTCOUNTNOBLANK({CN}) = 1, MAX({CN}), \"Others\")", None)

GAPS = [
    "Link table: [Link Table] is not unique on [%Key Field] (10,073 rows, 10,068 keys; five Antonov keys carry Carrier "
    "Codes ADB and AUQ), so Main Data and Employment Statistics relate to it many-to-many, filtered from the link "
    "table. As in QlikView, a flight row of such a key counts once in totals and under each of its Carrier Codes.",
    "Fields on the link table (Year, Month, Quarter, Period, carrier names, Airlines, Carrier Groups) filter both "
    "facts; fields on one fact (e.g. Flight Type) do not filter the link table or the other fact. QlikView propagates "
    "selections in every direction; with no selections (the parity baseline) the results are the same.",
    "Null-key 'Unknown' members the script adds (Carrier Groups: 12 flight rows without a carrier group) are not "
    "loaded: they associate with nothing in QlikView and would wrongly match blank keys in Power BI (7 vs 8 rows).",
    "Aircraft Types: MAPPING LOAD / ApplyMap -> left merge on the first Country per manufacturer ('Unknown' when "
    "missing); LEFT JOIN -> merge; the script's STORE into Aircraft Types Transformed.qvd is not reproduced. "
    "QlikView trims unquoted text in delimited files, so the Aircraft_Group.csv labels are trimmed.",
    "Field and table comments from Comments.xls (COMMENT ... USING) are not migrated; config.qvs / tracerowcount.qvs "
    "are not in the repo and only set paths / log row counts.",
    "Calculated dimension: the Flight Type deal status -> calculated column on Flight Types.",
    "List boxes -> slicers on the field named by the list box's caption: Year, Quarter, Month, Flight Type, Carrier's "
    "Operating Region, Carrier Group, Carrier Name (Dashboard, Analysis, Reports); 11 origin / destination / carrier / "
    "distance fields (Associations); Aircraft Name, Year (Data Consistency). Associations' 'Aircraft Type' (LB10) and "
    "'Aircraft Group' (LB11) name no field of this model and are not migrated.",
    "Multi boxes MB01 'Flight Information' and MB02 'Aircraft' -> one slicer per field they contain, on the Dashboard, "
    "Analysis and Reports pages. Text objects, search object, buttons, bookmark object, current selections box, "
    "container, statistics box and table box have no Power BI equivalent and are not migrated; gauges become cards "
    "and the radar, mekko, grid, funnel and block charts are not rebuilt (their measures are in the model).",
]


def fn_key(row: str) -> str:
    return " & \" | \" & ".join(f'fnText({row}[#"{k}"])' for k in KEY_PARTS)


def table_specs(types: dict) -> dict[str, dict]:
    specs = {}
    ft, et = types[FLIGHT], types[EMPLOYMENT]
    md_cols = [(KEY, "string")] + [(x, ft[x]) for x in FLIGHT_COLS]
    specs[MD] = {"cols": md_cols, "m": m_let([
        f'Source = fnReadParquet("{FLIGHT}")',
        f'Keyed = Table.AddColumn(Source, "{KEY}", each {fn_key("_")}, type text)',
        f"Selected = Table.SelectColumns(Keyed, {m_list(n for n, _ in md_cols)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(md_cols)})"], "Typed")}
    es_cols = [(KEY, "string")] + [(x, et[x]) for x in EMPLOYMENT_COLS]
    specs["Employment Statistics"] = {"cols": es_cols, "m": m_let([
        f'Source = fnReadParquet("{EMPLOYMENT}")',
        f'Keyed = Table.AddColumn(Source, "{KEY}", each {fn_key("_")}, type text)',
        f"Selected = Table.SelectColumns(Keyed, {m_list(n for n, _ in es_cols)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(es_cols)})"], "Typed")}
    lt_cols = [(KEY, "string")] + [(x, ft[x]) for x in LINK_COLS]
    names = m_list(n for n, _ in lt_cols)
    specs[LT] = {"cols": lt_cols, "m": m_let([
        f'Flight = fnReadParquet("{FLIGHT}")',
        f'FlightKeyed = Table.AddColumn(Flight, "{KEY}", each {fn_key("_")}, type text)',
        f"FlightLinks = Table.Buffer(Table.Distinct(Table.SelectColumns(FlightKeyed, {names})))",
        f'Employment = fnReadParquet("{EMPLOYMENT}")',
        f'EmploymentKeyed = Table.AddColumn(Employment, "{KEY}", each {fn_key("_")}, type text)',
        'WithQuarter = Table.AddColumn(EmploymentKeyed, "Quarter", each "Q" & Text.From(Number.RoundUp([#"Month (#)"] / 3)), type text)',
        f"EmploymentLinks = Table.Distinct(Table.SelectColumns(WithQuarter, {names}))",
        "// Where Not Exists([%TEMP Key Field], [%Key Field]): employment keys no flight row has",
        f'NewKeys = Table.NestedJoin(EmploymentLinks, {{"{KEY}"}}, FlightLinks, {{"{KEY}"}}, "Flight", JoinKind.LeftAnti)',
        f"Combined = Table.Combine({{FlightLinks, Table.RemoveColumns(NewKeys, {{\"Flight\"}})}})",
        f"Typed = Table.TransformColumnTypes(Combined, {m_types(lt_cols)})"], "Typed")}
    for name, path, key, labels, unknown, _ in DIMENSIONS:
        cols = [(key, types[path][key])] + [(x, types[path][x]) for x in labels]
        steps = [f'Source = Table.SelectColumns(fnReadParquet("{path}"), {m_list([key, *labels])})',
                 f'FactKeys = List.Buffer(List.RemoveNulls(fnFactKeys("{key}")))',
                 f'Kept = Table.SelectRows(Source, each List.Contains(FactKeys, [#"{key}"]))']
        last = "Kept"
        if unknown:
            steps += [f'Missing = List.Difference(FactKeys, Table.Column(Kept, "{key}"))',
                      f'Unknown = Table.FromColumns({{Missing, List.Repeat({{"Unknown"}}, List.Count(Missing))}}, '
                      f'{m_list([key, labels[0]])})',
                      "Combined = Table.Combine({Kept, Unknown})"]
            last = "Combined"
        steps.append(f"Typed = Table.TransformColumnTypes({last}, {m_types(cols)})")
        specs[name] = {"cols": cols, "m": m_let(steps, "Typed")}
    fields = ['"Aircraft Name"', '"Aircraft Manufacturer"', '"Aircraft Manufacturer Country"', '"Aircraft Name Full"',
              '"Aircraft Name Abbreviated"', '"Aircraft Begin Date"', '"Aircraft End Date"']
    renames = "{" + ", ".join(f'{{"{a}", {b}}}' for a, b in zip(
        ["SSD_NAME", "MANUFACTURER", "Country", "LONG_NAME", "SHORT_NAME", "BEGIN_DATE", "END_DATE"], fields)) + \
        ', {"AC_TYPEID", "%Aircraft Type ID"}}'
    specs["Aircraft Types"] = {"cols": AIRCRAFT_COLS, "m": m_let([
        'FactKeys = List.Buffer(List.RemoveNulls(fnFactKeys("%Aircraft Type ID")))',
        "// MAPPING LOAD: the first Country of each manufacturer",
        f'Manufacturers = Table.Buffer(Table.Distinct(fnReadParquet("{CSVS}Aircraft_Manufacturers.parquet"), {{"Company"}}))',
        "ApplyMap = (t as table) => Table.ReplaceValue(Table.ExpandTableColumn(Table.NestedJoin(t, {\"MANUFACTURER\"}, "
        "Manufacturers, {\"Company\"}, \"Map\", JoinKind.LeftOuter), \"Map\", {\"Country\"}), null, \"Unknown\", "
        "Replacer.ReplaceValue, {\"Country\"})",
        f'BaseFile = Table.SelectRows(fnReadParquet("{CSVS}Aircraft_Base_File.parquet"), each List.Contains(FactKeys, [AC_TYPEID]))',
        'Aged = Table.AddColumn(ApplyMap(BaseFile), "Aircraft Age Classification", each '
        'if [BEGIN_DATE] <> null and Date.Year([BEGIN_DATE]) < 1990 then "Classic" else "Current", type text)',
        "// LEFT JOIN Aircraft_Group.csv; QlikView trims unquoted delimited text",
        f'Groups = Table.TransformColumns(fnReadParquet("{CSVS}Aircraft_Group.parquet"), '
        '{{"Aircraft Engine Type", Text.Trim}, {"Aircraft Number Of Engines", Text.Trim}})',
        'Joined = Table.ExpandTableColumn(Table.NestedJoin(Aged, {"AC_GROUP"}, Groups, {"Aircraft Group ID"}, "Group", '
        'JoinKind.LeftOuter), "Group", {"Aircraft Engine Type", "Aircraft Number Of Engines"})',
        f'Update = Table.SelectRows(fnReadParquet("{CSVS}Aircraft_2010_Update.parquet"), each List.Contains(FactKeys, [AC_TYPEID]))',
        'Split = Table.AddColumn(Table.AddColumn(Table.AddColumn(ApplyMap(Update), "Aircraft Engine Type", each '
        'Text.BeforeDelimiter([AC_GROUPNAME], ", "), type text), "Aircraft Number Of Engines", each '
        'if Text.Contains([AC_GROUPNAME], ", ") then Text.Split([AC_GROUPNAME], ", "){1} else null, type text), '
        '"Aircraft Age Classification", each "Current", type text)',
        "Combined = Table.Combine({Joined, Split})",
        f"Renamed = Table.RenameColumns(Combined, {renames})",
        f"Selected = Table.SelectColumns(Renamed, {m_list(n for n, _ in AIRCRAFT_COLS)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(AIRCRAFT_COLS)})"], "Typed")}
    return specs


def write_table(path: Path, name: str, spec: dict, measures: list[dict], calc: list[tuple]):
    names = {n for n, _ in spec["cols"]}
    lines = [f"table {tname(name)}", f"\tlineageTag: {tag(SLUG, name)}", ""]
    for mz in measures:
        lines += [f"\tmeasure {tname(mz['name'])} = {mz['dax']}"]
        if mz["fmt"]:
            lines.append(f"\t\tformatString: {mz['fmt']}")
        lines += [f"\t\tlineageTag: {tag(SLUG, name, 'm', mz['parity_key'])}", "",
                  f"\t\tannotation ParityKey = {mz['parity_key']}", f"\t\tannotation QlikExpression = {mz['qlik']}",
                  f"\t\tannotation QlikObjects = {', '.join(mz['kpis'])}", ""]
    for col, typ in spec["cols"]:
        dtype, _, fmt = TYPE_MAP[typ]
        lines += [f"\tcolumn {tname(col)}", f"\t\tdataType: {dtype}"]
        sort = f"{col}__num" if f"{col}__num" in names else None
        if col.startswith("%") or col.endswith("__num"):
            lines.append("\t\tisHidden")
        if sort:
            lines.append(f"\t\tsortByColumn: {tname(sort)}")
        if fmt and col not in ("Period", "Year"):
            lines.append(f"\t\tformatString: {fmt}")
        lines += [f"\t\tlineageTag: {tag(SLUG, name, 'c', col)}",
                  f"\t\tsummarizeBy: {'sum' if col.startswith('#') else 'none'}", f"\t\tsourceColumn: {col}", "",
                  "\t\tannotation SummarizationSetBy = Automatic", ""]
    for _, col, qlik, dax, typ in calc:
        lines += [f"\tcolumn {tname(col)} = {dax}", f"\t\tdataType: {typ}",
                  f"\t\tlineageTag: {tag(SLUG, name, 'c', col)}", "\t\tsummarizeBy: none", "",
                  f"\t\tannotation ParityKey = {parity_key(qlik)}",
                  f"\t\tannotation QlikDimension = {' '.join(qlik.split())}", ""]
    lines += [f"\tpartition {tname(name)} = m", "\t\tmode: import", "\t\tsource =", spec["m"], ""]
    fname = re.sub(r'[<>:"/\\|?*]', "_", name)
    (path / f"{fname}.tmdl").write_text("\n".join(lines), encoding="utf-8")


def relationships() -> list[tuple[str, str, str, str, bool]]:
    """(from table, column, to table, column, many-to-many)."""
    rels = [(MD, KEY, LT, KEY, True), ("Employment Statistics", KEY, LT, KEY, True)]
    rels += [(src, key, name, key, False) for name, _, key, _, _, src in DIMENSIONS]
    rels.append((MD, "%Aircraft Type ID", "Aircraft Types", "%Aircraft Type ID", False))
    return rels


# ------------------------------------------------------------------ report
def _field(entity: str, prop: str, measure: bool) -> tuple[dict, str]:
    kind = "Measure" if measure else "Column"
    return {kind: {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop},
            "Name": f"{entity}.{prop}"}, f"{entity}.{prop}"


def visual(page: str, i: int, vtype: str, pos: tuple[int, int, int, int], roles: dict[str, list[tuple]],
           title: str | None = None) -> dict:
    x, y, w, h = pos
    select, projections = [], {}
    for role, fields in roles.items():
        for entity, prop, measure in fields:
            sel, ref = _field(entity, prop, measure)
            if ref not in {s["Name"] for s in select}:
                select.append(sel)
            projections.setdefault(role, []).append({"queryRef": ref})
    single = {"visualType": vtype, "projections": projections,
              "prototypeQuery": {"Version": 2, "From": [], "Select": select}, "drillFilterOtherVisuals": True}
    entities = sorted({s[k]["Expression"]["SourceRef"]["Entity"] for s in select for k in ("Measure", "Column") if k in s})
    alias = {e: f"t{n}" for n, e in enumerate(entities)}
    single["prototypeQuery"]["From"] = [{"Name": alias[e], "Entity": e, "Type": 0} for e in entities]
    for s in select:
        k = "Measure" if "Measure" in s else "Column"
        s[k]["Expression"]["SourceRef"] = {"Source": alias[s[k]["Expression"]["SourceRef"]["Entity"]]}
    if title:
        single["vcObjects"] = {"title": [{"properties": {
            "show": {"expr": {"Literal": {"Value": "true"}}}, "text": {"expr": {"Literal": {"Value": f"'{title}'"}}}}}]}
    config = {"name": tag(SLUG, "visual", page, str(i)),
              "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": i, "width": w, "height": h}}],
              "singleVisual": single}
    return {"x": x, "y": y, "z": i, "width": w, "height": h, "config": json.dumps(config), "filters": "[]"}


def M(name):  # noqa: N802
    return (MD, name, True)


def C(table, name):  # noqa: N802
    return (table, name, False)


# QlikView list boxes -> slicers, by caption (font, font, caption, object id in the .qvw document block).
# LB27-LB33 sit on the Dashboard, Analysis and Reports sheets:
SLICERS = [C(LT, "Year"), C(LT, "Quarter"), C(LT, "Month"), C("Flight Types", "Flight Type"),
           C("Carrier Operating Region", "Carrier's Operating Region"), C("Carrier Groups", "Carrier Group"),
           C(LT, "Carrier Name")]
# Associations sheet LB01-LB15 (LB10 'Aircraft Type' and LB11 'Aircraft Group' name no model field):
ASSOCIATIONS = [C(MD, "Destination Country"), C(MD, "Destination State"), C(MD, "Destination City"),
                C(MD, "Origin Country"), C(MD, "Origin State"), C(MD, "Origin City"), C(LT, "Carrier Name"),
                C("Distance Groups", "Distance Interval"), C("Flight Types", "Flight Type"),
                C("Carrier Operating Region", "Carrier's Operating Region"), C("Carrier Groups", "Carrier Group")]
# Multi boxes -> one slicer per field (field list after the caption / id in the document block), below the charts:
MULTI_BOXES = [C(MD, "Destination City"), C(MD, "Destination Country"), C("Distance Groups", "Distance Interval"),
               C(MD, "From - To City"), C(MD, "Origin City"), C(MD, "Origin Country"),  # MB01 'Flight Information'
               C("Aircraft Types", "Aircraft Name"), C("Aircraft Types", "Aircraft Engine Type"),  # MB02 'Aircraft'
               C("Aircraft Types", "Aircraft Number Of Engines"), C("Aircraft Types", "Aircraft Manufacturer"),
               C("Aircraft Types", "Aircraft Manufacturer Country"), C("Aircraft Types", "Aircraft Age Classification")]
# Data Consistency sheet LB34 / LB35:
CONSISTENCY = [C("Aircraft Types", "Aircraft Name"), C(LT, "Year")]
PAGES = [
    ("Dashboard", [
        ("columnChart", (240, 20, 500, 220), {"Category": [C(LT, "Year"), C(LT, "Month")], "Y": [M("# of Flights")]},
         "Traffic by Year (CH01)"),
        ("barChart", (760, 20, 500, 220), {"Category": [C(MD, "From - To City")], "Y": [M("# of Enplanned Passengers")]},
         "Top Routes (CH02)"),
        ("clusteredColumnChart", (240, 260, 500, 220), {"Category": [C("Flight Types", "Flight Type")],
                                                        "Y": [M("# of Passengers (millions)"), M("# of Available Seats (millions)")]},
         "Passengers and Seats by Flight Type (CH03)"),
        ("tableEx", (760, 260, 500, 220), {"Values": [C(LT, "Carrier Name"), M("# of Enplanned Passengers"),
                                                      M("Transported Mail"), M("Transported Freight")]},
         "Transported Passengers vs Mail (CH04)"),
        ("card", (240, 500, 250, 100), {"Values": [M("Load Factor")]}, "Load Factor"),
        ("card", (500, 500, 250, 100), {"Values": [M("Performed vs Scheduled")]}, "Performed vs Scheduled"),
        ("card", (760, 500, 250, 100), {"Values": [M("Air Time %")]}, "Air Time %"),
        ("card", (1020, 500, 240, 100), {"Values": [M("# of Flights")]}, "# of Flights"),
    ]),
    ("Analysis", [
        ("pivotTable", (240, 20, 1020, 330), {"Rows": [C("Carrier Groups", "Carrier Group"), C("Airlines", "Airline"),
                                                       C(LT, "Year"), C(LT, "Month")],
                                              "Values": [M("Load Factor")]}, "Load Factor by Carrier (CH22)"),
        ("columnChart", (240, 370, 500, 330), {"Category": [C(LT, "Month")], "Y": [M("# of Passengers (millions)")]},
         "Passengers by Month (CH24)"),
        ("barChart", (760, 370, 500, 330), {"Category": [C("Airlines", "Airline")], "Y": [M("Air Time % (CH21)")]},
         "Air Time % by Airline (CH21)"),
    ]),
    ("Reports", [
        ("pivotTable", (240, 20, 500, 330), {"Rows": [C(LT, "Year"), C(LT, "Quarter"), C("Flight Types", "Flight Type")],
                                             "Values": [M("# of Passengers (millions)")]}, "Passengers by Quarter (CH26)"),
        ("tableEx", (760, 20, 500, 330), {"Values": [C("Flight Types", "Deal Status"), M("# of Passengers (millions)")]},
         "Deal Status (CH27)"),
        ("pivotTable", (240, 370, 500, 330), {"Rows": [C(MD, "Destination Country"), C(MD, "Destination City")],
                                              "Values": [M("Load Factor")]}, "Destinations (CH28)"),
        ("pivotTable", (760, 370, 500, 330), {"Rows": [C("Aircraft Types", "Aircraft Engine Type"),
                                                       C("Aircraft Types", "Aircraft Number Of Engines")],
                                              "Values": [M("Performed vs Scheduled")]}, "Aircraft Engines (CH38)"),
    ]),
    ("Associations", []),
    ("Data Consistency", [
        ("tableEx", (240, 20, 1020, 330), {"Values": [C(LT, "Year"), C(LT, "Carrier Name"), M("# of Flights"),
                                                      C("Carrier Groups", "Carrier Group")]},
         "Flights through the Link Table"),
    ]),
]


def report() -> dict:
    sections = []
    for n, (page, visuals) in enumerate(PAGES):
        if page == "Associations":
            vcs = [visual(page, i, "slicer", (20 + (i % 4) * 315, 20 + (i // 4) * 235, 305, 225), {"Values": [f]})
                   for i, f in enumerate(ASSOCIATIONS)]
        else:
            fields = CONSISTENCY if page == "Data Consistency" else SLICERS
            vcs = [visual(page, i, "slicer", (20, 20 + i * 98, 200, 92), {"Values": [f]}) for i, f in enumerate(fields)]
            if page != "Data Consistency":
                vcs += [visual(page, len(vcs) + i, "slicer", (240 + (i % 6) * 172, 730 + (i // 6) * 170, 165, 160),
                               {"Values": [f]}) for i, f in enumerate(MULTI_BOXES)]
        vcs += [visual(page, len(vcs) + i, vt, pos, roles, title) for i, (vt, pos, roles, title) in enumerate(visuals)]
        height = 1080 if page not in ("Associations", "Data Consistency") else 720
        sections.append({"name": f"ReportSection{n}", "displayName": page, "displayOption": 1, "ordinal": n,
                         "width": 1280, "height": height, "config": "{}", "filters": "[]", "visualContainers": vcs})
    return {"config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
            "layoutOptimization": 0, "resourcePackages": [], "sections": sections}


def build(data_root: str = DEFAULT_ROOT) -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = APPS / SLUG
    sm, rp = root / f"{SLUG}.SemanticModel", root / f"{SLUG}.Report"
    for d in (sm / "definition" / "tables", rp):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.tmdl"):
            f.unlink()
    measures: dict[str, dict] = {}
    for k in kpi_list(manifest):
        pk = k["parity_key"]
        if pk not in MEASURES:
            raise SystemExit(f"{k['kpi']}: no measure for ParityKey {pk}: {k['expression']}")
        mz = measures.setdefault(pk, {"parity_key": pk, "name": MEASURES[pk][0], "dax": MEASURES[pk][1],
                                      "fmt": MEASURES[pk][2], "kpis": [], "qlik": " ".join(k["expression"].split())})
        mz["kpis"].append(k["kpi"])
        for d in k["dims"]:
            if d.startswith("=") and d not in {x[2] for x in CALC_DIMS}:
                raise SystemExit(f"{k['kpi']}: no calculated column for dimension {d!r}")
    if unused := set(MEASURES) - set(measures):
        raise SystemExit(f"measures without a KPI: {sorted(unused)}")
    specs = table_specs(catalog_types())
    for name, spec in specs.items():
        write_table(sm / "definition" / "tables", name, spec, list(measures.values()) if name == MD else [],
                    [x for x in CALC_DIMS if x[0] == name])
    rels = []
    for ft, fc, tt, tc, many in relationships():
        rels += [f"relationship {tag(SLUG, 'rel', ft, fc, tt)}"]
        if many:
            rels += ["\tfromCardinality: many", "\ttoCardinality: many"]
        rels += [f"\tfromColumn: {tname(ft)}.{tname(fc)}", f"\ttoColumn: {tname(tt)}.{tname(tc)}", ""]
    (sm / "definition" / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")
    (sm / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n", encoding="utf-8")
    refs = "\n".join(f"ref table {tname(t)}" for t in specs)
    order = ["DataRoot", "fnReadParquet", "fnText", "fnFactKeys", *specs]
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
        f"\tlineageTag: {tag(SLUG, 'fnReadParquet')}\n\n"
        "expression fnText =\n"
        "\t\t// QlikView's & treats null as an empty string\n"
        '\t\t(v) as text => if v = null then "" else Text.From(v)\n'
        f"\tlineageTag: {tag(SLUG, 'fnText')}\n\n"
        "expression fnFactKeys =\n"
        "\t\t// Distinct values of a fact field: QlikView's Exists() after the fact and link table loads\n"
        "\t\t(column as text) as list =>\n"
        "\t\tlet\n"
        f'\t\t    Flight = fnReadParquet("{FLIGHT}"),\n'
        f'\t\t    Employment = fnReadParquet("{EMPLOYMENT}"),\n'
        "\t\t    FromTable = (t as table) => if Table.HasColumns(t, column) then Table.Column(t, column) else {},\n"
        "\t\t    KeyValues = List.Distinct(FromTable(Flight) & FromTable(Employment))\n"
        "\t\tin\n"
        "\t\t    KeyValues\n"
        f"\tlineageTag: {tag(SLUG, 'fnFactKeys')}\n", encoding="utf-8")
    (sm / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2) + "\n")
    (rp / "definition.pbir").write_text(json.dumps(
        {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{SLUG}.SemanticModel"}}}, indent=2) + "\n")
    (rp / "report.json").write_text(json.dumps(report(), indent=2) + "\n")
    (root / f"{SLUG}.pbip").write_text(json.dumps(
        {"version": "1.0", "artifacts": [{"report": {"path": f"{SLUG}.Report"}}], "settings": {"enableAutoRecovery": True}},
        indent=2) + "\n")
    (root / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    (root / "model.json").write_text(json.dumps(
        {"app": APP, "generated_by": "powerbi/tools/build_link_table.py",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in measures.values()],
         "calculated_dimensions": [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q, "dax": d}
                                   for t, col, q, d, _ in CALC_DIMS],
         "semantic_gaps": GAPS}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(specs)} tables, {len(relationships())} relationships, {len(measures)} measures, "
          f"{len(CALC_DIMS)} calculated columns, {len(PAGES)} report pages")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
