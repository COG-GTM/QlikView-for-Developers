"""Build the Power BI PBIP for Chapter12/Solution_Chapter 12_Airline Operations.qvw from the Chapter 15 base.

Chapter 12 has the same Main Data / calendar / dimension model, metric picker, point-in-time sets, alternate states
and calculated dimensions as Chapter 15 (powerbi/tools/build_airline_base.py), but its own load script:

* sources are the older `Data Files/` QVDs, the Access `Dimension Tables.mdb` airports and the tab-delimited market
  CSVs; Main Data concatenates T_F41SCHEDULE_P1A_EMP.qvd (no headcount deltas, so no HC Change measures);
* Aircraft Types is built in the script from Aircraft_Base_File.csv (ApplyMap of the manufacturer country,
  Left Join of Aircraft_Group.csv) + Concatenate Aircraft_2010_Update.csv, instead of reading the transformed QVD;
* no Section Access: no roles, and the metric picker inline table is `INLFED`.

The base builder's generation code is reused by pointing its module-level configuration at Chapter 12.

Usage: python powerbi/tools/build_airline_ch12.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_airline_base as base  # noqa: E402

APP = "Chapter12__Solution_Chapter 12_Airline Operations"
SLUG = "Chapter12_Airline_Operations"
QVDS = "Data Files/QVDs/"
CSVS = "Data Files/CSVs/"
MDB = "Data Files/MDBs/Dimension Tables/"
SOURCES = {"Carrier Groups": QVDS, "Airlines": QVDS, "Carrier Operating Region": QVDS, "Flight Types": QVDS,
           "Aircraft Types": QVDS, "Distance Groups": QVDS, "Origin Airports": MDB, "Destination Airports": MDB,
           "Origin Markets": CSVS, "Destination Markets": CSVS}
EMPLOYMENT_COLS = ["%Airline ID", "%Unique Carrier Code", "%Carrier Group ID", "# Full Time Employees",
                   "# Part Time Employees", "# Total Employees", "# Equivalent FTEs", "Unique Carrier", "Carrier Code",
                   "Carrier Name", "Period"]
HC_DELTA_MEASURES = {"04c961e41f32", "53f3fabda737", "97885edb520e", "bdf635c244a3", "bebebe28ced0", "d76da9774b00"}
AIRCRAFT_RENAMES = {"AC_TYPEID": "%Aircraft Type ID", "SSD_NAME": "Aircraft Name", "MANUFACTURER": "Aircraft Manufacturer",
                    "LONG_NAME": "Aircraft Name Full", "SHORT_NAME": "Aircraft Name Abbreviated",
                    "BEGIN_DATE": "Aircraft Begin Date", "END_DATE": "Aircraft End Date"}
GAPS = [
    "Aircraft Types: ApplyMap('Map_Manufacturer_Country', MANUFACTURER, 'Unknown') -> left merge with "
    "Aircraft_Manufacturers + 'Unknown' default; LEFT JOIN Aircraft_Group -> left merge on AC_GROUP; the 2010 update's "
    "SubField(AC_GROUPNAME, ', ', n) -> Text.Split. Qlik trims unquoted text-file fields and keeps empty ones as '', "
    "so group texts are trimmed and an empty MANUFACTURER is ''. STORE ... Aircraft Types Transformed.qvd is dropped.",
    "Origin / Destination Airports: OLEDB (Jet) SQL SELECT from Dimension Tables.mdb with LEFT KEEP ([Main Data]) -> "
    "Parquet exported from the .mdb, filtered to the airport keys Main Data uses (LEFT KEEP keeps no other rows).",
    "IF $(vLoadMainData) = 'Y' always loads Main Data (vLoadMainData is 'Y'); the config.qvs / tracerowcount.qvs "
    "includes, TraceRowCount calls and COMMENT FIELDS / TABLES USING Comments.xls are not part of the model.",
    *[g.replace("INLFED-1", "INLFED").replace("so RLS and selections", "so selections")
      for g in base.GAPS if not any(w in g for w in ("Section Access", "OMIT", "each role"))],
]

# Sheets (in .qvw order) and their list boxes as (object id, caption), read from the .qvw's sheet object lists and
# the caption string stored before each list box id. A list box caption is normally its field name.
SHEETS = [
    ("SH03", "Dashboard", ["LB28", "LB32", "LB30", "LB31", "LB27", "LB33", "LB29"]),
    ("SH_Analysis", "Analysis", ["LB29", "LB27", "LB33", "LB28", "LB32", "LB31", "LB30"]),
    ("SH05", "Reports", ["LB32", "LB30", "LB31", "LB29", "LB27", "LB33", "LB28"]),
    ("SH01", "Associations", ["LB04", "LB01", "LB13", "LB07", "LB02", "LB06", "LB05", "LB03", "LB15", "LB10", "LB12",
                              "LB11", "LB09"]),
    ("SH04", "Gauge Styles", []),
    ("SH06", "Other Charts", ["LB30", "LB31", "LB28", "LB33", "LB27", "LB29", "LB32"]),
    ("SH08", "Other representations", ["LB30", "LB31", "LB32", "LB29", "LB27", "LB33", "LB28"]),
    ("SH09", "Data Consistency", ["LB34", "LB35"]),
    ("SH10", "Variables", ["LB31", "LB32", "LB30", "LB36"]),
    ("SH11", "Advanced Expressions", ["LB31", "LB30", "LB32"]),
    ("SH12", "Set Analysis", ["LB32", "LB31", "LB30"]),
    ("SH13", "Point In Time Reporting", ["LB32", "LB31", "LB33", "LB28", "LB27", "LB29", "LB30"]),
    ("SH15", "Comparative Analysis", ["LB30", "LB32", "LB31", "LB37", "LB42", "LB41", "LB40", "LB38", "LB45", "LB44",
                                      "LB43", "LB39"]),
]
LIST_BOXES = {
    "LB27": "Flight Type", "LB28": "Carrier's Operating Region", "LB29": "Carrier Group", "LB30": "Month",
    "LB31": "Quarter", "LB32": "Year", "LB33": "Carrier Name", "LB01": "Destination Country", "LB02": "Destination State",
    "LB03": "Destination City", "LB04": "Origin Country", "LB05": "Origin State", "LB06": "Origin City",
    "LB07": "Carrier Name", "LB09": "Distance Interval", "LB10": "Aircraft Type", "LB11": "Aircraft Group",
    "LB12": "Flight Type", "LB13": "Carrier's Operating Region", "LB15": "Carrier Group", "LB34": "Aircraft Name",
    "LB35": "Year", "LB36": "Metric Name",
    # Comparative Analysis: list boxes in alternate states Group A / Group B, captioned by their position
    "LB37": None, "LB38": "To Country", "LB39": "From Coutry", "LB40": "To State", "LB41": "To City",
    "LB42": "To Airport", "LB43": "From State", "LB44": "From City", "LB45": "From Airport",
}


def slicer(lb: str, table: str, field: str, x: int, y: int, z: int) -> dict:
    ref = f"{table}.{field}"
    config = {"name": f"{SLUG}_{lb}", "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": 200, "height": 160}}],
              "singleVisual": {"visualType": "slicer", "projections": {"Values": [{"queryRef": ref, "active": True}]},
                               "prototypeQuery": {"Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}],
                                                  "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}},
                                                                         "Property": field}, "Name": ref}]},
                               "objects": {"data": [{"properties": {"mode": {"expr": {"Literal": {"Value": "'Basic'"}}}}}]},
                               "vcObjects": {"title": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}},
                                                                       "text": {"expr": {"Literal": {"Value": "'" + field.replace("'", "''") + "'"}}}}}]}}}
    return {"x": x, "y": y, "z": z, "width": 200, "height": 160, "config": json.dumps(config), "filters": "[]"}


def write_report(root: Path, specs: dict) -> list[dict]:
    fields = {}
    for table, spec in specs.items():
        for col, _ in spec["cols"]:
            fields.setdefault(col, table)
    sections, mapped = [], []
    for i, (sid, title, lbs) in enumerate(SHEETS):
        visuals = []
        for lb in lbs:
            field = LIST_BOXES[lb]
            if field in fields:
                n = len(visuals)
                visuals.append(slicer(lb, fields[field], field, 10 + (n % 6) * 210, 10 + (n // 6) * 170, n))
                mapped.append({"sheet": title, "object": lb, "caption": field, "table": fields[field]})
        sections.append({"name": f"ReportSection_{sid}", "displayName": title, "displayOption": 1, "ordinal": i,
                         "width": 1280, "height": 720, "config": "{}", "filters": "[]", "visualContainers": visuals})
    report = root / f"{SLUG}.Report" / "report.json"
    data = json.loads(report.read_text())
    data["sections"] = sections
    report.write_text(json.dumps(data, indent=2) + "\n")
    return mapped


def aircraft_m(cols: list[tuple[str, str]]) -> str:
    trim = "each if _ = null then null else Text.Trim(_)"
    return base.m_let([
        'FactKeys = List.Buffer(List.RemoveNulls(fnFactKeys("%Aircraft Type ID")))',
        f'Manufacturers = fnReadParquet("{CSVS}Aircraft_Manufacturers.parquet")',
        f'Groups = Table.TransformColumns(fnReadParquet("{CSVS}Aircraft_Group.parquet"), '
        f'{{{{"Aircraft Engine Type", {trim}}}, {{"Aircraft Number Of Engines", {trim}}}}})',
        f'Base = Table.SelectRows(fnReadParquet("{CSVS}Aircraft_Base_File.parquet"), each List.Contains(FactKeys, [AC_TYPEID]))',
        'BaseAge = Table.AddColumn(Base, "Aircraft Age Classification", '
        'each if [BEGIN_DATE] <> null and Date.Year([BEGIN_DATE]) < 1990 then "Classic" else "Current")',
        'BaseGroups = Table.NestedJoin(BaseAge, {"AC_GROUP"}, Groups, {"Aircraft Group ID"}, "Group", JoinKind.LeftOuter)',
        'BaseOut = Table.ExpandTableColumn(BaseGroups, "Group", {"Aircraft Engine Type", "Aircraft Number Of Engines"})',
        f'Update = Table.SelectRows(fnReadParquet("{CSVS}Aircraft_2010_Update.parquet"), each List.Contains(FactKeys, [AC_TYPEID]))',
        'UpdateParts = Table.AddColumn(Update, "Parts", each if [AC_GROUPNAME] = null then {} else Text.Split([AC_GROUPNAME], ", "))',
        'UpdateEngine = Table.AddColumn(UpdateParts, "Aircraft Engine Type", each [Parts]{0}?)',
        'UpdateEngines = Table.AddColumn(UpdateEngine, "Aircraft Number Of Engines", each [Parts]{1}?)',
        'UpdateOut = Table.AddColumn(UpdateEngines, "Aircraft Age Classification", each "Current")',
        'Combined = Table.Combine({BaseOut, UpdateOut})',
        'Manufacturer = Table.ReplaceValue(Combined, null, "", Replacer.ReplaceValue, {"MANUFACTURER"})',
        'Mapped = Table.NestedJoin(Manufacturer, {"MANUFACTURER"}, Manufacturers, {"Company"}, "Map", JoinKind.LeftOuter)',
        'Country = Table.AddColumn(Mapped, "Aircraft Manufacturer Country", '
        'each if Table.IsEmpty([Map]) then "Unknown" else [Map]{0}[Country])',
        "Renamed = Table.RenameColumns(Country, {"
        + ", ".join(f'{{"{a}", "{b}"}}' for a, b in AIRCRAFT_RENAMES.items()) + "})",
        f"Selected = Table.SelectColumns(Renamed, {base.m_list(n for n, _ in cols)})",
        f"Typed = Table.TransformColumnTypes(Selected, {base.m_types(cols)})"], "Typed")


def table_specs(types: dict) -> dict[str, dict]:
    specs = _base_table_specs(types)
    specs["Aircraft Types"]["m"] = aircraft_m(specs["Aircraft Types"]["cols"])
    del specs["INLFED"]
    return {("INLFED" if k == "INLFED-1" else k): v for k, v in specs.items()}


def relationships() -> list[tuple[str, str, str, str]]:
    return [r for r in _base_relationships() if r[2] != "INLFED"]


_base_table_specs, _base_relationships = base.table_specs, base.relationships


def configure() -> None:
    base.APP, base.SLUG = APP, SLUG
    base.FLIGHT = f"{QVDS}Flight Data.parquet"
    base.EMPLOYMENT = f"{QVDS}T_F41SCHEDULE_P1A_EMP.parquet"
    base.EMPLOYMENT_COLS = EMPLOYMENT_COLS
    base.DIMENSIONS = [(name, SOURCES[name] + Path(path).name, *rest) for name, path, *rest in base.DIMENSIONS]
    base.SECTION_ACCESS = {}
    base.MEASURES = {k: (n, d.replace("'INLFED-1'", "INLFED"), f) for k, (n, d, f) in base.MEASURES.items()
                     if k not in HC_DELTA_MEASURES}
    base.GAPS = GAPS
    base.table_specs, base.relationships = table_specs, relationships


def build(data_root: str = base.DEFAULT_ROOT) -> Path:
    configure()
    root = base.build(data_root)
    slicers = write_report(root, base.table_specs(base.catalog_types()))
    model = root / "model.json"
    data = json.loads(model.read_text())
    data["slicers"] = slicers
    data["semantic_gaps"].append(
        "List boxes -> one report page per sheet with a slicer per list box whose caption is a model field. Not "
        "rebuilt: Associations' 'Aircraft Type' / 'Aircraft Group' (LB10 / LB11; no such field in the model) and the "
        "Comparative Analysis list boxes LB37-LB45 (alternate states Group A / Group B, captions From / To ... that "
        "are not field names; Power BI slicers have no alternate states). Charts and other sheet objects are not "
        "laid out on the pages.")
    data["generated_by"] = "powerbi/tools/build_airline_ch12.py"
    del data["roles"]
    model.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=base.DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
