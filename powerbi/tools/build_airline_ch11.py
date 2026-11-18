"""Generate the Chapter 11 Airline Operations PBIP, derived from the Chapter 15 base model (build_airline_base.py).

Chapter 11 is the earlier version of the same app: every one of its chart expressions is also in Chapter 15, so the
measures, the Aggr()/Class() segment tables and the Deal Status column are the base model's. What differs is the
load script, which this script follows instead of Chapter 15's:
  - sources from the original layout: Flight Data / T_F41SCHEDULE_P1A_EMP / dimension QVDs, airports from the Access
    database (LEFT KEEP), markets from CSVs;
  - Aircraft Types is built from Aircraft_Base_File.csv + Aircraft_Group.csv (LEFT JOIN) + Aircraft_2010_Update.csv
    with the Map_Manufacturer_Country ApplyMap (Chapter 15 reads the QVD this tab stores);
  - COMMENT TABLES / FIELDS from Comments.xls -> TMDL descriptions;
  - the metric picker inline table is INLFED; no Section Access, alternate states or SetVariables.txt.

    python powerbi/tools/build_airline_ch11.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_airline_base as base  # noqa: E402
from build_airline_base import (  # noqa: E402
    CALC_DIMS,
    DEFAULT_ROOT,
    FLIGHT_COLS,
    METRICS,
    PCT,
    SEGMENTS,
    catalog_types,
    kpi_list,
    m,
    m_let,
    m_list,
    m_types,
    parity_key,
    total_dax,
    write_table,
)

from scaffold_pbip import APPS, POWERBI, show, tag, tname  # noqa: E402

APP = "Chapter11__Solution_Chapter 11_Airline Operations"
SLUG = "Chapter11_Airline_Operations"
QVDS, MDB, CSVS = "Data Files/QVDs/", "Data Files/MDBs/Dimension Tables/", "Data Files/CSVs/"
FLIGHT = QVDS + "Flight Data.parquet"
EMPLOYMENT = QVDS + "T_F41SCHEDULE_P1A_EMP.parquet"
EMPLOYMENT_COLS = ["%Airline ID", "%Unique Carrier Code", "%Carrier Group ID", "# Full Time Employees",
                   "# Part Time Employees", "# Total Employees", "# Equivalent FTEs", "Unique Carrier", "Carrier Code",
                   "Carrier Name", "Period"]
AIRCRAFT_TYPES = QVDS + "Aircraft Types Transformed.parquet"  # what the Aircrafts tab STOREs: column types only
AIRCRAFT_COLS = ["Aircraft Name", "Aircraft Manufacturer", "Aircraft Manufacturer Country", "Aircraft Name Full",
                 "Aircraft Name Abbreviated", "Aircraft Begin Date", "Aircraft End Date", "Aircraft Age Classification",
                 "Aircraft Engine Type", "Aircraft Number Of Engines"]
COMMENTS = "Data Files/Excel/Comments/"
# CH43 divides by $(vTotalFTEs), defined '= Sum([# Equivalent FTEs])': a '=' variable is evaluated once in the current
# selection before expansion, so it is the selection-wide total (Sum(TOTAL ...)), not the per-row Sum the base
# model's measure (inventory expansion without the '=') repeats. The manifest's expansion is corrected to TOTAL.
_FTE = f"SUM({m('# Equivalent FTEs')})"
CH11_MEASURES = {
    parity_key("Sum([# Equivalent FTEs]) / Sum(TOTAL [# Equivalent FTEs])"):
        ("FTE % to Total", f"DIVIDE({_FTE}, {total_dax(_FTE, [])})", PCT),
}
METRIC_TABLE = "INLFED"

# (table, parquet, key, label columns, add 'Unknown' members for fact keys missing from the dimension)
DIMENSIONS = [
    ("Carrier Groups", QVDS + "Carrier Groups.parquet", "%Carrier Group ID", ["Carrier Group"], True),
    ("Airlines", QVDS + "Airlines.parquet", "%Airline ID", ["Airline"], False),
    ("Carrier Operating Region", QVDS + "Carrier Operating Region.parquet", "%Region Code",
     ["Carrier's Operating Region"], True),
    ("Flight Types", QVDS + "Flight Types.parquet", "%Datasource ID", ["Flight Type"], False),
    ("Aircraft Types", AIRCRAFT_TYPES, "%Aircraft Type ID", AIRCRAFT_COLS, False),
    ("Distance Groups", QVDS + "Distance Groups.parquet", "%Distance Group ID", ["Distance Interval"], False),
    ("Origin Airports", MDB + "Origin Airports.parquet", "%Origin Airport ID", ["Origin Airport"], False),
    ("Destination Airports", MDB + "Destination Airports.parquet", "%Destination Airport ID",
     ["Destination Airport"], False),
    ("Origin Markets", CSVS + "Origin Markets.parquet", "%Origin Airport Market ID", ["Origin Market"], True),
    ("Destination Markets", CSVS + "Destination Markets.parquet", "%Destination Airport Market ID",
     ["Destination Market"], True),
]

GAPS = [
    "Derived from the Chapter 15 base model: Chapter 11's 66 chart expressions are 26 distinct Qlik expressions, all of "
    "which the base model already migrates, so the measures, segment tables and calculated column are shared (the metric "
    "picker reads INLFED, Chapter 11's name for that inline table).",
    "FTE % to Total (CH43): $(vTotalFTEs) is '= Sum([# Equivalent FTEs])', evaluated once in the selection, so the "
    "denominator is the selection-wide total -> CALCULATE(..., ALLSELECTED()); the inventory expansion had dropped the "
    "'=' (each carrier divided by itself) and is corrected to Sum(TOTAL ...) in the manifest.",
    "No Section Access in Chapter 11: no roles; Main Data keeps the Employment rows and Carrier Groups / Airlines / "
    "Carrier Operating Region / Markets keep every member the script loads (inventory: Main Data 1,258,763, Airlines 337).",
    "Aircraft Types: Aircraft_Base_File.csv WHERE Exists, LEFT JOIN Aircraft_Group.csv on the group, then CONCATENATE "
    "Aircraft_2010_Update.csv (engine type / count from SubField(AC_GROUPNAME, ', ')) -> Power Query merges; ApplyMap "
    "Map_Manufacturer_Country -> left merge on Aircraft_Manufacturers.csv with 'Unknown' default. The STORE into "
    "Aircraft Types Transformed.qvd is an ETL side effect and is not reproduced.",
    "Origin / Destination Airports: LEFT KEEP ([Main Data]) over the Access tables -> keep rows whose key is in Main Data "
    "(read from the Access tables' Parquet export).",
    "COMMENT TABLES / FIELDS USING Comments.xls -> TMDL descriptions on Aircraft Types and its fields (and Main Data's "
    "%Aircraft Type ID, as Qlik comments the field wherever it appears).",
    "Master Calendar: one row per month (36), as in QlikView (Chapter 11 has no preceding Load * keeping daily rows); "
    "Month and Year - Month are Qlik duals -> text columns sorted by hidden __num columns.",
    "Null-key 'Unknown' members the script adds for null fact keys are not loaded: they associate with nothing in "
    "QlikView and would wrongly match blank keys in Power BI.",
    "IF $(vLoadMainData) = 'Y': always loaded. Includes config.qvs / tracerowcount.qvs (paths, TraceRowCount logging) "
    "are not in the repo; paths resolve by repo layout and the row-count trace is dropped.",
    "Set analysis value modifiers use KEEPFILTERS: identical to QlikView with no selections (the parity baseline); with a "
    "slicer selection on the same field Power BI intersects where QlikView replaces the selection.",
    "Calculated dimensions: the Aggr()/Class() carrier buckets -> disconnected segment tables; '# of Carriers' counts the "
    "carriers whose value falls in the segment at query time. The row-level Flight Type deal status -> calculated column.",
    "Dimensionality()/Pick(Dimensionality()+1, ...) -> ISINSCOPE() over the chart's dimension fields; "
    "$($(=eMetric)) -> SWITCH over SELECTEDVALUE(INLFED[eMetric]).",
    "Report: one page per QlikView sheet with every chart of the sheet (base report_sections). List boxes -> slicers "
    "on the field their caption names, each field synced on every page (hidden where the sheet had no list box for it). "
    "MB01/MB02 multi boxes and LB10 'Aircraft Type' / LB11 'Aircraft Group' name no field of the model (Chapter 11 "
    "drops %Aircraft Group Type) and are not rebuilt. CH02 keeps its Top 10 (by # of Flights, descending). Current "
    "selections, buttons, bookmarks, input box, slider, search object, statistics box and table boxes map to Power BI's "
    "filter pane / bookmarks and are not generated.",
]



def measures_for_ch11() -> dict[str, tuple]:
    """The base model's measures for the parity keys Chapter 11 uses."""
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    keys = {k["parity_key"] for k in kpi_list(manifest)}
    out = {}
    for pk in keys:
        if pk in CH11_MEASURES:
            out[pk] = CH11_MEASURES[pk]
            continue
        if pk not in base.MEASURES:
            raise SystemExit(f"ParityKey {pk} has no measure in the base model")
        name, dax, fmt = base.MEASURES[pk]
        out[pk] = (name, dax.replace("'INLFED-1'", METRIC_TABLE), fmt)
    return out


def comments(data_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    tables = pd.read_parquet(data_root / COMMENTS / "Tables.parquet")
    fields = pd.read_parquet(data_root / COMMENTS / "Fields.parquet")
    return dict(zip(tables["TableName"], tables["Comment"])), dict(zip(fields["FieldName"], fields["Comment"]))


def aircraft_m(types: dict) -> str:
    cols = [("%Aircraft Type ID", types[AIRCRAFT_TYPES]["%Aircraft Type ID"])] + \
        [(x, types[AIRCRAFT_TYPES][x]) for x in AIRCRAFT_COLS]
    renames = {"AC_TYPEID": "%Aircraft Type ID", "SSD_NAME": "Aircraft Name", "MANUFACTURER": "Aircraft Manufacturer",
               "LONG_NAME": "Aircraft Name Full", "SHORT_NAME": "Aircraft Name Abbreviated",
               "BEGIN_DATE": "Aircraft Begin Date", "END_DATE": "Aircraft End Date"}
    rename_list = "{" + ", ".join(f'{{"{a}", "{b}"}}' for a, b in renames.items()) + "}"
    return m_let([
        'FactKeys = List.Buffer(List.RemoveNulls(fnFactKeys("%Aircraft Type ID")))',
        f'Base = Table.SelectRows(fnReadParquet("{CSVS}Aircraft_Base_File.parquet"), each List.Contains(FactKeys, [AC_TYPEID]))',
        # Qlik trims leading / trailing spaces of text-file fields (Aircraft_Group.csv has ' 4-Engine')
        f'Groups = Table.TransformColumns(fnReadParquet("{CSVS}Aircraft_Group.parquet"), '
        '{{"Aircraft Engine Type", each if _ = null then null else Text.Trim(_, " ")}, '
        '{"Aircraft Number Of Engines", each if _ = null then null else Text.Trim(_, " ")}})',
        'Joined = Table.NestedJoin(Base, {"AC_GROUP"}, Groups, {"Aircraft Group ID"}, "Group", JoinKind.LeftOuter)',
        'WithEngines = Table.ExpandTableColumn(Joined, "Group", {"Aircraft Engine Type", "Aircraft Number Of Engines"})',
        'BaseAged = Table.AddColumn(WithEngines, "Aircraft Age Classification", each '
        'if [BEGIN_DATE] <> null and Date.Year([BEGIN_DATE]) < 1990 then "Classic" else "Current")',
        f'Update = Table.SelectRows(fnReadParquet("{CSVS}Aircraft_2010_Update.parquet"), '
        'each List.Contains(FactKeys, [AC_TYPEID]))',
        'UpdateEngine = Table.AddColumn(Update, "Aircraft Engine Type", each '
        'if [AC_GROUPNAME] = null then null else Text.Split([AC_GROUPNAME], ", "){0}?)',
        'UpdateEngines = Table.AddColumn(UpdateEngine, "Aircraft Number Of Engines", each '
        'if [AC_GROUPNAME] = null then null else Text.Split([AC_GROUPNAME], ", "){1}?)',
        'UpdateAged = Table.AddColumn(UpdateEngines, "Aircraft Age Classification", each "Current")',
        'Combined = Table.Combine({BaseAged, UpdateAged})',
        f'Manufacturers = Table.Distinct(fnReadParquet("{CSVS}Aircraft_Manufacturers.parquet"), {{"Company"}})',
        'Mapped = Table.NestedJoin(Combined, {"MANUFACTURER"}, Manufacturers, {"Company"}, "Map", JoinKind.LeftOuter)',
        'WithCountry = Table.ExpandTableColumn(Mapped, "Map", {"Country"})',
        'Country = Table.AddColumn(WithCountry, "Aircraft Manufacturer Country", each '
        'if [Country] = null then "Unknown" else [Country])',
        f"Renamed = Table.RenameColumns(Country, {rename_list})",
        f"Selected = Table.SelectColumns(Renamed, {m_list(n for n, _ in cols)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(cols)})"], "Typed")


def table_specs(types: dict, table_comments: dict, field_comments: dict) -> dict[str, dict]:
    specs = {}
    emp_only = [x for x in EMPLOYMENT_COLS if x not in FLIGHT_COLS]
    md_cols = [(x, types[FLIGHT][x]) for x in FLIGHT_COLS] + [(x, types[EMPLOYMENT][x]) for x in emp_only]
    specs["Main Data"] = {"cols": md_cols, "m": m_let([
        f'Flight = Table.SelectColumns(fnReadParquet("{FLIGHT}"), {m_list(FLIGHT_COLS)})',
        f'Employment = Table.SelectColumns(fnReadParquet("{EMPLOYMENT}"), {m_list(EMPLOYMENT_COLS)})',
        "Combined = Table.Combine({Flight, Employment})",
        f"Typed = Table.TransformColumnTypes(Combined, {m_types(md_cols)})"], "Typed")}
    cal_cols = [("Period", "int64"), ("Year", "int64"), ("Month", "string"), ("Month__num", "float64"),
                ("Year - Month", "string"), ("Year - Month__num", "float64"), ("Quarter", "string")]
    specs["Master Calendar"] = {"cols": cal_cols, "m": m_let([
        'Periods = List.RemoveNulls(fnFactKeys("Period"))',
        "MinDate = #date(Number.IntegerDivide(List.Min(Periods), 100), Number.Mod(List.Min(Periods), 100), 1)",
        "MaxDate = #date(Number.IntegerDivide(List.Max(Periods), 100), Number.Mod(List.Max(Periods), 100), 1)",
        "Months = List.Generate(() => MinDate, each _ <= MaxDate, each Date.AddMonths(_, 1))",
        'Base = Table.FromList(Months, Splitter.SplitByNothing(), {"MonthStart"})',
        'Cols = Table.AddColumn(Base, "Fields", each [Period = Date.Year([MonthStart]) * 100 + Date.Month([MonthStart]), '
        'Year = Date.Year([MonthStart]), Month = Date.ToText([MonthStart], "MMM", "en-US"), '
        'Month__num = Date.Month([MonthStart]), '
        '#"Year - Month" = Date.ToText([MonthStart], "yyyy-MM", "en-US"), #"Year - Month__num" = Number.From([MonthStart]), '
        'Quarter = "Q" & Text.From(Number.RoundUp(Date.Month([MonthStart]) / 3))])',
        f"Expanded = Table.ExpandRecordColumn(Cols, \"Fields\", {m_list(n for n, _ in cal_cols)})",
        f"Typed = Table.TransformColumnTypes(Expanded, {m_types(cal_cols)})"], "Typed")}
    for name, path, key, labels, unknown in DIMENSIONS:
        cols = [(key, types[path][key])] + [(x, types[path][x]) for x in labels]
        if name == "Aircraft Types":
            specs[name] = {"cols": cols, "m": aircraft_m(types)}
            continue
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
    specs[METRIC_TABLE] = {"cols": [("Metric Name", "string"), ("eMetric", "string")], "m": m_let([
        "Source = #table(type table [#\"Metric Name\" = text, eMetric = text], {"
        + ", ".join(f'{{"{a}", "{b}"}}' for a, b in METRICS) + "})"], "Source")}
    for table, col, qlik, values, label, _ in SEGMENTS:
        if label:
            specs[table] = {"cols": [(col, "string"), ("Low", "int64")], "sort": {col: "Low"}, "qlik": {col: qlik},
                            "m": m_let([f'Source = Table.FromList({values}, Splitter.SplitByNothing(), {{"Low"}})',
                                        f'Labeled = Table.AddColumn(Source, "{col}", each {label})',
                                        'Typed = Table.TransformColumnTypes(Labeled, '
                                        f'{{{{"{col}", type text}}, {{"Low", Int64.Type}}}})'],
                                       "Typed")}
        else:
            specs[table] = {"cols": [(col, "int64")], "qlik": {col: qlik},
                            "m": m_let([f'Source = Table.FromList({values}, Splitter.SplitByNothing(), {{"{col}"}})',
                                        f'Typed = Table.TransformColumnTypes(Source, {{{{"{col}", Int64.Type}}}})'], "Typed")}
    for name, spec in specs.items():  # COMMENT TABLES / COMMENT FIELDS: Qlik comments a field in every table holding it
        if name in table_comments:
            spec["description"] = table_comments[name]
        spec["descriptions"] = {col: field_comments[col] for col, _ in spec["cols"] if col in field_comments}
    return specs


def relationships() -> list[tuple[str, str, str, str]]:
    rels = [("Main Data", key, name, key) for name, _, key, _, _ in DIMENSIONS]
    rels.append(("Main Data", "Period", "Master Calendar", "Period"))
    return rels


def with_synced_slicers(sections: list[dict]) -> None:
    """QlikView selections are global: every list-box field gets a slicer on every page, in one sync group (hidden
    where the sheet had no list box for it), so a selection on any page filters every page's charts."""
    slicers = {}
    for sec in sections:
        for vc in sec["visualContainers"]:
            cfg = json.loads(vc["config"])
            if cfg["singleVisual"]["visualType"] == "slicer":
                slicers.setdefault(cfg["singleVisual"]["syncGroup"]["groupName"], cfg)
    for sec in sections:
        shown = {json.loads(vc["config"])["singleVisual"].get("syncGroup", {}).get("groupName")
                 for vc in sec["visualContainers"]}
        sheet = json.loads(sec["config"])["QlikSheet"]
        for group, cfg in slicers.items():
            if group in shown:
                continue
            pos = {"x": 0, "y": 0, "z": len(sec["visualContainers"]), "width": 120, "height": 60}
            hidden = {**cfg, "name": tag(SLUG, "sync", sheet, group), "layouts": [{"id": 0, "position": pos}],
                      "singleVisual": {**cfg["singleVisual"], "display": {"mode": "hidden"}}}
            sec["visualContainers"].append({**pos, "config": json.dumps(hidden), "filters": "[]"})


def build(data_root: str = DEFAULT_ROOT, parquet: Path = POWERBI / "data" / "parquet") -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = APPS / SLUG
    sm, rp = root / f"{SLUG}.SemanticModel", root / f"{SLUG}.Report"
    for d in (sm / "definition" / "tables", rp):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.tmdl"):
            f.unlink()
    defs = measures_for_ch11()
    measures: dict[str, dict] = {}
    for k in kpi_list(manifest):
        pk = k["parity_key"]
        mz = measures.setdefault(pk, {"parity_key": pk, "name": defs[pk][0], "dax": defs[pk][1], "fmt": defs[pk][2],
                                      "kpis": [], "qlik": " ".join(k["expression"].split())})
        mz["kpis"].append(k["kpi"])
        for d in k["dims"]:
            if d.startswith("=") and d not in {x[2] for x in CALC_DIMS} | {x[2] for x in SEGMENTS}:
                raise SystemExit(f"{k['kpi']}: no calculated column for dimension {d!r}")
    specs = table_specs(catalog_types(), *comments(parquet))
    for name, spec in specs.items():
        write_table(sm / "definition" / "tables", name, spec,
                    list(measures.values()) if name == "Main Data" else [],
                    [x for x in CALC_DIMS if x[0] == name], slug=SLUG)
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
    base.SLUG = SLUG  # report_sections tags pages / visuals with the module's current app slug
    try:
        sections, unmapped = base.report_sections(manifest, specs, measures)
    finally:
        base.SLUG = base.CFG.slug
    with_synced_slicers(sections)
    (rp / "report.json").write_text(json.dumps({
        "config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
        "layoutOptimization": 0, "resourcePackages": [],
        "sections": sections}, indent=2) + "\n")
    (root / f"{SLUG}.pbip").write_text(json.dumps(
        {"version": "1.0", "artifacts": [{"report": {"path": f"{SLUG}.Report"}}], "settings": {"enableAutoRecovery": True}},
        indent=2) + "\n")
    (root / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    (root / "model.json").write_text(json.dumps(
        {"app": APP, "generated_by": "powerbi/tools/build_airline_ch11.py",
         "base_model": "powerbi/tools/build_airline_base.py (Chapter 15)",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in sorted(measures.values(), key=lambda x: x["kpis"][0])],
         "calculated_dimensions": [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q, "dax": d}
                                   for t, col, q, d, _ in CALC_DIMS]
                                  + [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q,
                                      "dax": "segment table + '# of Carriers'"} for t, col, q, _, _, _ in SEGMENTS],
         "report_pages": {s_["displayName"]: len(s_["visualContainers"]) for s_ in sections},
         "unmapped_list_boxes": unmapped,
         "semantic_gaps": GAPS}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(specs)} tables, {len(rels) // 4} relationships, {len(measures)} measures, "
          f"{len(CALC_DIMS)} calculated columns, {len(sections)} report pages")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
