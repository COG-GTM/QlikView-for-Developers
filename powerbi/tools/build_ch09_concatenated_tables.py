"""Generate the PBIP of Chapter 09 "Concatenated tables", derived from the Chapter 15 Airline base model.

Its load script concatenates the employment statistics into [Main Data], adds 'Unknown' dimension members
(CONCATENATE ... WHERE NOT Exists), builds [Aircraft Types] with a mapping, a LEFT JOIN and a concatenated 2010
update, and Left Keeps the Access airports, so scaffold_pbip.py cannot generate it. The measures and the calculated
dimension come from build_airline_base.py (same parity keys); build() fails if a KPI with source-side parity has none.
COMMENT TABLES / FIELDS (Data Files/Excel/Comments.xls) become TMDL descriptions.

    python powerbi/tools/build_ch09_concatenated_tables.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_airline_base import CALC_DIMS, DEFAULT_ROOT, MEASURES, catalog_types, m_let, m_list, m_types  # noqa: E402

from scaffold_pbip import APPS, POWERBI, TYPE_MAP, show, tag, tname  # noqa: E402

sys.path.insert(0, str(POWERBI / "parity"))
from harness import kpi_list, parity_key  # noqa: E402

APP = "Chapter09__Solution_Chapter 9_Concatenated tables"
SLUG = "Chapter09_Concatenated_tables"
QVDS, CSVS, MDB = "Data Files/QVDs/", "Data Files/CSVs/", "Data Files/MDBs/Dimension Tables/"
FLIGHT = QVDS + "Flight Data.parquet"
EMPLOYMENT = QVDS + "T_F41SCHEDULE_P1A_EMP.parquet"
COMMENTS = POWERBI / "data" / "parquet" / "Data Files" / "Excel" / "Comments"

FLIGHT_COLS = [
    "%Airline ID", "%Carrier Group ID", "%Unique Carrier Code", "%Unique Carrier Entity Code", "%Region Code",
    "%Origin Airport ID", "%Origin Airport Sequence ID", "%Origin Airport Market ID", "%Origin World Area Code",
    "%Destination Airport ID", "%Destination Airport Sequence ID", "%Destination Airport Market ID",
    "%Destination World Area Code", "%Aircraft Group ID", "%Aircraft Type ID", "%Aircraft Configuration ID",
    "%Distance Group ID", "%Service Class ID", "%Datasource ID", "# Departures Scheduled", "# Departures Performed",
    "# Payload", "Distance", "# Available Seats", "# Transported Passengers", "# Transported Freight",
    "# Transported Mail", "# Ramp-To-Ramp Time", "# Air Time", "Unique Carrier", "Carrier Code", "Carrier Name",
    "Origin Airport Code", "Origin City", "Origin State Code", "Origin State FIPS", "Origin State",
    "Origin Country Code", "Origin Country", "Destination Airport Code", "Destination City", "Destination State Code",
    "Destination State FIPS", "Destination State", "Destination Country Code", "Destination Country", "Year", "Period",
    "Quarter", "Month (#)", "Month", "Month__num", "From - To Airport Code", "From - To Airport ID", "From - To City",
    "From - To State Code", "From - To State",
]
EMPLOYMENT_COLS = [
    "%Airline ID", "%Unique Carrier Code", "%Carrier Group ID", "# Full Time Employees", "# Part Time Employees",
    "# Total Employees", "# Equivalent FTEs", "Unique Carrier", "Carrier Code", "Carrier Name", "Year", "Period",
    "Month (#)", "Month", "Month__num",
]

# (table, parquet, key, labels, 'Unknown' members for missing keys)
DIMENSIONS = [
    ("Carrier Groups", QVDS + "Carrier Groups.parquet", "%Carrier Group ID", ["Carrier Group"], True),
    ("Airlines", QVDS + "Airlines.parquet", "%Airline ID", ["Airline"], False),
    ("Carrier Operating Region", QVDS + "Carrier Operating Region.parquet", "%Region Code",
     ["Carrier's Operating Region"], True),
    ("Flight Types", QVDS + "Flight Types.parquet", "%Datasource ID", ["Flight Type"], False),
    ("Distance Groups", QVDS + "Distance Groups.parquet", "%Distance Group ID", ["Distance Interval"], False),
    ("Origin Airports", MDB + "Origin Airports.parquet", "%Origin Airport ID", ["Origin Airport"], False),
    ("Destination Airports", MDB + "Destination Airports.parquet", "%Destination Airport ID",
     ["Destination Airport"], False),
    ("Origin Markets", CSVS + "Origin Markets.parquet", "%Origin Airport Market ID", ["Origin Market"], True),
    ("Destination Markets", CSVS + "Destination Markets.parquet", "%Destination Airport Market ID",
     ["Destination Market"], True),
]
AIRCRAFT_KEY = "%Aircraft Type ID"
AIRCRAFT_COLS = [
    (AIRCRAFT_KEY, "int64"), ("Aircraft Name", "string"), ("Aircraft Manufacturer", "string"),
    ("Aircraft Manufacturer Country", "string"), ("Aircraft Name Full", "string"),
    ("Aircraft Name Abbreviated", "string"), ("Aircraft Begin Date", "date"), ("Aircraft End Date", "int64"),
    ("Aircraft Age Classification", "string"), ("Aircraft Engine Type", "string"),
    ("Aircraft Number Of Engines", "string"),
]
KEYS = [k for _, _, k, _, _ in DIMENSIONS] + [AIRCRAFT_KEY]

GAPS = [
    "$(Include=config.qvs) / $(Include=tracerowcount.qvs) are not in the repo: vFolderSourceData is the repo's "
    "Data Files folder (DataRoot parameter + relative Parquet paths); the row-count trace has no Power BI counterpart.",
    "QVD, CSV and Access (Dimension Tables.mdb, OLEDB CONNECT32) sources -> Parquet converted by tools/convert_sources.py.",
    "STORE [Aircraft Types] INTO Aircraft Types Transformed.qvd is a file side effect of the reload; the model has no "
    "equivalent (Power Query does not write files) and nothing in this document reads it back.",
    "WHERE Exists(key) and Left Keep ([Main Data]) -> rows kept when their key is in [Main Data] (fnFactKeys, the distinct "
    "values of both concatenated fact sources).",
    "Null-key 'Unknown' members the script adds for null fact keys (the Employment rows have no region or market: "
    "Carrier Operating Region 8 and Origin / Destination Markets 1,860 / 1,918 rows in QlikView) are not loaded: they "
    "associate with nothing in QlikView and would wrongly match blank keys in Power BI.",
    "COMMENT TABLES / FIELDS USING the Comments.xls maps -> TMDL descriptions on the table and on every column of the "
    "commented field (a Qlik field comment applies to the field in every table).",
    "Synthetic keys / $$SysTables: none in the model; every dimension relates to [Main Data] on its single key.",
    "Month is a dual -> Month text sorted by the hidden Month__num column.",
    "Drill-down group Time (Year > Month) and cyclic group Airline / Origin Country / Destination Country: report-level "
    "choices in Power BI (visual drill / field parameters); the parity grains cover each level.",
    "The row-level Flight Type deal status (Funnel Chart) -> calculated column on Flight Types.",
]


def let(steps: list[str], last: str) -> str:
    """m_let with `// comment` items written on their own line above the next step."""
    merged, pending = [], []
    for s in steps:
        if s.startswith("//"):
            pending.append(s)
        else:
            merged.append("\n\t\t\t\t    ".join([*pending, s]))
            pending = []
    return m_let(merged, last)


def comments() -> tuple[dict[str, str], dict[str, str]]:
    tables = pd.read_parquet(COMMENTS / "Tables.parquet")
    fields = pd.read_parquet(COMMENTS / "Fields.parquet")
    return dict(zip(tables["TableName"], tables["Comment"])), dict(zip(fields["FieldName"], fields["Comment"]))


def table_specs(types: dict) -> dict[str, dict]:
    specs = {}
    emp_only = [x for x in EMPLOYMENT_COLS if x not in FLIGHT_COLS]
    md_cols = [(x, types[FLIGHT][x]) for x in FLIGHT_COLS] + [(x, types[EMPLOYMENT][x]) for x in emp_only]
    specs["Main Data"] = {"cols": md_cols, "m": let([
        f'Flight = Table.SelectColumns(fnReadParquet("{FLIGHT}"), {m_list(FLIGHT_COLS)})',
        f'Employment = Table.SelectColumns(fnReadParquet("{EMPLOYMENT}"), {m_list(EMPLOYMENT_COLS)})',
        "// 'Q' & Ceil([Month (#)]/3, 1) as Quarter",
        'EmploymentQ = Table.AddColumn(Employment, "Quarter", each if [#"Month (#)"] = null then "Q" '
        'else "Q" & Text.From(Number.RoundUp([#"Month (#)"] / 3)), type text)',
        "Combined = Table.Combine({Flight, EmploymentQ})",
        f"Typed = Table.TransformColumnTypes(Combined, {m_types(md_cols)})"], "Typed")}
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
    base_names = [n for n, _ in AIRCRAFT_COLS[:9]]
    common = ('#"Aircraft Name" = [SSD_NAME], #"Aircraft Manufacturer" = [MANUFACTURER], '
              '#"Aircraft Manufacturer Country" = Country([MANUFACTURER]), #"Aircraft Name Full" = [LONG_NAME], '
              '#"Aircraft Name Abbreviated" = [SHORT_NAME], #"Aircraft Begin Date" = [BEGIN_DATE], '
              '#"Aircraft End Date" = [END_DATE]')
    specs["Aircraft Types"] = {"cols": AIRCRAFT_COLS, "m": let([
        "// MAPPING LOAD Company, Country (Aircraft_Manufacturers.csv); ApplyMap(..., MANUFACTURER, 'Unknown')",
        f'Manufacturers = fnReadParquet("{CSVS}Aircraft_Manufacturers.parquet")',
        'CountryMap = Record.FromList(Table.Column(Manufacturers, "Country"), Table.Column(Manufacturers, "Company"))',
        'Country = (name) => if name = null then "Unknown" else Record.FieldOrDefault(CountryMap, name, "Unknown")',
        f'TypeKeys = List.Buffer(List.RemoveNulls(fnFactKeys("{AIRCRAFT_KEY}")))',
        f'Base = Table.SelectRows(fnReadParquet("{CSVS}Aircraft_Base_File.parquet"), '
        'each List.Contains(TypeKeys, [AC_TYPEID]))',
        'BaseRows = Table.FromRecords(Table.TransformRows(Base, each [#"%Aircraft Type ID" = [AC_TYPEID], '
        f'#"%Aircraft Group Type" = [AC_GROUP], {common}, #"Aircraft Age Classification" = '
        'if [BEGIN_DATE] <> null and Date.Year([BEGIN_DATE]) < 1990 then "Classic" else "Current"]), '
        f'{m_list(["%Aircraft Group Type", *base_names])})',
        "// LEFT JOIN Aircraft_Group.csv on [Aircraft Group ID] as [%Aircraft Group Type]",
        f'Groups = Table.RenameColumns(Table.SelectColumns(fnReadParquet("{CSVS}Aircraft_Group.parquet"), '
        '{"Aircraft Group ID", "Aircraft Engine Type", "Aircraft Number Of Engines"}), '
        '{{"Aircraft Group ID", "%Aircraft Group Type"}})',
        'Joined = Table.NestedJoin(BaseRows, {"%Aircraft Group Type"}, Groups, {"%Aircraft Group Type"}, "Group", '
        "JoinKind.LeftOuter)",
        'Expanded = Table.ExpandTableColumn(Joined, "Group", {"Aircraft Engine Type", "Aircraft Number Of Engines"})',
        'Dropped = Table.RemoveColumns(Expanded, {"%Aircraft Group Type"})',
        "// CONCATENATE Aircraft_2010_Update.csv: SubField(AC_GROUPNAME, ', ', 1 | 2), 'Current'",
        f'Update = Table.SelectRows(fnReadParquet("{CSVS}Aircraft_2010_Update.parquet"), '
        'each List.Contains(TypeKeys, [AC_TYPEID]))',
        'SubField = (s, n) => let parts = if s = null then {} else Text.Split(s, ", ") in '
        "if List.Count(parts) >= n then parts{n - 1} else null",
        'UpdateRows = Table.FromRecords(Table.TransformRows(Update, each [#"%Aircraft Type ID" = [AC_TYPEID], '
        '#"Aircraft Engine Type" = SubField([AC_GROUPNAME], 1), #"Aircraft Number Of Engines" = '
        f'SubField([AC_GROUPNAME], 2), {common}, #"Aircraft Age Classification" = "Current"]), '
        f'{m_list([*base_names, "Aircraft Engine Type", "Aircraft Number Of Engines"])})',
        "Combined = Table.Combine({Dropped, UpdateRows})",
        f"Selected = Table.SelectColumns(Combined, {m_list(n for n, _ in AIRCRAFT_COLS)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(AIRCRAFT_COLS)})"], "Typed")}
    return specs


def description(text: str, indent: str) -> list[str]:
    return [f"{indent}/// {line}" for line in str(text).splitlines()]


def write_table(path: Path, name: str, spec: dict, measures: list[dict], calc: list[tuple],
                table_comments: dict, field_comments: dict):
    names = {n for n, _ in spec["cols"]}
    lines = description(table_comments[name], "") if name in table_comments else []
    lines += [f"table {tname(name)}", f"\tlineageTag: {tag(SLUG, name)}", ""]
    for mz in measures:
        lines += [f"\tmeasure {tname(mz['name'])} = {mz['dax']}"]
        if mz["fmt"]:
            lines.append(f"\t\tformatString: {mz['fmt']}")
        lines += [f"\t\tlineageTag: {tag(SLUG, name, 'm', mz['parity_key'])}", "",
                  f"\t\tannotation ParityKey = {mz['parity_key']}", f"\t\tannotation QlikExpression = {mz['qlik']}",
                  f"\t\tannotation QlikObjects = {', '.join(mz['kpis'])}", ""]
    for col, typ in spec["cols"]:
        dtype, _, fmt = TYPE_MAP[typ]
        if col in field_comments:
            lines += description(field_comments[col], "\t")
        lines += [f"\tcolumn {tname(col)}", f"\t\tdataType: {dtype}"]
        if col.startswith("%") or col.endswith("__num"):
            lines.append("\t\tisHidden")
        if f"{col}__num" in names:
            lines.append(f"\t\tsortByColumn: {tname(col + '__num')}")
        if fmt and col not in ("Period", "Year", "Month (#)"):
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


def relationships() -> list[tuple[str, str, str, str]]:
    return [("Main Data", key, name, key) for name, _, key, _, _ in DIMENSIONS] + \
        [("Main Data", AIRCRAFT_KEY, "Aircraft Types", AIRCRAFT_KEY)]


def build(data_root: str = DEFAULT_ROOT) -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = APPS / SLUG
    sm, rp = root / f"{SLUG}.SemanticModel", root / f"{SLUG}.Report"
    for d in (sm / "definition" / "tables", rp):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.tmdl"):
            f.unlink()
    measures: dict[str, dict] = {}
    calc_qlik = {x[2] for x in CALC_DIMS}
    used_calc = set()
    for k in kpi_list(manifest):
        pk = k["parity_key"]
        if pk not in MEASURES:
            raise SystemExit(f"{k['kpi']}: no measure for ParityKey {pk}: {k['expression']}")
        mz = measures.setdefault(pk, {"parity_key": pk, "name": MEASURES[pk][0], "dax": MEASURES[pk][1],
                                      "fmt": MEASURES[pk][2], "kpis": [], "qlik": " ".join(k["expression"].split())})
        mz["kpis"].append(k["kpi"])
        for d in k["dims"]:
            if d.startswith("="):
                if d not in calc_qlik:
                    raise SystemExit(f"{k['kpi']}: no calculated column for dimension {d!r}")
                used_calc.add(d)
    names = {mz["name"] for mz in measures.values()}
    for mz in measures.values():
        for ref in re.findall(r"(?<!')\[([^\]]+)\]", mz["dax"]):
            if ref not in names and not ref.startswith("@") and f"'Main Data'[{ref}]" not in mz["dax"]:
                raise SystemExit(f"{mz['name']}: references measure [{ref}] that this model does not have")
    calc = [x for x in CALC_DIMS if x[2] in used_calc]
    table_comments, field_comments = comments()
    specs = table_specs(catalog_types())
    for name, spec in specs.items():
        write_table(sm / "definition" / "tables", name, spec,
                    list(measures.values()) if name == "Main Data" else [],
                    [x for x in calc if x[0] == name], table_comments, field_comments)
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
        "\t\t// Distinct values of a [Main Data] field: QlikView's Exists() after the fact loads\n"
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
    (rp / "report.json").write_text(json.dumps({
        "config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
        "layoutOptimization": 0, "resourcePackages": [],
        "sections": [{"name": "ReportSection", "displayName": "Page 1", "displayOption": 1, "ordinal": 0,
                      "width": 1280, "height": 720, "config": "{}", "filters": "[]", "visualContainers": []}]},
        indent=2) + "\n")
    (root / f"{SLUG}.pbip").write_text(json.dumps(
        {"version": "1.0", "artifacts": [{"report": {"path": f"{SLUG}.Report"}}], "settings": {"enableAutoRecovery": True}},
        indent=2) + "\n")
    (root / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    (root / "model.json").write_text(json.dumps(
        {"app": APP, "generated_by": "powerbi/tools/build_ch09_concatenated_tables.py",
         "derived_from": "powerbi/tools/build_airline_base.py",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in measures.values()],
         "calculated_dimensions": [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q, "dax": d}
                                   for t, col, q, d, _ in calc],
         "semantic_gaps": GAPS}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(specs)} tables, {len(rels) // 4} relationships, {len(measures)} measures, "
          f"{len(calc)} calculated columns")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
