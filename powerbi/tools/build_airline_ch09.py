"""Generate the Chapter 09 Airline Operations PBIP, derived from the Chapter 15 base model.

Chapter 9's script is an earlier version of the same model: [Main Data] (Flight Data.qvd + Concatenate
T_F41SCHEDULE_P1A_EMP.qvd), a monthly Master Calendar, WHERE Exists / LEFT KEEP dimensions with 'Unknown' members and
an Aircraft Types table built from CSVs (ApplyMap, LEFT JOIN, CONCATENATE). It has no Section Access, alternate states,
inline tables or include-file variables, so this builder keeps only those parts of build_airline_base.py and reuses its
measures (by ParityKey), calculated column and TMDL writer.

    python powerbi/tools/build_airline_ch09.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_airline_base as base  # noqa: E402
from build_airline_base import CALC_DIMS, FLIGHT_COLS, MEASURES, catalog_types, m_let, m_list, m_types, write_table  # noqa: E402

from harness import kpi_list, parity_key  # noqa: E402  (build_airline_base puts parity/ on sys.path)
from scaffold_pbip import APPS, REPO, show, tag, tname  # noqa: E402

APP = "Chapter09__Solution_Chapter 9_Airline Operations"
SLUG = "Chapter09_Airline_Operations"
FLIGHT = "Data Files/QVDs/Flight Data.parquet"
EMPLOYMENT = "Data Files/QVDs/T_F41SCHEDULE_P1A_EMP.parquet"
COMMENTS = REPO / "Data Files" / "Excel" / "Comments.xls"
EMPLOYMENT_COLS = ["%Airline ID", "%Unique Carrier Code", "%Carrier Group ID", "# Full Time Employees",
                   "# Part Time Employees", "# Total Employees", "# Equivalent FTEs", "Unique Carrier", "Carrier Code",
                   "Carrier Name", "Period"]
CSV = "Data Files/CSVs/"
# (table, parquet, key, label columns, add 'Unknown' members for fact keys missing from the dimension)
DIMENSIONS = [
    ("Carrier Groups", "Data Files/QVDs/Carrier Groups.parquet", "%Carrier Group ID", ["Carrier Group"], True),
    ("Airlines", "Data Files/QVDs/Airlines.parquet", "%Airline ID", ["Airline"], False),
    ("Carrier Operating Region", "Data Files/QVDs/Carrier Operating Region.parquet", "%Region Code",
     ["Carrier's Operating Region"], True),
    ("Flight Types", "Data Files/QVDs/Flight Types.parquet", "%Datasource ID", ["Flight Type"], False),
    ("Distance Groups", "Data Files/QVDs/Distance Groups.parquet", "%Distance Group ID", ["Distance Interval"], False),
    ("Origin Airports", "Data Files/MDBs/Dimension Tables/Origin Airports.parquet", "%Origin Airport ID",
     ["Origin Airport"], False),
    ("Destination Airports", "Data Files/MDBs/Dimension Tables/Destination Airports.parquet",
     "%Destination Airport ID", ["Destination Airport"], False),
    ("Origin Markets", CSV + "Origin Markets.parquet", "%Origin Airport Market ID", ["Origin Market"], True),
    ("Destination Markets", CSV + "Destination Markets.parquet", "%Destination Airport Market ID",
     ["Destination Market"], True),
]
AIRCRAFT_COLS = [("%Aircraft Type ID", "int64"), ("Aircraft Name", "string"), ("Aircraft Manufacturer", "string"),
                 ("Aircraft Manufacturer Country", "string"), ("Aircraft Name Full", "string"),
                 ("Aircraft Name Abbreviated", "string"), ("Aircraft Begin Date", "date"),
                 ("Aircraft End Date", "int64"), ("Aircraft Age Classification", "string"),
                 ("Aircraft Engine Type", "string"), ("Aircraft Number Of Engines", "string")]
CAL_COLS = [("Period", "int64"), ("Year", "int64"), ("Month", "string"), ("Month__num", "float64"),
            ("Year - Month", "string"), ("Year - Month__num", "float64"), ("Quarter", "string")]

GAPS = [
    "Master Calendar: one row per month (36) as in QlikView; Month and Year - Month are labels sorted by hidden "
    "Month__num / Year - Month__num columns (QlikView duals).",
    "Null-key 'Unknown' members the script adds for null fact keys (Carrier Groups, Carrier Operating Region, Origin / "
    "Destination Markets) are not loaded: they associate with nothing in QlikView and would wrongly match blank keys "
    "in Power BI. Dimension row counts are therefore one lower than QlikView's where [Main Data] has null keys; "
    "measures are unaffected.",
    "Aircraft Types: empty CSV fields are null in Power BI (QlikView stores an empty string, e.g. the manufacturer of "
    "aircraft type 91); ApplyMap's default 'Unknown' applies to both.",
    "COMMENT TABLES / FIELDS USING Comments.xls -> TMDL descriptions on the table and on every column of that name "
    "(QlikView comments a field in every table).",
    "STORE [Aircraft Types] INTO 'Aircraft Types Transformed.qvd' is an ETL side effect and is not migrated; "
    "IF $(vLoadMainData) = 'Y' always loads.",
    "Calculated dimension (Flight Type deal status, Funnel Chart CH27) -> calculated column on Flight Types.",
    "Drill-down group Time (Year > Month) and cyclic group Airline_Origin_Destination -> parity at every level; "
    "in the report as a Year > Month hierarchy and separate visuals.",
    "QlikView-only objects (multi boxes, search object, buttons, bookmark object, current selections, container, "
    "statistics box, text objects) are approximated by slicers and cards; gauge styles (CH07-CH14) are one gauge.",
]


def dax_measure(name: str) -> str:
    return f"[{name}]"


def table_specs(types: dict) -> dict[str, dict]:
    specs = {}
    emp_only = [x for x in EMPLOYMENT_COLS if x not in FLIGHT_COLS]
    md_cols = [(x, types[FLIGHT][x]) for x in FLIGHT_COLS] + [(x, types[EMPLOYMENT][x]) for x in emp_only]
    specs["Main Data"] = {"cols": md_cols, "m": m_let([
        f'Flight = Table.SelectColumns(fnReadParquet("{FLIGHT}"), {m_list(FLIGHT_COLS)})',
        f'Employment = Table.SelectColumns(fnReadParquet("{EMPLOYMENT}"), {m_list(EMPLOYMENT_COLS)})',
        "Combined = Table.Combine({Flight, Employment})",
        f"Typed = Table.TransformColumnTypes(Combined, {m_types(md_cols)})"], "Typed")}
    specs["Master Calendar"] = {"cols": CAL_COLS, "m": m_let([
        'Periods = List.RemoveNulls(fnFactKeys("Period"))',
        "MinDate = #date(Number.IntegerDivide(List.Min(Periods), 100), Number.Mod(List.Min(Periods), 100), 1)",
        "MaxDate = #date(Number.IntegerDivide(List.Max(Periods), 100), Number.Mod(List.Max(Periods), 100), 1)",
        "Months = List.Generate(() => MinDate, each _ <= MaxDate, each Date.AddMonths(_, 1))",
        'Base = Table.FromList(Months, Splitter.SplitByNothing(), {"MonthStart"})',
        'Cols = Table.AddColumn(Base, "Fields", each [Period = Date.Year([MonthStart]) * 100 + Date.Month([MonthStart]), '
        'Year = Date.Year([MonthStart]), Month = Date.ToText([MonthStart], "MMM", "en-US"), '
        'Month__num = Date.Month([MonthStart]), #"Year - Month" = Date.ToText([MonthStart], "yyyy-MM", "en-US"), '
        '#"Year - Month__num" = Number.From([MonthStart]), '
        'Quarter = "Q" & Text.From(Number.RoundUp(Date.Month([MonthStart]) / 3))])',
        f'Expanded = Table.ExpandRecordColumn(Cols, "Fields", {m_list(n for n, _ in CAL_COLS)})',
        f"Selected = Table.SelectColumns(Expanded, {m_list(n for n, _ in CAL_COLS)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(CAL_COLS)})"], "Typed")}
    for name, path, key, labels, unknown in DIMENSIONS:
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
    src = ["AC_TYPEID", "SSD_NAME", "MANUFACTURER", "LONG_NAME", "SHORT_NAME", "BEGIN_DATE", "END_DATE"]
    out = [n for n, _ in AIRCRAFT_COLS]
    renames = "{" + ", ".join(f'{{"{a}", "{b}"}}' for a, b in [
        ("AC_TYPEID", "%Aircraft Type ID"), ("SSD_NAME", "Aircraft Name"), ("MANUFACTURER", "Aircraft Manufacturer"),
        ("LONG_NAME", "Aircraft Name Full"), ("SHORT_NAME", "Aircraft Name Abbreviated"),
        ("BEGIN_DATE", "Aircraft Begin Date"), ("END_DATE", "Aircraft End Date")]) + "}"
    country = ('each let i = List.PositionOf(Companies, [MANUFACTURER]) in '
               'if [MANUFACTURER] = null or i < 0 then "Unknown" else Countries{i}')
    specs["Aircraft Types"] = {"cols": AIRCRAFT_COLS, "m": m_let([
        "// ApplyMap('Map_Manufacturer_Country', MANUFACTURER, 'Unknown'): first matching Company",
        f'Manufacturers = Table.Buffer(fnReadParquet("{CSV}Aircraft_Manufacturers.parquet"))',
        'Companies = Manufacturers[Company]',
        'Countries = Manufacturers[Country]',
        'FactKeys = List.Buffer(List.RemoveNulls(fnFactKeys("%Aircraft Type ID")))',
        f'BaseFile = Table.SelectColumns(fnReadParquet("{CSV}Aircraft_Base_File.parquet"), '
        f'{m_list(["AC_GROUP", *src])})',
        "BaseKept = Table.SelectRows(BaseFile, each List.Contains(FactKeys, [AC_TYPEID]))",
        f'BaseCountry = Table.AddColumn(BaseKept, "Aircraft Manufacturer Country", {country})',
        'BaseAge = Table.AddColumn(BaseCountry, "Aircraft Age Classification", each '
        'if [BEGIN_DATE] <> null and Date.Year([BEGIN_DATE]) < 1990 then "Classic" else "Current")',
        "// LEFT JOIN Aircraft_Group.csv on the aircraft group; QlikView trims the unquoted text fields",
        f'Groups = Table.TransformColumns(fnReadParquet("{CSV}Aircraft_Group.parquet"), '
        '{{"Aircraft Engine Type", Text.Trim}, {"Aircraft Number Of Engines", Text.Trim}})',
        'Joined = Table.NestedJoin(BaseAge, {"AC_GROUP"}, Groups, {"Aircraft Group ID"}, "Group", JoinKind.LeftOuter)',
        'BaseEngines = Table.ExpandTableColumn(Joined, "Group", {"Aircraft Engine Type", "Aircraft Number Of Engines"})',
        f"BaseRenamed = Table.RenameColumns(Table.RemoveColumns(BaseEngines, {{\"AC_GROUP\"}}), {renames})",
        "// CONCATENATE the 2010 update: engine type and number from SubField(AC_GROUPNAME, ', ', 1 / 2)",
        f'Update = Table.SelectColumns(fnReadParquet("{CSV}Aircraft_2010_Update.parquet"), '
        f'{m_list(["AC_GROUPNAME", *src])})',
        "UpdateKept = Table.SelectRows(Update, each List.Contains(FactKeys, [AC_TYPEID]))",
        f'UpdateCountry = Table.AddColumn(UpdateKept, "Aircraft Manufacturer Country", {country})',
        'UpdateAge = Table.AddColumn(UpdateCountry, "Aircraft Age Classification", each "Current")',
        'UpdateType = Table.AddColumn(UpdateAge, "Aircraft Engine Type", each '
        'if [AC_GROUPNAME] = null then null else Text.Split([AC_GROUPNAME], ", "){0}?)',
        'UpdateEngines = Table.AddColumn(UpdateType, "Aircraft Number Of Engines", each '
        'if [AC_GROUPNAME] = null then null else Text.Split([AC_GROUPNAME], ", "){1}?)',
        f"UpdateRenamed = Table.RenameColumns(Table.RemoveColumns(UpdateEngines, {{\"AC_GROUPNAME\"}}), {renames})",
        f"Combined = Table.Combine({{Table.SelectColumns(BaseRenamed, {m_list(out)}), "
        f"Table.SelectColumns(UpdateRenamed, {m_list(out)})}})",
        f"Typed = Table.TransformColumnTypes(Combined, {m_types(AIRCRAFT_COLS)})"], "Typed")}
    return specs


def relationships() -> list[tuple[str, str, str, str]]:
    rels = [("Main Data", key, name, key) for name, _, key, _, _ in DIMENSIONS]
    rels.insert(4, ("Main Data", "%Aircraft Type ID", "Aircraft Types", "%Aircraft Type ID"))
    rels.append(("Main Data", "Period", "Master Calendar", "Period"))
    return rels


def comments() -> tuple[dict[str, str], dict[str, str]]:
    """COMMENT TABLES / FIELDS USING the Comments.xls mapping tables."""
    sheets = pd.read_excel(COMMENTS, sheet_name=["Tables", "Fields"], dtype=str, engine="xlrd")
    return (dict(zip(sheets["Tables"]["TableName"], sheets["Tables"]["Comment"])),
            dict(zip(sheets["Fields"]["FieldName"], sheets["Fields"]["Comment"])))


def add_descriptions(path: Path, table: str, table_comments: dict, field_comments: dict) -> None:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("table ") and table in table_comments:
            out.append(f"/// {table_comments[table]}")
        elif (mt := re.match(r"^\tcolumn ('(?:[^']|'')*'|\S+)$", line)):
            col = mt.group(1)
            col = col[1:-1].replace("''", "'") if col.startswith("'") else col
            if col in field_comments:
                out.append(f"\t/// {field_comments[col]}")
        out.append(line)
    path.write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------- report: one page per QlikView sheet with charts
def _field(entity: str, prop: str, kind: str = "Column") -> dict:
    return {"kind": kind, "entity": entity, "prop": prop}


def col(table: str, name: str) -> dict:
    return _field(table, name)


def meas(name: str) -> dict:
    return _field("Main Data", name, "Measure")


def visual(page: str, idx: int, vtype: str, title: str, pos: tuple[int, int, int, int], roles: dict) -> dict:
    x, y, w, h = pos
    aliases, select, projections = {}, [], {}
    for role, fields in roles.items():
        projections[role] = []
        for f in fields:
            alias = aliases.setdefault(f["entity"], f"t{len(aliases)}")
            ref = f"{f['entity']}.{f['prop']}"
            if ref not in {s["Name"] for s in select}:
                select.append({f["kind"]: {"Expression": {"SourceRef": {"Source": alias}}, "Property": f["prop"]},
                               "Name": ref})
            projections[role].append({"queryRef": ref})
    config = {"name": tag(SLUG, "visual", page, str(idx)),
              "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": idx, "width": w, "height": h}}],
              "singleVisual": {
                  "visualType": vtype, "projections": projections,
                  "prototypeQuery": {"Version": 2,
                                     "From": [{"Name": a, "Entity": e, "Type": 0} for e, a in aliases.items()],
                                     "Select": select},
                  "vcObjects": {"title": [{"properties": {
                      "show": {"expr": {"Literal": {"Value": "true"}}},
                      "text": {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}}}}]},
                  "drillFilterOtherVisuals": True}}
    return {"x": x, "y": y, "z": idx, "width": w, "height": h, "config": json.dumps(config), "filters": "[]"}


CAL, MD, FT = "Master Calendar", "Main Data", "Flight Types"
PAGES = [
    ("Dashboard", "SH03", [
        ("slicer", "Year", (10, 10, 150, 150), {"Values": [col(CAL, "Year")]}),
        ("slicer", "Month", (10, 170, 150, 300), {"Values": [col(CAL, "Month")]}),
        ("slicer", "Carrier Group", (10, 480, 150, 230), {"Values": [col("Carrier Groups", "Carrier Group")]}),
        ("gauge", "Load Factor %", (170, 10, 360, 170), {"Y": [meas("Load Factor")]}),
        ("gauge", "Performed vs Scheduled", (540, 10, 360, 170), {"Y": [meas("Performed vs Scheduled")]}),
        ("gauge", "Air Time %", (910, 10, 360, 170), {"Y": [meas("Air Time %")]}),
        ("lineChart", "Traffic per Year", (170, 190, 550, 260),
         {"Category": [col(CAL, "Year"), col(CAL, "Month")], "Y": [meas("# of Flights")]}),
        ("lineClusteredColumnComboChart", "# of Passengers/Available Seats (x 1 million) by Flight Type",
         (730, 190, 540, 260), {"Category": [col(FT, "Flight Type")],
                                "Y": [meas("# of Passengers (millions)"), meas("# of Available Seats (millions)")],
                                "Y2": [meas("Load Factor")]}),
        ("tableEx", "Top 10 Routes", (170, 460, 550, 250),
         {"Values": [col(MD, "From - To City"), meas("# of Flights"), meas("# of Enplanned Passengers"),
                     meas("Transported Freight"), meas("Transported Mail")]}),
        ("pieChart", "Market Share", (730, 460, 540, 250),
         {"Category": [col(MD, "Carrier Name")], "Y": [meas("# of Enplanned Passengers")]}),
    ]),
    ("Analysis", "SH_Analysis", [
        ("scatterChart", "Transported passengers vs mail", (10, 10, 1260, 700),
         {"Category": [col(MD, "Carrier Name")], "X": [meas("Transported Mail")],
          "Y": [meas("# of Enplanned Passengers")], "Size": [meas("# of Flights")]}),
    ]),
    ("Reports", "SH05", [
        ("tableEx", "KPIs per Airline", (10, 10, 620, 700),
         {"Values": [col("Airlines", "Airline"), meas("Load Factor"), meas("Performed vs Scheduled"),
                     meas("Air Time % (CH21)")]}),
        ("pivotTable", "Enplaned passengers (millions)", (640, 10, 630, 700),
         {"Rows": [col("Carrier Groups", "Carrier Group"), col("Airlines", "Airline")],
          "Columns": [col(CAL, "Year"), col(CAL, "Month")],
          "Values": [meas("# of Passengers (millions)"), meas("Departures Performed (thousands)")]}),
    ]),
    ("Other Charts", "SH06", [
        ("lineChart", "Traffic per Year by Flight Type", (10, 10, 620, 230),
         {"Category": [col(CAL, "Month")], "Series": [col(FT, "Flight Type")], "Y": [meas("Load Factor")]}),
        ("radarChart", "Radar Chart", (640, 10, 630, 230),
         {"Category": [col(CAL, "Month")], "Y": [meas("# of Passengers (millions)")]}),
        ("hundredPercentStackedColumnChart", "Mekko Chart", (10, 250, 410, 230),
         {"Category": [col(CAL, "Year")], "Series": [col(FT, "Flight Type")],
          "Y": [meas("# of Passengers (millions)")]}),
        ("matrix", "Grid Chart", (430, 250, 410, 230),
         {"Rows": [col(CAL, "Year"), col(CAL, "Quarter")], "Columns": [col(FT, "Flight Type")],
          "Values": [meas("# of Passengers (millions)")]}),
        ("funnel", "Funnel Chart", (850, 250, 420, 230),
         {"Category": [col(FT, "Deal Status")], "Y": [meas("# of Passengers (millions)")]}),
        ("treemap", "Block Chart", (10, 490, 1260, 220),
         {"Group": [col(MD, "Destination Country"), col(MD, "Destination City")],
          "Values": [meas("# of Passengers (millions)")]}),
    ]),
    ("Other representations", "SH08", [
        ("tableEx", "Other representations", (10, 10, 1260, 400),
         {"Values": [col("Aircraft Types", "Aircraft Engine Type"), col("Aircraft Types", "Aircraft Number Of Engines"),
                     meas("Load Factor"), meas("Performed vs Scheduled"), meas("Air Time % (CH21)")]}),
    ]),
]


def report() -> dict:
    sections = []
    for i, (page, sheet, visuals) in enumerate(PAGES):
        sections.append({"name": tag(SLUG, "page", sheet).replace("-", "")[:20], "displayName": page,
                         "displayOption": 1, "ordinal": i, "width": 1280, "height": 720,
                         "config": json.dumps({"objects": {}, "QlikSheet": sheet}), "filters": "[]",
                         "visualContainers": [visual(page, j, *v) for j, v in enumerate(visuals)]})
    return {"config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
            "layoutOptimization": 0, "resourcePackages": [], "sections": sections}


def build(data_root: str = base.DEFAULT_ROOT) -> Path:
    manifest = json.loads((base.POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = APPS / SLUG
    sm, rp = root / f"{SLUG}.SemanticModel", root / f"{SLUG}.Report"
    for d in (sm / "definition" / "tables", rp):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.tmdl"):
            f.unlink()
    calc_dims = {x[2] for x in CALC_DIMS}
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
            if d.startswith("=") and d not in calc_dims:
                raise SystemExit(f"{k['kpi']}: no calculated column for dimension {d!r}")
    names = {mz["name"] for mz in measures.values()}
    for ref in re.findall(r"(?<!')\[([^\]]+)\]", " ".join(mz["dax"] for mz in measures.values())):
        if ref.startswith("# of") and ref not in names:  # measure referenced by another measure, e.g. [# of Flights]
            raise SystemExit(f"measure [{ref}] is referenced but not part of this app")
    used_dims = {d for k in kpi_list(manifest) for d in k["dims"]}
    calc = [x for x in CALC_DIMS if x[2] in used_dims]
    specs = table_specs(catalog_types())
    table_comments, field_comments = comments()
    tables_dir = sm / "definition" / "tables"
    for name, spec in specs.items():
        write_table(tables_dir, name, spec, list(measures.values()) if name == "Main Data" else [],
                    [x for x in calc if x[0] == name], slug=SLUG)
        fname = re.sub(r'[<>:"/\\|?*]', "_", name)
        add_descriptions(tables_dir / f"{fname}.tmdl", name, table_comments, field_comments)
    rels = []
    for ft, fc, tt, tc in relationships():
        rels += [f"relationship {tag(SLUG, 'rel', ft, fc, tt)}", f"\tfromColumn: {tname(ft)}.{tname(fc)}",
                 f"\ttoColumn: {tname(tt)}.{tname(tc)}", ""]
    (sm / "definition" / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")
    (sm / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n", encoding="utf-8")
    refs = "\n".join(f"ref table {tname(t)}" for t in specs)
    order = ["DataRoot", "fnReadParquet", "fnFactKeys", *specs]
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
        "expression fnFactKeys =\n"
        "\t\t// Distinct values of a [Main Data] field: QlikView's Exists() / LEFT KEEP after the fact loads\n"
        "\t\t(column as text) as list =>\n"
        "\t\tlet\n"
        f'\t\t    Flight = fnReadParquet("{FLIGHT}"),\n'
        f'\t\t    Employment = fnReadParquet("{EMPLOYMENT}"),\n'
        "\t\t    FromTable = (t as table) => if Table.HasColumns(t, column) then Table.Column(t, column) else {},\n"
        "\t\t    Values = List.Distinct(FromTable(Flight) & FromTable(Employment))\n"
        "\t\tin\n"
        "\t\t    Values\n"
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
        {"app": APP, "generated_by": "powerbi/tools/build_airline_ch09.py",
         "derived_from": "powerbi/tools/build_airline_base.py (Chapter 15)",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in measures.values()],
         "calculated_dimensions": [{"table": t, "column": c, "parity_key": parity_key(q), "qlik": q, "dax": d}
                                   for t, c, q, d, _ in calc],
         "report_pages": [{"page": p, "qlik_sheet": s, "visuals": [v[1] for v in vs]} for p, s, vs in PAGES],
         "semantic_gaps": GAPS}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(specs)} tables, {len(rels) // 4} relationships, {len(measures)} measures, "
          f"{len(calc)} calculated columns, {len(PAGES)} report pages")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=base.DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
