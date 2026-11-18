"""Generate the Chapter 15 Airline Operations PBIP: the reusable base model for the Airline chapters.

Chapter 15's load script transforms its tables (concatenated facts, master calendar, WHERE Exists, 'Unknown'
members, inline tables, Section Access), so scaffold_pbip.py cannot generate it. This script writes the same
PBIP layout with hand-written Power Query, relationships, RLS/OLS roles and DAX measures. Every measure carries
the ParityKey of the Qlik expression(s) it replaces; build() fails if a KPI with source-side parity has none.

    python powerbi/tools/build_airline_base.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaffold_pbip import APPS, CATALOG, POWERBI, TYPE_MAP, show, tag, tname  # noqa: E402

sys.path.insert(0, str(POWERBI / "parity"))
from harness import kpi_list, parity_key  # noqa: E402

APP = "Chapter15__Solution_Chapter 15_Airline Operations"
SLUG = "Chapter15_Airline_Operations"
DEFAULT_ROOT = "C:\\QlikView-for-Developers\\powerbi\\data\\parquet\\"
FLIGHT = "QVD/Source/Flight Data.parquet"
EMPLOYMENT = "QVD/Transformed/Employment Statistics.parquet"
MD = "'Main Data'"

FLIGHT_COLS = [
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
    "Destination Country", "Period", "From - To Airport Code", "From - To Airport ID", "From - To City",
    "From - To State Code", "From - To State"]
EMPLOYMENT_COLS = [
    "# M-Delta Total Employees", "# M-Delta Full Time Employees", "# M-Delta Part Time Employees",
    "# M-Delta Equivalent FTEs", "# Q-Delta Total Employees", "# Q-Delta Full Time Employees",
    "# Q-Delta Part Time Employees", "# Q-Delta Equivalent FTEs", "# Y-Delta Total Employees",
    "# Y-Delta Full Time Employees", "# Y-Delta Part Time Employees", "# Y-Delta Equivalent FTEs", "%Airline ID",
    "# Total Employees", "Period", "%Unique Carrier Code", "Unique Carrier", "Carrier Code", "Carrier Name",
    "%Carrier Group ID", "# Full Time Employees", "# Part Time Employees", "# Equivalent FTEs"]

# (table, parquet, key, label columns, add 'Unknown' members for fact keys missing from the dimension)
DIMENSIONS = [
    ("Carrier Groups", "QVD/Source/Carrier Groups.parquet", "%Carrier Group ID", ["Carrier Group"], True),
    ("Airlines", "QVD/Source/Airlines.parquet", "%Airline ID", ["Airline"], False),
    ("Carrier Operating Region", "QVD/Source/Carrier Operating Region.parquet", "%Region Code",
     ["Carrier's Operating Region"], True),
    ("Flight Types", "QVD/Source/Flight Types.parquet", "%Datasource ID", ["Flight Type"], False),
    ("Aircraft Types", "QVD/Transformed/Aircraft Types Transformed.parquet", "%Aircraft Type ID",
     ["Aircraft Name", "Aircraft Manufacturer", "Aircraft Manufacturer Country", "Aircraft Name Full",
      "Aircraft Name Abbreviated", "Aircraft Begin Date", "Aircraft End Date", "Aircraft Age Classification",
      "Aircraft Engine Type", "Aircraft Number Of Engines"], False),
    ("Distance Groups", "QVD/Source/Distance Groups.parquet", "%Distance Group ID", ["Distance Interval"], False),
    ("Origin Airports", "QVD/Source/Origin Airports.parquet", "%Origin Airport ID", ["Origin Airport"], False),
    ("Destination Airports", "QVD/Source/Destination Airports.parquet", "%Destination Airport ID",
     ["Destination Airport"], False),
    ("Origin Markets", "QVD/Source/Origin Markets.parquet", "%Origin Airport Market ID", ["Origin Market"], True),
    ("Destination Markets", "QVD/Source/Destination Markets.parquet", "%Destination Airport Market ID",
     ["Destination Market"], True),
]

FLIGHT_TYPES = {"DOMESTIC_FOREIGN": "Domestic, Foreign Carriers", "DOMESTIC_US": "Domestic, US Carriers Only",
                "INTERNATIONAL_FOREIGN": "International, Foreign Carriers",
                "INTERNATIONAL_US": "International, US Carriers Only"}
# Section Access rows (passwords dropped): USERID -> (%FLIGHTTYPE values, '*' = every listed value; OMIT field)
SECTION_ACCESS = {"ADMIN": (["*", "INTERNATIONAL_US"], None), "DF": (["DOMESTIC_FOREIGN"], None),
                  "DU": (["DOMESTIC_US"], None), "IF": (["INTERNATIONAL_FOREIGN"], None),
                  "NOCARRIER": (["*"], "Carrier Name")}
METRICS = [("# of Flights", "eDeparturesPerformed"), ("Enplaned Passengers", "eEnplanedPassengers"),
           ("Air Time", "eAirTime")]


def c(table: str, col: str) -> str:
    return f"{tname(table) if not table.startswith(chr(39)) else table}[{col.replace(']', ']]')}]"


def m(col: str) -> str:
    return c(MD, col)


CAL = "'Master Calendar'"
LF = f"DIVIDE(SUM({m('# Transported Passengers')}), SUM({m('# Available Seats')}))"
FLIGHTS = "[# of Flights]"
MAX_YEAR = f"CALCULATE(MAX({c(CAL, 'Year')}), ALLSELECTED())"
MAX_MONTH = f"CALCULATE(MAX({c(CAL, 'Month__num')}), ALLSELECTED())"
MAX_PERIOD_ID = f"CALCULATE(MAX({c(CAL, 'PeriodID')}), ALLSELECTED())"
CYCLIC = [c("Airlines", "Airline"), m("Origin Country"), m("Destination Country")]


def total_dax(base: str, keep: list[str]) -> str:
    """Qlik Sum(TOTAL <keep> x): ignore the chart's dimensions except those in `keep` that are in scope."""
    def build(i: int, kept: list[str]) -> str:
        if i == len(keep):
            return f"CALCULATE({base}, ALLSELECTED(){''.join(f', VALUES({k})' for k in kept)})"
        return f"IF(ISINSCOPE({keep[i]}), {build(i + 1, kept + [keep[i]])}, {build(i + 1, kept)})"
    return build(0, [])


def pit(base: str, year_offset: int | None = None, month: str | None = None, period_back: str | None = None) -> str:
    """Point-in-time set (the reconstructed vSet* variables): clear the calendar, then select by Year/Month or PeriodID."""
    if period_back is not None:
        return (f"VAR p = {MAX_PERIOD_ID} - {period_back} RETURN "
                f"CALCULATE({base}, REMOVEFILTERS({CAL}), {c(CAL, 'PeriodID')} = p)")
    op = "<=" if month == "ytd" else "="
    return (f"VAR y = {MAX_YEAR} - {year_offset} VAR mo = {MAX_MONTH} RETURN "
            f"CALCULATE({base}, REMOVEFILTERS({CAL}), {c(CAL, 'Year')} = y, {c(CAL, 'Month__num')} {op} mo)")


def var_pct(a: str, b: str) -> str:
    return f"VAR r = DIVIDE({a}, {b}) RETURN IF(ISBLANK(r), BLANK(), r - 1)"


def avg_route_lf(*cols: str) -> str:
    return (f"AVERAGEX(FILTER(ADDCOLUMNS(SUMMARIZE({MD}, {', '.join(cols)}), \"@lf\", CALCULATE({LF})), "
            f"NOT ISBLANK([@lf])), [@lf])")


ROUTE, FT, CG, CN = m("From - To Airport ID"), c("Flight Types", "Flight Type"), c("Carrier Groups", "Carrier Group"), m("Carrier Name")
COR = c("Carrier Operating Region", "Carrier's Operating Region")
PCT, NUM, DEC = "0.00%", "#,0", "#,0.00"

# parity key -> (measure name, DAX, format string)
MEASURES = {
    "1baea265cccd": ("# of Flights", f"SUM({m('# Departures Performed')})", NUM),
    "7f15ad08b3bb": ("# of Enplanned Passengers", f"SUM({m('# Transported Passengers')})", NUM),
    "aea8a21aee5f": ("Transported Freight", f"SUM({m('# Transported Freight')})", NUM),
    "e0ca719214a7": ("Transported Mail", f"SUM({m('# Transported Mail')})", NUM),
    "0c8ca154aacf": ("# of Passengers (millions)", f"DIVIDE(SUM({m('# Transported Passengers')}), 1000000)", DEC),
    "8dfad31060e3": ("# of Available Seats (millions)", f"DIVIDE(SUM({m('# Available Seats')}), 1000000)", DEC),
    "213681cc0d2a": ("Load Factor", LF, PCT),
    "7588bff24d2c": ("Performed vs Scheduled",
                     f"DIVIDE(SUM({m('# Departures Performed')}), SUM({m('# Departures Scheduled')}))", PCT),
    "cd4c4a3c94f4": ("Air Time %", f"DIVIDE(SUM({m('# Air Time')}), SUM({m('# Ramp-To-Ramp Time')}))", PCT),
    "a1ec8a2cb5ee": ("Air Time % (CH21)", f"DIVIDE(SUM({m('# Air Time')}), SUM({m('# Ramp-To-Ramp Time')}))", PCT),
    "90777bd5df7f": ("Carrier", f"IF(DISTINCTCOUNTNOBLANK({CN}) = 1, MAX({CN}), \"Others\")", None),
    "072410d4365a": ("Departures Performed (thousands)", f"DIVIDE({FLIGHTS}, 1000)", DEC),
    "f0af66ad7007": ("FTE % to Total", f"DIVIDE(SUM({m('# Equivalent FTEs')}), SUM({m('# Equivalent FTEs')}))", PCT),
    "db52d6494b27": ("FTEs", f"SUM({m('# Equivalent FTEs')})", NUM),
    "a8d240d462f9": ("# of Flights (units)", f"DIVIDE({FLIGHTS}, 1)", NUM),
    "f72a33049af9": ("# of Flights (thousands)", f"DIVIDE({FLIGHTS}, 1000)", DEC),
    "0437729d9522": ("# of Flights (millions)", f"DIVIDE({FLIGHTS}, 1000000)", DEC),
    "b8cda7856288": ("Selected Metric",
                     "SWITCH(SELECTEDVALUE('INLFED-1'[eMetric]), "
                     f"\"eDeparturesPerformed\", DIVIDE({FLIGHTS}, 1000), "
                     f"\"eEnplanedPassengers\", DIVIDE(SUM({m('# Transported Passengers')}), 1000000), "
                     f"\"eAirTime\", DIVIDE(SUM({m('# Air Time')}), SUM({m('# Ramp-To-Ramp Time')})))", DEC),
    "2727aeae83d4": ("Participation to the whole", f"DIVIDE({FLIGHTS}, {total_dax(FLIGHTS, [])})", PCT),
    "599355404d68": ("% vs the Carrier's whole", f"DIVIDE({FLIGHTS}, {total_dax(FLIGHTS, [CG, CN])})", PCT),
    "624bbb57c7a7": ("% vs the Carrier's whole per year",
                     f"DIVIDE({FLIGHTS}, {total_dax(FLIGHTS, [CG, CN, c(CAL, 'Year')])})", PCT),
    "0a66033bf9d0": ("# of Carriers", f"DISTINCTCOUNTNOBLANK({CN})", NUM),
    "cdd5b20db14b": ("Average Load Factor per Route", avg_route_lf(c("Airlines", "Airline"), ROUTE), PCT),
    "527a7b7f9d77": ("Dimensionality",
                     f"IF(NOT ISEMPTY({MD}), " + " + ".join(
                         f"INT(ISINSCOPE({x}))" for x in [CG, *CYCLIC, c("Aircraft Types", "Aircraft Name")]) + ")",
                     "0"),
    "18b5ee2089a0": ("Avg Load Factor per Route (by level)",
                     f"SWITCH(INT(ISINSCOPE({FT})) + INT(ISINSCOPE({CG})) + INT(ISINSCOPE({CN})), "
                     f"0, {avg_route_lf(ROUTE)}, 1, {avg_route_lf(ROUTE, FT)}, 2, {avg_route_lf(ROUTE, FT, CG)}, "
                     f"3, {avg_route_lf(ROUTE, CG, FT, CN)})", PCT),
    "4a285b15d9d8": ("Foreign Carriers' flights", f"CALCULATE({FLIGHTS}, KEEPFILTERS({CG} = \"Foreign Carriers\"))", NUM),
    "e6f0f64c372a": ("Domestic and Latin America (2010)",
                     f"CALCULATE({FLIGHTS}, KEEPFILTERS({COR} "
                     f"IN {{\"Domestic\", \"Latin America\"}}), KEEPFILTERS({c(CAL, 'Year')} = 2010))", NUM),
    "5960f0d975e3": ("2010 Flights", f"CALCULATE({FLIGHTS}, KEEPFILTERS({c(CAL, 'Year')} = 2010))", NUM),
    "12972176d425": ("2011 Flights", f"CALCULATE({FLIGHTS}, KEEPFILTERS({c(CAL, 'Year')} = 2011))", NUM),
    "674eb51e60d5": ("Current Year Flights",
                     f"VAR y = {MAX_YEAR} RETURN CALCULATE({FLIGHTS}, KEEPFILTERS({c(CAL, 'Year')} = y))", NUM),
    "e483b68667ee": ("Previous Year Flights",
                     f"VAR y = {MAX_YEAR} - 1 RETURN CALCULATE({FLIGHTS}, KEEPFILTERS({c(CAL, 'Year')} = y))", NUM),
    "c4c3691d5d18": ("Latin America 2011 + Domestic 2010 excl. Foreign",
                     f"CALCULATE({FLIGHTS}, KEEPFILTERS(FILTER(SUMMARIZE({MD}, "
                     f"{COR}, {c(CAL, 'Year')}, {CG}), "
                     f"((({COR} = \"Latin America\" && {c(CAL, 'Year')} = 2011) "
                     f"|| ({COR} = \"Domestic\" && {c(CAL, 'Year')} = 2010)) "
                     f"&& NOT ({CG} = \"Foreign Carrier\")))))", NUM),
    "86cbdcf06a0d": ("Flights in excluded years",
                     f"VAR excluded = EXCEPT(ALL({c(CAL, 'Year')}), ALLSELECTED({c(CAL, 'Year')})) "
                     f"RETURN CALCULATE({FLIGHTS}, KEEPFILTERS(excluded))", NUM),
    "faf40071dfd3": ("YTD Flights Var %", var_pct(pit(FLIGHTS, 0, "ytd"), pit(FLIGHTS, 1, "ytd")), PCT),
    "bbaa93b98827": ("MTD Flights Var % vs LY", var_pct(pit(FLIGHTS, 0, "mtd"), pit(FLIGHTS, 1, "mtd")), PCT),
    "0001ae6d8196": ("MTD Flights Var % vs Previous Month", var_pct(pit(FLIGHTS, 0, "mtd"), pit(FLIGHTS, period_back="1")), PCT),
    "b200807bf073": ("YTD Flights", pit(FLIGHTS, 0, "ytd"), NUM),
    "b45172e8680e": ("Current Month Flights", pit(FLIGHTS, period_back="0"), NUM),
    "f81b30295d5f": ("Flights Previous Month", pit(FLIGHTS, period_back="1"), NUM),
    "c61bbcf8a5bc": ("Flights Two Months Ago", pit(FLIGHTS, period_back="2"), NUM),
    "233f869eae9d": ("Group A Flights",
                     f"CALCULATE({FLIGHTS}, KEEPFILTERS(TREATAS(VALUES('Group A'[Period]), {c(CAL, 'Period')})))", NUM),
    "6ba2cbf5d1e6": ("Group B Flights",
                     f"CALCULATE({FLIGHTS}, KEEPFILTERS(TREATAS(VALUES('Group B'[Period]), {c(CAL, 'Period')})))", NUM),
    "97885edb520e": ("Full Time HC Change", f"SUM({m('# M-Delta Full Time Employees')})", NUM),
    "bebebe28ced0": ("Part Time HC Change", f"SUM({m('# M-Delta Part Time Employees')})", NUM),
    "53f3fabda737": ("Total HC Change", f"SUM({m('# M-Delta Total Employees')})", NUM),
    "bdf635c244a3": ("Total HC Change MTD", pit(f"SUM({m('# M-Delta Total Employees')})", 0, "mtd"), NUM),
    "04c961e41f32": ("Total HC Change YTD", pit(f"SUM({m('# M-Delta Total Employees')})", 0, "ytd"), NUM),
    "d76da9774b00": ("FTEs MTD", pit(f"SUM({m('# Equivalent FTEs')})", 0, "mtd"), NUM),
}

_STATES = f"CALCULATE(DISTINCTCOUNTNOBLANK({m('From - To State Code')}), ALLEXCEPT({MD}, {CN}))"
_CARRIER_LF = (f"DIVIDE(CALCULATE(SUM({m('# Transported Passengers')}), ALLEXCEPT({MD}, {CN})), "
               f"CALCULATE(SUM({m('# Available Seats')}), ALLEXCEPT({MD}, {CN})))")
# Qlik calculated dimensions -> calculated columns: (table, column, Qlik dimension text, DAX, dataType)
CALC_DIMS = [
    ("Flight Types", "Deal Status",
     "=if([Flight Type]='Domestic, US Carriers Only', 'Open',\nif([Flight Type]='International, Foreign Carriers', 'Negotiating', 'Closed'))",
     "SWITCH([Flight Type], \"Domestic, US Carriers Only\", \"Open\", \"International, Foreign Carriers\", \"Negotiating\", \"Closed\")",
     "string"),
    ("Main Data", "Carrier State Count", "=Aggr(Count(DISTINCT [From - To State Code]), [Carrier Name])",
     f"IF(ISBLANK([Carrier Name]), BLANK(), {_STATES})", "int64"),
    ("Main Data", "Carrier State Count Band",
     "=Replace(Aggr(Class(Count(DISTINCT [From - To State Code]), 100), [Carrier Name]), '<= x <', ' - ')",
     f"IF(ISBLANK([Carrier Name]), BLANK(), VAR lo = FLOOR({_STATES}, 100) RETURN lo & \"  -  \" & (lo + 100))",
     "string"),
    ("Main Data", "Carrier Load Factor Band",
     "=Replace(Aggr(Class($(eLoadFactor)*100, 10), [Carrier Name]), '<= x <', ' - ')",
     f"VAR lf = IF(ISBLANK([Carrier Name]), BLANK(), {_CARRIER_LF}) RETURN "
     f"IF(ISBLANK(lf), BLANK(), VAR lo = FLOOR(lf * 100, 10) RETURN lo & \"  -  \" & (lo + 10))", "string"),
]

GAPS = [
    "Section Access -> RLS roles named after the Qlik USERIDs (ADMIN, DF, DU, IF, NOCARRIER) filtering INLFED[%FLIGHTTYPE]; "
    "passwords are not migrated, role membership is assigned in the Power BI service. '*' means every %FLIGHTTYPE value "
    "listed in Section Access, so ADMIN and NOCARRIER see the four flight types and, like in QlikView, not the "
    "Employment Statistics rows of Main Data (they have no %Datasource ID). Users outside every role (dataset owners) see "
    "all rows, which QlikView never showed in this document.",
    "OMIT Carrier Name (NOCARRIER) -> object-level security: Carrier Name has columnPermission none for that role; measures "
    "and calculated columns that reference it fail for that role instead of returning null as in QlikView.",
    "Master Calendar: QlikView keeps one row per day (1,065) because the script's LOAD DISTINCTs sit under a non-distinct "
    "preceding Load *; Power BI keeps one row per month (36) so Period can be the one side of the relationship. Measures "
    "over Main Data are unaffected; counts over calendar rows would differ.",
    "Dimension rows: RLS filters Main Data only, so a slicer on a dimension lists rows the role's facts do not use "
    "(QlikView's reduction removes them, e.g. Airlines 336 under ADMIN vs 337 in the model). Null-key 'Unknown' members "
    "the script adds for null fact keys are not loaded: they associate with nothing in QlikView and would wrongly match "
    "blank keys in Power BI.",
    "Set analysis value modifiers use KEEPFILTERS: identical to QlikView with no selections (the parity baseline); with a "
    "slicer selection on the same field Power BI intersects where QlikView replaces the selection.",
    "Point-in-time sets (vSetYTD, vSetLYYTD, vSetMTD, vSetLYMTD, vSetPreviousMonth, vSetPreviousNMonth) are defined in "
    "..\\0.Includes\\SetVariables.txt, which is not in the repo; their definitions are reconstructed (see "
    "parity/models/<app>.overlay.json) and the measures implement the same reconstruction.",
    "Alternate states Group A / Group B -> disconnected 'Group A' / 'Group B' period tables used as slicers; the measures "
    "intersect the main selection with the group's periods ({[Group A] * $}).",
    "Calculated dimensions (Aggr()/Class() buckets, the Flight Type deal status) -> calculated columns computed at refresh "
    "over all rows, so they do not react to selections as QlikView's Aggr() does; identical with no selections.",
    "Dimensionality()/Pick(Dimensionality()+1, ...) -> ISINSCOPE() over the chart's dimension fields.",
    "$($(=eMetric)) -> SWITCH over SELECTEDVALUE('INLFED-1'[eMetric]); blank without a single Metric Name selected, "
    "like QlikView's empty expansion.",
]


def catalog_types() -> dict[str, dict[str, str]]:
    out = {}
    for src in json.loads(CATALOG.read_text())["sources"].values():
        for t in src.get("tables", []):
            out[t["parquet"].split("powerbi/data/parquet/", 1)[1]] = {col["name"]: col["type"] for col in t["columns"]}
    return out


def m_list(names) -> str:
    return "{" + ", ".join(json.dumps(n) for n in names) + "}"


def m_types(cols) -> str:
    return "{" + ", ".join(f"{{{json.dumps(n)}, {TYPE_MAP[t][1]}}}" for n, t in cols) + "}"


def m_let(steps: list[str], last: str) -> str:
    body = ",\n".join("\t\t\t\t    " + s for s in steps)
    return f"\t\t\t\tlet\n{body}\n\t\t\t\tin\n\t\t\t\t    {last}"


def table_specs(types: dict) -> dict[str, dict]:
    specs = {}
    emp_only = [x for x in EMPLOYMENT_COLS if x not in FLIGHT_COLS]
    md_cols = [(x, types[FLIGHT][x]) for x in FLIGHT_COLS] + [(x, types[EMPLOYMENT][x]) for x in emp_only]
    specs["Main Data"] = {"cols": md_cols, "m": m_let([
        f'Flight = Table.SelectColumns(fnReadParquet("{FLIGHT}"), {m_list(FLIGHT_COLS)})',
        f'Employment = Table.SelectColumns(fnReadParquet("{EMPLOYMENT}"), {m_list(EMPLOYMENT_COLS)})',
        "Combined = Table.Combine({Flight, Employment})",
        f"Typed = Table.TransformColumnTypes(Combined, {m_types(md_cols)})"], "Typed")}
    cal_cols = [("Period", "int64"), ("Year", "int64"), ("Month", "string"), ("Month__num", "float64"),
                ("Year - Month", "string"), ("Year - Month__num", "float64"), ("Quarter", "string"),
                ("QuarterID", "int64"), ("PeriodID", "int64")]
    specs["Master Calendar"] = {"cols": cal_cols, "m": m_let([
        'Periods = List.RemoveNulls(fnFactKeys("Period"))',
        "MinDate = #date(Number.IntegerDivide(List.Min(Periods), 100), Number.Mod(List.Min(Periods), 100), 1)",
        "MaxDate = #date(Number.IntegerDivide(List.Max(Periods), 100), Number.Mod(List.Max(Periods), 100), 1)",
        "Months = List.Generate(() => MinDate, each _ <= MaxDate, each Date.AddMonths(_, 1))",
        'Base = Table.FromList(Months, Splitter.SplitByNothing(), {"MonthStart"})',
        'Indexed = Table.AddIndexColumn(Base, "PeriodID", 1, 1)',
        'Cols = Table.AddColumn(Indexed, "Fields", each [Period = Date.Year([MonthStart]) * 100 + Date.Month([MonthStart]), '
        'Year = Date.Year([MonthStart]), Month = Date.ToText([MonthStart], "MMM", "en-US"), Month__num = Date.Month([MonthStart]), '
        '#"Year - Month" = Date.ToText([MonthStart], "yyyy-MM", "en-US"), #"Year - Month__num" = Number.From([MonthStart]), '
        'Quarter = "Q" & Text.From(Number.RoundUp(Date.Month([MonthStart]) / 3)), '
        'QuarterID = (Date.Year([MonthStart]) - Date.Year(MinDate)) * 4 + Number.RoundUp(Date.Month([MonthStart]) / 3) '
        '- Number.RoundUp(Date.Month(MinDate) / 3) + 1])',
        'Expanded = Table.ExpandRecordColumn(Cols, "Fields", {"Period", "Year", "Month", "Month__num", "Year - Month", '
        '"Year - Month__num", "Quarter", "QuarterID"})',
        f"Selected = Table.SelectColumns(Expanded, {m_list(n for n, _ in cal_cols)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(cal_cols)})"], "Typed")}
    for name, path, key, labels, unknown in DIMENSIONS:
        cols = [(key, types[path][key])] + [(x, types[path][x]) for x in labels]
        steps = [f'Source = Table.SelectColumns(fnReadParquet("{path}"), {m_list([key, *labels])})',
                 f'FactKeys = List.Buffer(List.RemoveNulls(fnFactKeys("{key}")))',
                 f'Kept = Table.SelectRows(Source, each List.Contains(FactKeys, [{key}]))']
        last = "Kept"
        if unknown:
            steps += [f'Missing = List.Difference(FactKeys, Table.Column(Kept, "{key}"))',
                      f'Unknown = Table.FromColumns({{Missing, List.Repeat({{"Unknown"}}, List.Count(Missing))}}, '
                      f'{m_list([key, labels[0]])})',
                      "Combined = Table.Combine({Kept, Unknown})"]
            last = "Combined"
        steps.append(f"Typed = Table.TransformColumnTypes({last}, {m_types(cols)})")
        specs[name] = {"cols": cols, "m": m_let(steps, "Typed")}
    specs["INLFED"] = {"cols": [("Flight Type", "string"), ("%FLIGHTTYPE", "string")], "m": m_let([
        "Source = #table(type table [#\"Flight Type\" = text, #\"%FLIGHTTYPE\" = text], {"
        + ", ".join(f'{{"{v}", "{k}"}}' for k, v in FLIGHT_TYPES.items()) + "})"], "Source")}
    specs["INLFED-1"] = {"cols": [("Metric Name", "string"), ("eMetric", "string")], "m": m_let([
        "Source = #table(type table [#\"Metric Name\" = text, eMetric = text], {"
        + ", ".join(f'{{"{a}", "{b}"}}' for a, b in METRICS) + "})"], "Source")}
    for state in ("Group A", "Group B"):
        gcols = cal_cols[:6]
        specs[state] = {"cols": gcols, "m": m_let([
            f'Source = Table.SelectColumns(#"Master Calendar", {m_list(n for n, _ in gcols)})'], "Source")}
    return specs


def write_table(path: Path, name: str, spec: dict, measures: list[dict], calc: list[tuple]):
    keys = {k for _, _, k, _, _ in DIMENSIONS} | {"Period", "%FLIGHTTYPE"}
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
        if (col.startswith("%") and name not in ("INLFED",)) or col.endswith("__num") or \
                (col == "Period" and name == "Main Data"):
            lines.append("\t\tisHidden")
        if f"{col}__num" in names:
            lines.append(f"\t\tsortByColumn: {tname(col + '__num')}")
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


def relationships() -> list[tuple[str, str, str, str]]:
    rels = [("Main Data", key, name, key) for name, _, key, _, _ in DIMENSIONS]
    rels.append(("Main Data", "Period", "Master Calendar", "Period"))
    rels.append(("Flight Types", "Flight Type", "INLFED", "Flight Type"))  # Section Access reduction path
    return rels


def role_tmdl(user: str) -> str:
    values, omit = SECTION_ACCESS[user]
    allowed = sorted(FLIGHT_TYPES) if "*" in values else sorted(set(values))
    filt = "INLFED[%FLIGHTTYPE] IN {" + ", ".join(f'"{v}"' for v in allowed) + "}"
    lines = [f"role {tname(user)}", "\tmodelPermission: read", "", f"\ttablePermission INLFED = {filt}", ""]
    if omit:
        lines += [f"\ttablePermission {MD}", "", f"\t\tcolumnPermission {tname(omit)} = none", ""]
    lines += [f"\tannotation QlikSectionAccess = USERID {user}; %FLIGHTTYPE {', '.join(values)}"
              + (f"; OMIT {omit}" if omit else ""), ""]
    return "\n".join(lines)


def build(data_root: str = DEFAULT_ROOT) -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = APPS / SLUG
    sm, rp = root / f"{SLUG}.SemanticModel", root / f"{SLUG}.Report"
    for d in (sm / "definition" / "tables", sm / "definition" / "roles", rp):
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
        write_table(sm / "definition" / "tables", name, spec,
                    list(measures.values()) if name == "Main Data" else [],
                    [x for x in CALC_DIMS if x[0] == name])
    rels = []
    for ft, fc, tt, tc in relationships():
        rels += [f"relationship {tag(SLUG, 'rel', ft, fc, tt)}", f"\tfromColumn: {tname(ft)}.{tname(fc)}",
                 f"\ttoColumn: {tname(tt)}.{tname(tc)}", ""]
    (sm / "definition" / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")
    for user in SECTION_ACCESS:
        (sm / "definition" / "roles" / f"{user}.tmdl").write_text(role_tmdl(user), encoding="utf-8")
    (sm / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n", encoding="utf-8")
    refs = "\n".join(f"ref table {tname(t)}" for t in specs) + "\n\n" + \
        "\n".join(f"ref role {tname(u)}" for u in SECTION_ACCESS)
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
        {"app": APP, "generated_by": "powerbi/tools/build_airline_base.py",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in measures.values()],
         "calculated_dimensions": [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q, "dax": d}
                                   for t, col, q, d, _ in CALC_DIMS],
         "roles": {u: {"flight_types": v, "omit": o} for u, (v, o) in SECTION_ACCESS.items()},
         "semantic_gaps": GAPS}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(specs)} tables, {len(rels) // 4} relationships, {len(SECTION_ACCESS)} roles, "
          f"{len(measures)} measures, {len(CALC_DIMS)} calculated columns")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
