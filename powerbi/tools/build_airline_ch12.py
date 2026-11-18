"""Build the Power BI PBIP for Chapter12/Solution_Chapter 12_Airline Operations.qvw from the Chapter 15 base.

Chapter 12 has the same Main Data / calendar / dimension model, metric picker, point-in-time sets, alternate states
and calculated dimensions as Chapter 15 (powerbi/tools/build_airline_base.py), but its own load script:

* sources are the older `Data Files/` QVDs, the Access `Dimension Tables.mdb` airports and the tab-delimited market
  CSVs; Main Data concatenates T_F41SCHEDULE_P1A_EMP.qvd (no headcount deltas, so no HC Change measures);
* Aircraft Types is built in the script from Aircraft_Base_File.csv (ApplyMap of the manufacturer country,
  Left Join of Aircraft_Group.csv) + Concatenate Aircraft_2010_Update.csv, instead of reading the transformed QVD;
* no Section Access: no roles, and the metric picker inline table is `INLFED`.

The base builder's generation code is reused with an AirlineApp for Chapter 12 plus its source paths / tables.

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
    *[g.replace("so RLS and selections", "so selections")
      for g in base.GAPS if not any(w in g for w in ("Section Access", "OMIT", "each role"))],
]

# Comparative Analysis: the 'Origin and Destination - Group A / Group B' containers (CT03 / CT02) show these list
# boxes in the alternate states (titles From Coutry / From State / ... / To Airport); field = the caption before the id.
STATE_BOXES = {"LB39": "Flight Type", "LB43": "Origin Country", "LB44": "Origin State Code", "LB45": "Origin City",
               "LB38": "Origin Airport", "LB40": "Destination Country", "LB41": "Destination State Code",
               "LB42": "Destination City", "LB37": "Destination Airport"}
STATES = ("Group A", "Group B")
ROUTE_MD = ["Origin Country", "Origin State Code", "Origin City", "Destination Country", "Destination State Code",
            "Destination City"]
ROUTE_DIMS = [("Origin Airports", "%Origin Airport ID", "Origin Airport"),
              ("Destination Airports", "%Destination Airport ID", "Destination Airport"),
              ("Flight Types", "%Datasource ID", "Flight Type")]
ROUTE_TARGETS = [("Main Data", c) for c in ROUTE_MD] + [(t, c) for t, _, c in ROUTE_DIMS]


def route_spec(state: str) -> dict:
    # own column names, so parity queries over Main Data fields never bind to the disconnected copies
    keys = [k for _, k, _ in ROUTE_DIMS]
    steps = [f"Source = Table.Distinct(Table.SelectColumns(#\"Main Data\", {base.m_list(keys + ROUTE_MD)}))"]
    last = "Source"
    for i, (table, key, col) in enumerate(ROUTE_DIMS):
        steps += [f'J{i} = Table.NestedJoin({last}, {{"{key}"}}, #"{table}", {{"{key}"}}, "D{i}", JoinKind.LeftOuter)',
                  f'E{i} = Table.ExpandTableColumn(J{i}, "D{i}", {{"{col}"}})']
        last = f"E{i}"
    cols = [(f"{state} {c}", "string") for _, c in ROUTE_TARGETS]
    names = [c for _, c in ROUTE_TARGETS]
    renames = ", ".join(f'{{"{c}", "{state} {c}"}}' for c in names)
    steps += [f"Selected = Table.Distinct(Table.SelectColumns({last}, {base.m_list(names)}))",
              f"Renamed = Table.RenameColumns(Selected, {{{renames}}})",
              f"Typed = Table.TransformColumnTypes(Renamed, {base.m_types(cols)})"]
    return {"cols": cols, "m": base.m_let(steps, "Typed")}


def state_measure(state: str, flights: str, cal: str) -> str:
    period = f"KEEPFILTERS(TREATAS(VALUES('{state}'[{state} Period]), {cal}))"
    route = ", ".join(f"KEEPFILTERS(TREATAS(VALUES('{state} Route'[{state} {c}]), {base.tname(t)}[{c}]))"
                      for t, c in ROUTE_TARGETS)
    return (f"IF(ISFILTERED('{state} Route'), CALCULATE({flights}, {period}, {route}), "
            f"CALCULATE({flights}, {period}))")


def route_slicers() -> list[tuple]:
    return [(f"{lb}-{state}", f"{field} ({state})", "slicer", {"Values": [(f"{state} Route", f"{state} {field}")]}, set())
            for state in STATES for lb, field in STATE_BOXES.items()]


def visual_containers(sheet: str, slicers: list[tuple], visuals: list[tuple], hidden: list[tuple] = ()) -> list[dict]:
    """The base places the container list boxes on Analysis in the default state; they belong to Group A / B."""
    if sheet == "SH_Analysis":
        slicers = [x for x in slicers if x[3]["Values"][0][1] not in set(STATE_BOXES.values()) - {"Flight Type"}]
    if sheet == "SH15":
        slicers = slicers + route_slicers()
    return _base_visual_containers(sheet, slicers, visuals, hidden)


def write_table(path: Path, name: str, spec: dict, measures: list[dict], calc: list[tuple], slug: str = SLUG):
    _base_write_table(path, name, spec, measures, calc, SLUG)


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
    for state in STATES:
        specs[f"{state} Route"] = route_spec(state)
    return specs


_base_table_specs, _base_write_table = base.table_specs, base.write_table
_base_visual_containers = base.visual_containers
CH12 = base.AirlineApp(APP, SLUG, False, "INLFED", True)


def configure() -> None:
    base.FLIGHT = f"{QVDS}Flight Data.parquet"
    base.EMPLOYMENT = f"{QVDS}T_F41SCHEDULE_P1A_EMP.parquet"
    base.EMPLOYMENT_COLS = EMPLOYMENT_COLS
    base.DIMENSIONS = [(name, SOURCES[name] + Path(path).name, *rest) for name, path, *rest in base.DIMENSIONS]
    base.MEASURES = {k: v for k, v in base.MEASURES.items() if k not in HC_DELTA_MEASURES}
    cal = base.c(base.CAL, "Period")
    for pk, state in (("233f869eae9d", "Group A"), ("6ba2cbf5d1e6", "Group B")):
        name, _, fmt = base.MEASURES[pk]
        base.MEASURES[pk] = (name, state_measure(state, base.FLIGHTS, cal), fmt)
    base.GAPS = GAPS
    base.table_specs, base.write_table, base.visual_containers = table_specs, write_table, visual_containers


def build(data_root: str = base.DEFAULT_ROOT) -> Path:
    configure()
    root = base.build(data_root, CH12)
    model = root / "model.json"
    data = json.loads(model.read_text())
    data["route_slicers"] = [{"object": x[0].split("-")[0], "table": x[3]["Values"][0][0], "column": x[3]["Values"][0][1]}
                             for x in route_slicers()]
    data["semantic_gaps"].append(
        "Comparative Analysis list boxes LB37-LB45 sit in the 'Origin and Destination - Group A / B' containers in the "
        "alternate states: slicers on the disconnected 'Group A Route' / 'Group B Route' tables (route_slicers), which "
        "'Group A/B Flights' apply with TREATAS like the Group A / B periods ({[Group A] * $}); with a route slicer "
        "set, a route field left unselected still drops flights without an airport / flight type match. LB10 "
        "'Aircraft Type' / LB11 'Aircraft Group': this script loads neither field (Aircraft Name is SSD_NAME, which "
        "matches the old Aircraft Type text for 50 of 180 types; the group text is split into Aircraft Engine Type / "
        "Number Of Engines).")
    data["semantic_gaps"].append(
        "FTE % to Total (CH43): $(vTotalFTEs) is '= Sum([# Equivalent FTEs])', evaluated once over the selection, so the "
        "denominator is the selection-wide total -> CALCULATE(..., ALLSELECTED()); the inventory expansion had dropped "
        "the '=' (each carrier divided by itself) and is corrected to Sum(TOTAL ...) in the manifest.")
    data["generated_by"] = "powerbi/tools/build_airline_ch12.py"
    data.pop("roles", None)
    model.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=base.DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
