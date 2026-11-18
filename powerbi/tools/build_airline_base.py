"""Generate the Airline Operations PBIPs: the Chapter 15 base model and the chapters derived from it.

Chapter 15's load script transforms its tables (concatenated facts, master calendar, WHERE Exists, 'Unknown'
members, inline tables, Section Access), so scaffold_pbip.py cannot generate it. This script writes the same
PBIP layout with hand-written Power Query, relationships, RLS/OLS roles and DAX measures. Every measure carries
the ParityKey of the Qlik expression(s) it replaces; build() fails if a KPI with source-side parity has none.

Chapters 13 and 14 have the same script without the hidden Section Access script: no roles, no INLFED %FLIGHTTYPE table
(its metric picker is then the first inline table, INLFED), and the unreduced model. It also gets one report page
per QlikView sheet, with a visual per chart bound to the measures and fields the chart's KPIs use.

    python powerbi/tools/build_airline_base.py [--app Chapter15|Chapter13|Chapter14|all] [--data-root C:\\path\\to\\parquet\\]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaffold_pbip import APPS, CATALOG, POWERBI, REPO, TYPE_MAP, show, tag, tname  # noqa: E402

sys.path.insert(0, str(POWERBI / "parity"))
from harness import kpi_list, parity_key  # noqa: E402


@dataclass(frozen=True)
class AirlineApp:
    app: str
    slug: str
    section_access: bool  # hidden script: Section Access, RLS/OLS roles and the INLFED %FLIGHTTYPE table
    metric_table: str  # the Metric Name / eMetric inline table
    report_pages: bool  # one report page per QlikView sheet (else a single empty page)


CH15 = AirlineApp("Chapter15__Solution_Chapter 15_Airline Operations", "Chapter15_Airline_Operations", True,
                  "INLFED-1", False)
CH13 = AirlineApp("Chapter13__Solution_Chapter 13_Airline Operations", "Chapter13_Airline_Operations", False,
                  "INLFED", True)
CH14 = AirlineApp("Chapter14__Solution_Chapter 14_Airline Operations", "Chapter14_Airline_Operations", False,
                  "INLFED", True)
AIRLINE_APPS = {"Chapter15": CH15, "Chapter13": CH13, "Chapter14": CH14}
CFG = CH15
APP, SLUG = CFG.app, CFG.slug
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

# 12 flight rows have no %Carrier Group ID / %Airline ID. A filtered (RLS) dimension hides fact rows on its blank
# member, so those keys point at a placeholder member with a null label instead: grouped they still show as the
# null row, as in QlikView, and every role can reduce these dimensions the way Section Access does.
NULL_KEY = -1
NULL_KEY_FIELDS = ["%Carrier Group ID", "%Airline ID"]

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
    # $(vTotalFTEs) with vTotalFTEs = '= Sum(...)': evaluated once over the selection, i.e. Sum(TOTAL ...)
    "9f20a3cefdc3": ("FTE % to Total",
                     f"DIVIDE(SUM({m('# Equivalent FTEs')}), CALCULATE(SUM({m('# Equivalent FTEs')}), ALLSELECTED()))", PCT),
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
    "0a66033bf9d0": ("# of Carriers", "CARRIERS", NUM),  # filled in below from SEGMENTS
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
                     f"CALCULATE({FLIGHTS}, KEEPFILTERS(TREATAS(VALUES('Group A'[Group A Period]), {c(CAL, 'Period')})))", NUM),
    "6ba2cbf5d1e6": ("Group B Flights",
                     f"CALCULATE({FLIGHTS}, KEEPFILTERS(TREATAS(VALUES('Group B'[Group B Period]), {c(CAL, 'Period')})))", NUM),
    "97885edb520e": ("Full Time HC Change", f"SUM({m('# M-Delta Full Time Employees')})", NUM),
    "bebebe28ced0": ("Part Time HC Change", f"SUM({m('# M-Delta Part Time Employees')})", NUM),
    "53f3fabda737": ("Total HC Change", f"SUM({m('# M-Delta Total Employees')})", NUM),
    "bdf635c244a3": ("Total HC Change MTD", pit(f"SUM({m('# M-Delta Total Employees')})", 0, "mtd"), NUM),
    "04c961e41f32": ("Total HC Change YTD", pit(f"SUM({m('# M-Delta Total Employees')})", 0, "ytd"), NUM),
    "d76da9774b00": ("FTEs MTD", pit(f"SUM({m('# Equivalent FTEs')})", 0, "mtd"), NUM),
}

_STATES = f"CALCULATE(DISTINCTCOUNTNOBLANK({m('From - To State Code')}))"
# Qlik Aggr() calculated dimensions over [Carrier Name] -> disconnected segment tables; '# of Carriers' counts the carriers
# whose per-carrier value falls in the segment in scope, at query time, so RLS and selections apply as in QlikView.
# (table, label column, Qlik dimension text, segment values (M list), label (M, from [Low]), carrier's value (DAX);
# a null segment holds the carriers whose value is blank, like QlikView's null dimension row)
SEGMENTS = [
    ("Carrier State Count", "Carrier State Count", "=Aggr(Count(DISTINCT [From - To State Code]), [Carrier Name])",
     "List.Numbers(0, 5001)", None, f"{_STATES} + 0"),
    ("Carrier State Count Band", "Carrier State Count Band",
     "=Replace(Aggr(Class(Count(DISTINCT [From - To State Code]), 100), [Carrier Name]), '<= x <', ' - ')",
     "List.Numbers(0, 51, 100)", 'Text.From([Low]) & "  -  " & Text.From([Low] + 100)', f"FLOOR({_STATES} + 0, 100)"),
    ("Carrier Load Factor Band", "Carrier Load Factor Band",
     "=Replace(Aggr(Class($(eLoadFactor)*100, 10), [Carrier Name]), '<= x <', ' - ')",
     "List.Numbers(0, 101, 10) & {null}", 'if [Low] = null then null else Text.From([Low]) & "  -  " & Text.From([Low] + 10)',
     f"VAR lf = CALCULATE({LF}) RETURN IF(ISBLANK(lf), BLANK(), FLOOR(lf * 100, 10))"),
]


def carriers_dax() -> str:
    """Carriers in every filtered segment (grouped or sliced); IN compares BLANK strictly (the null segment)."""
    filtered, tests = [], []
    for table, col, _, _, label, value in SEGMENTS:
        low = c(table, "Low" if label else col)
        flt = f"ISFILTERED({c(table, col)}) || ISFILTERED({low})"
        filtered.append(f"({flt})")
        tests.append(f"(NOT ({flt}) || ({value}) IN VALUES({low}))")
    return (f"IF({' || '.join(filtered)}, COUNTROWS(FILTER(VALUES({CN}), NOT ISBLANK({CN}) && "
            f"{' && '.join(tests)})), DISTINCTCOUNTNOBLANK({CN}))")


MEASURES["0a66033bf9d0"] = ("# of Carriers", carriers_dax(), NUM)

CALC_DIMS = [
    ("Flight Types", "Deal Status",
     "=if([Flight Type]='Domestic, US Carriers Only', 'Open',\nif([Flight Type]='International, Foreign Carriers', 'Negotiating', 'Closed'))",
     "SWITCH([Flight Type], \"Domestic, US Carriers Only\", \"Open\", \"International, Foreign Carriers\", \"Negotiating\", \"Closed\")",
     "string"),
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
    "Dimension rows: each role also filters every dimension and the calendars to the keys its facts use, as "
    "QlikView's reduction does (Airlines 336 named members under ADMIN). The 12 flight rows without a carrier group / "
    "airline point at a placeholder member (key -1, null label) so the filtered dimensions keep them, as the null row "
    "QlikView shows. The script's null-key 'Unknown' members are not loaded: they associate with nothing in QlikView "
    "and would wrongly match blank keys in Power BI.",
    "Set analysis value modifiers use KEEPFILTERS: identical to QlikView with no selections (the parity baseline); with a "
    "slicer selection on the same field Power BI intersects where QlikView replaces the selection.",
    "Point-in-time sets (vSetYTD, vSetLYYTD, vSetMTD, vSetLYMTD, vSetPreviousMonth, vSetPreviousNMonth) are defined in "
    "..\\0.Includes\\SetVariables.txt, which is not in the repo; their definitions are reconstructed (see "
    "parity/models/<app>.overlay.json) and the measures implement the same reconstruction.",
    "Alternate states Group A / Group B -> disconnected 'Group A' / 'Group B' period tables used as slicers; the measures "
    "intersect the main selection with the group's periods ({[Group A] * $}).",
    "Calculated dimensions: the Aggr()/Class() carrier buckets -> disconnected segment tables; '# of Carriers' counts the "
    "carriers whose value falls in the segment at query time, so RLS and selections apply as in QlikView. The row-level "
    "Flight Type deal status -> calculated column on Flight Types.",
    "Dimensionality()/Pick(Dimensionality()+1, ...) -> ISINSCOPE() over the chart's dimension fields.",
    "$($(=eMetric)) -> SWITCH over SELECTEDVALUE('INLFED-1'[eMetric]); blank without a single Metric Name selected, "
    "like QlikView's empty expansion.",
]

NO_SECTION_ACCESS_DIMENSION_GAP = (
    "Dimension rows: no Section Access, so nothing is reduced (Main Data keeps the Employment Statistics rows; "
    "Airlines 337, Carrier Operating Region 8 as in QlikView). Null-key 'Unknown' members the script adds for null "
    "fact keys are not loaded: they associate with nothing in QlikView and would wrongly match blank keys in Power BI.")


def gaps() -> list[str]:
    out = [g.replace("'INLFED-1'", tname(CFG.metric_table)) for g in GAPS]
    if CFG.section_access:
        return out
    return [NO_SECTION_ACCESS_DIMENSION_GAP if g.startswith("Dimension rows:") else g for g in out
            if not g.startswith(("Section Access", "OMIT"))]


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
    md_steps = [f'Flight = Table.SelectColumns(fnReadParquet("{FLIGHT}"), {m_list(FLIGHT_COLS)})',
                f'Employment = Table.SelectColumns(fnReadParquet("{EMPLOYMENT}"), {m_list(EMPLOYMENT_COLS)})',
                "Combined = Table.Combine({Flight, Employment})"]
    if CFG.section_access:  # the placeholder member only exists so RLS-filtered dimensions keep null-key rows
        md_steps.append(f"Placeholder = Table.ReplaceValue(Combined, null, {NULL_KEY}, Replacer.ReplaceValue, "
                        f"{m_list(NULL_KEY_FIELDS)})")
    md_steps.append(f"Typed = Table.TransformColumnTypes({'Placeholder' if CFG.section_access else 'Combined'}, "
                    f"{m_types(md_cols)})")
    specs["Main Data"] = {"cols": md_cols, "m": m_let(md_steps, "Typed")}
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
                 f'Kept = Table.SelectRows(Source, each List.Contains(FactKeys, [#"{key}"]))']
        last = "Kept"
        if unknown:
            steps += [f'Missing = List.Difference(FactKeys, Table.Column(Kept, "{key}"))',
                      f'Unknown = Table.FromColumns({{Missing, List.Repeat({{"Unknown"}}, List.Count(Missing))}}, '
                      f'{m_list([key, labels[0]])})',
                      "Combined = Table.Combine({Kept, Unknown})"]
            last = "Combined"
        if key in NULL_KEY_FIELDS and CFG.section_access:
            steps.append(f'WithPlaceholder = Table.Combine({{{last}, #table({m_list([key, *labels])}, '
                         f'{{{{{", ".join([str(NULL_KEY)] + ["null"] * len(labels))}}}}})}})')
            last = "WithPlaceholder"
        steps.append(f"Typed = Table.TransformColumnTypes({last}, {m_types(cols)})")
        specs[name] = {"cols": cols, "m": m_let(steps, "Typed")}
    if CFG.section_access:
        specs["INLFED"] = {"cols": [("Flight Type", "string"), ("%FLIGHTTYPE", "string")], "m": m_let([
            "Source = #table(type table [#\"Flight Type\" = text, #\"%FLIGHTTYPE\" = text], {"
            + ", ".join(f'{{"{v}", "{k}"}}' for k, v in FLIGHT_TYPES.items()) + "})"], "Source")}
    specs[CFG.metric_table] = {"cols": [("Metric Name", "string"), ("eMetric", "string")], "m": m_let([
        "Source = #table(type table [#\"Metric Name\" = text, eMetric = text], {"
        + ", ".join(f'{{"{a}", "{b}"}}' for a, b in METRICS) + "})"], "Source")}
    for table, col, qlik, values, label, _ in SEGMENTS:
        if label:
            specs[table] = {"cols": [(col, "string"), ("Low", "int64")], "sort": {col: "Low"}, "qlik": {col: qlik},
                            "m": m_let([f'Source = Table.FromList({values}, Splitter.SplitByNothing(), {{"Low"}})',
                                        f'Labeled = Table.AddColumn(Source, "{col}", each {label})',
                                        f'Typed = Table.TransformColumnTypes(Labeled, {{{{"{col}", type text}}, {{"Low", Int64.Type}}}})'],
                                       "Typed")}
        else:
            specs[table] = {"cols": [(col, "int64")], "qlik": {col: qlik},
                            "m": m_let([f'Source = Table.FromList({values}, Splitter.SplitByNothing(), {{"{col}"}})',
                                        f'Typed = Table.TransformColumnTypes(Source, {{{{"{col}", Int64.Type}}}})'], "Typed")}
    for state in ("Group A", "Group B"):  # own column names: Qlik's calendar fields must resolve to Master Calendar
        gcols = cal_cols[:6]
        renames = "{" + ", ".join(f'{{"{n}", "{state} {n}"}}' for n, _ in gcols) + "}"
        specs[state] = {"cols": [(f"{state} {n}", t) for n, t in gcols], "m": m_let([
            f'Source = Table.SelectColumns(#"Master Calendar", {m_list(n for n, _ in gcols)})',
            f"Renamed = Table.RenameColumns(Source, {renames})"], "Renamed")}
    return specs


def write_table(path: Path, name: str, spec: dict, measures: list[dict], calc: list[tuple],
                slug: str | None = None):
    """spec: cols, m, optional sort / qlik / description (table) / descriptions (column -> text, e.g. COMMENT FIELDS)."""
    slug = slug or SLUG  # the app being built (build() rebinds SLUG), not the import-time default
    names = {n for n, _ in spec["cols"]}
    lines = [f"/// {spec['description']}"] if spec.get("description") else []
    lines += [f"table {tname(name)}", f"\tlineageTag: {tag(slug, name)}", ""]
    for mz in measures:
        lines += [f"\tmeasure {tname(mz['name'])} = {mz['dax']}"]
        if mz["fmt"]:
            lines.append(f"\t\tformatString: {mz['fmt']}")
        lines += [f"\t\tlineageTag: {tag(slug, name, 'm', mz['parity_key'])}", "",
                  f"\t\tannotation ParityKey = {mz['parity_key']}", f"\t\tannotation QlikExpression = {mz['qlik']}",
                  f"\t\tannotation QlikObjects = {', '.join(mz['kpis'])}", ""]
    for col, typ in spec["cols"]:
        dtype, _, fmt = TYPE_MAP[typ]
        if col in spec.get("descriptions", {}):
            lines.append(f"\t/// {spec['descriptions'][col]}")
        lines += [f"\tcolumn {tname(col)}", f"\t\tdataType: {dtype}"]
        sort = spec.get("sort", {}).get(col) or (f"{col}__num" if f"{col}__num" in names else None)
        if hidden_column(name, col, spec):
            lines.append("\t\tisHidden")
        if sort:
            lines.append(f"\t\tsortByColumn: {tname(sort)}")
        if fmt and col not in ("Period", "Year"):
            lines.append(f"\t\tformatString: {fmt}")
        lines += [f"\t\tlineageTag: {tag(slug, name, 'c', col)}",
                  f"\t\tsummarizeBy: {'sum' if col.startswith('#') else 'none'}", f"\t\tsourceColumn: {col}", "",
                  "\t\tannotation SummarizationSetBy = Automatic", ""]
        if col in spec.get("qlik", {}):
            qlik = spec["qlik"][col]
            lines[-1:-1] = [f"\t\tannotation ParityKey = {parity_key(qlik)}",
                            f"\t\tannotation QlikDimension = {' '.join(qlik.split())}"]
    for _, col, qlik, dax, typ in calc:
        lines += [f"\tcolumn {tname(col)} = {dax}", f"\t\tdataType: {typ}",
                  f"\t\tlineageTag: {tag(slug, name, 'c', col)}", "\t\tsummarizeBy: none", "",
                  f"\t\tannotation ParityKey = {parity_key(qlik)}",
                  f"\t\tannotation QlikDimension = {' '.join(qlik.split())}", ""]
    lines += [f"\tpartition {tname(name)} = m", "\t\tmode: import", "\t\tsource =", spec["m"], ""]
    fname = re.sub(r'[<>:"/\\|?*]', "_", name)
    (path / f"{fname}.tmdl").write_text("\n".join(lines), encoding="utf-8")


def hidden_column(name: str, col: str, spec: dict) -> bool:
    return (col.startswith("%") and name not in ("INLFED",)) or col.endswith("__num") or \
        (col == "Period" and name == "Main Data") or col in spec.get("sort", {}).values()


def relationships() -> list[tuple[str, str, str, str]]:
    rels = [("Main Data", key, name, key) for name, _, key, _, _ in DIMENSIONS]
    rels.append(("Main Data", "Period", "Master Calendar", "Period"))
    if CFG.section_access:
        rels.append(("Flight Types", "Flight Type", "INLFED", "Flight Type"))  # Section Access reduction path
    return rels


# QlikView chart type -> (Power BI visual, field role, measure role, max measures)
VISUALS = {
    "Line Chart": ("lineChart", "Category", "Y", None), "Radar Chart": ("lineChart", "Category", "Y", None),
    "Bar Chart": ("clusteredColumnChart", "Category", "Y", None),
    "Combo Chart": ("clusteredColumnChart", "Category", "Y", None),
    "Pie Chart": ("pieChart", "Category", "Y", 1), "Funnel Chart": ("funnel", "Category", "Y", 1),
    "Block Chart": ("treemap", "Group", "Values", 1), "Gauge Chart": ("gauge", None, "Y", 1),
    "Scatter Chart": ("scatterChart", "Category", None, 3),
    "Straight Table": ("tableEx", "Values", "Values", None), "Pivot Table": ("pivotTable", "Rows", "Values", None),
    "Mekko Chart": ("pivotTable", "Rows", "Values", None), "Grid Chart": ("pivotTable", "Rows", "Values", None),
}


def qvw_doc(manifest: dict) -> bytes:
    """The .qvw's document block (sheet and object definitions; script and inventory come from the manifest)."""
    return zlib.decompressobj().decompress((REPO / manifest["path"]).read_bytes()[23:])


def sheet_objects(manifest: dict, doc: bytes) -> dict[str, list[str]]:
    """Object ids per sheet id. Each sheet's definition (its caption, then Document\\<id>) is followed by the ids of
    the objects on it (linked objects appear on several sheets). Objects on no sheet are inside a container (the
    document block does not list container children readably): they go to the first sheet that has a container."""
    known = set(manifest["objects"]["ids"])
    out = {}
    for sh in manifest["sheets"]:
        out[sh["id"]] = []
        for m in re.finditer(re.escape(b"Document\\" + sh["id"].encode()), doc):
            before = re.findall(rb"[\x20-\x7e]{3,}", doc[max(0, m.start() - 120):m.start()])
            if not before or not sh["name"].startswith(before[-1].decode("latin-1")):
                continue
            for text in re.findall(rb"[\x20-\x7e]{3,}", doc[m.end():m.end() + 2000]):
                hit = max((k for k in known if text.decode("latin-1").startswith(k)), key=len, default=None)
                if not hit:
                    break
                out[sh["id"]].append(hit)
            break
    placed = {o for ids in out.values() for o in ids}
    host = next((sh for sh, ids in out.items() if any(o.startswith("CT") for o in ids)), manifest["sheets"][0]["id"])
    out[host] += [o for o in manifest["objects"]["ids"] if o not in placed and not o.startswith("SH")]
    return out


def list_box_captions(doc: bytes) -> dict[str, str]:
    """List box / multi box id -> caption. The manifest does not keep list box fields; in the .qvw's document block
    each box's definition starts with its caption (for a list box, normally its field name) right before its id."""
    out = {}
    for oid in sorted(set(re.findall(rb"Document\\((?:LB|MB)\d+)", doc))):
        m = re.search(rb"(?<![\\A-Za-z0-9])" + oid + rb"(?![0-9])", doc)
        strings = re.findall(rb"[\x20-\x7e]{3,}", doc[max(0, m.start() - 300):m.start()])
        out[oid.decode()] = strings[-1].decode("latin-1") if strings else ""
    return out


def report_sections(manifest: dict, specs: dict, measures: dict[str, dict]) -> tuple[list[dict], dict[str, str]]:
    """One page per sheet; returns the pages and the list / multi boxes that have no model field (id -> caption)."""
    fields = {}
    for name, spec in specs.items():
        for col, _ in spec["cols"]:
            if not hidden_column(name, col, spec):
                fields.setdefault(col, (name, col))
    fields.update({q: (t, col) for t, col, q, _, _ in CALC_DIMS})
    fields.update({q: (t, col) for t, col, q, _, _, _ in SEGMENTS})
    kpis = kpi_list(manifest)
    captions = {ch["id"].split(" ")[0]: ch.get("caption") or ch["id"].split(" \u2014 ", 1)[-1] for ch in manifest["charts"]}
    types = {ch["id"].split(" ")[0]: ch.get("type") for ch in manifest["charts"]}
    doc = qvw_doc(manifest)
    boxes = list_box_captions(doc)
    pages, unmapped = [], {}
    for sheet, object_ids in sheet_objects(manifest, doc).items():
        sheet_name = static_title(next(sh["name"] for sh in manifest["sheets"] if sh["id"] == sheet))
        visuals, slicers = [], []
        for oid in object_ids:
            if oid in boxes:
                if boxes[oid] in fields and fields[boxes[oid]] not in [r["Values"][0] for _, _, _, r, _ in slicers]:
                    slicers.append((oid, boxes[oid], "slicer", {"Values": [fields[boxes[oid]]]}, set()))
                elif boxes[oid] not in fields:
                    unmapped[oid] = boxes[oid]
                continue
            ks = [k for k in kpis if k["kpi"].split("#")[0] == oid]
            if not ks:
                continue
            grain = max(ks[0]["grains"], key=len)  # drill groups: deepest level; cyclic groups: first field
            dims = []
            for d in grain:
                if d not in fields:
                    raise SystemExit(f"{oid}: no model field for dimension {d!r}")
                dims.append(fields[d])
            names = list(dict.fromkeys(measures[k["parity_key"]]["name"] for k in ks))
            text = [mz["name"] for mz in measures.values() if mz["name"] in names and mz["fmt"] is None]
            visual, drole, mrole, most = VISUALS.get(types[oid], ("tableEx", "Values", "Values", None))
            if mrole not in ("Values",):  # text-valued measures (e.g. 'Carrier') cannot be plotted: tooltips
                names = [n for n in names if n not in text]
            if most and len(names) > most:
                visual, drole, mrole = "clusteredColumnChart", "Category", "Y"
            if not dims and visual not in ("gauge",):
                visual, drole, mrole = ("card", None, "Values") if len(names) == 1 else ("tableEx", None, "Values")
            roles = {drole: dims} if drole and dims else {}
            if visual == "scatterChart":
                roles.update({r: [("Main Data", n)] for r, n in zip(("X", "Y", "Size"), names)})
            else:
                roles.setdefault(mrole, []).extend(("Main Data", n) for n in names)
            if text and mrole != "Values":
                roles["Tooltips"] = [("Main Data", n) for n in text]
            visuals.append((oid, captions[oid], visual, roles, set(names) | set(text)))
        daxes = " ".join(mz["dax"] for mz in measures.values() if any(mz["name"] in v[4] for v in visuals))
        for state in ("Group A", "Group B"):  # the state's list boxes sit in containers: its period slicer
            if f"'{state}'" in daxes:
                slicers.append((f"{sheet}-{state}", f"{state} Year - Month", "slicer",
                                {"Values": [(state, f"{state} Year - Month")]}, set()))
        if not visuals:  # sheets of list boxes / table boxes only: the row-level table the slicers filter
            visuals.append((f"{sheet}-table", sheet_name, "tableEx",
                            {"Values": [fields["Carrier Group"], fields["Carrier Name"], ("Main Data", "# of Flights")]},
                            {"# of Flights"}))
        pages.append((sheet, sheet_name, slicers, visuals))
    # QlikView selections are global: every page gets a hidden synced copy of each list-box slicer it lacks, so a
    # selection made on any page filters all pages (Group A / B period slicers are per state, not copied).
    shared = list({s_[3]["Values"][0]: s_ for _, _, slicers, _ in pages for s_ in slicers
                   if s_[0] in boxes}.values())
    sections = []
    for ordinal, (sheet, sheet_name, slicers, visuals) in enumerate(pages):
        present = {s_[3]["Values"][0] for s_ in slicers}
        hidden = [(f"{s_[0]}_sync", *s_[1:]) for s_ in shared if s_[3]["Values"][0] not in present]
        sections.append({"name": "ReportSection" + tag(SLUG, "page", sheet).replace("-", "")[:20],
                         "displayName": sheet_name, "displayOption": 1, "ordinal": ordinal, "width": 1280,
                         "height": 720, "config": json.dumps({"QlikSheet": sheet}), "filters": "[]",
                         "visualContainers": visual_containers(sheet, slicers, visuals, hidden)})
    return sections, unmapped


def static_title(name: str) -> str:
    """A calculated sheet title (="'Details for ' & [Carrier Name]") as static text: 'Details for Carrier Name'."""
    if not name.startswith("="):
        return name
    text = re.sub(r"'([^']*)'|\[([^\]]*)\]", lambda m: m.group(1) if m.group(1) is not None else m.group(2), name[1:])
    return " ".join(text.replace("&", " ").split())


def grid(items: list, x0: int, width: int, cols: int) -> list[tuple]:
    rows = math.ceil(len(items) / cols)
    w, h = (width - 10 * (cols + 1)) // cols, (720 - 10 * (rows + 1)) // rows
    return [(item, x0 + 10 + (i % cols) * (w + 10), 10 + (i // cols) * (h + 10), w, h) for i, item in enumerate(items)]


def visual_containers(sheet: str, slicers: list[tuple], visuals: list[tuple], hidden: list[tuple] = ()) -> list[dict]:
    """Slicers in a left panel (up to 6 per column), the charts in a grid filling the rest of the page; hidden synced
    slicers are parked in a strip along the bottom edge."""
    panel = 170 * math.ceil(len(slicers) / 6) if slicers else 0
    placed = grid(slicers, 0, panel + 10, max(1, math.ceil(len(slicers) / 6))) if slicers else []
    placed += grid(visuals, panel, 1280 - panel, min(len(visuals), 3 if len(visuals) <= 6 else 4))
    placed += [(item, (i * 40) % 1240, 700, 40, 20) for i, item in enumerate(hidden)]
    hidden_ids = {h[0] for h in hidden}
    out = []
    for z, ((vid, title, visual, roles, measure_names), x, y, w, h) in enumerate(placed):
        aliases, select, projections = {}, [], {}
        for role, refs in roles.items():
            for table, col in refs:
                alias = aliases.setdefault(table, f"t{len(aliases)}")
                ref = f"{table}.{col}"
                kind = "Measure" if table == "Main Data" and col in measure_names else "Column"
                if ref not in {s_["Name"] for s_ in select}:
                    select.append({kind: {"Expression": {"SourceRef": {"Source": alias}}, "Property": col}, "Name": ref})
                projections.setdefault(role, []).append({"queryRef": ref})
        pos = {"x": x, "y": y, "z": z, "width": w, "height": h}
        config = {"name": tag(SLUG, "visual", sheet, vid), "layouts": [{"id": 0, "position": pos}],
                  "singleVisual": {"visualType": visual, "projections": projections, "prototypeQuery": {
                      "Version": 2, "From": [{"Name": a, "Entity": t, "Type": 0} for t, a in aliases.items()],
                      "Select": select}, "drillFilterOtherVisuals": True,
                      # QlikView selections are global: slicers on the same field are synced across pages
                      **({"syncGroup": {"groupName": select[0]["Name"], "fieldChanges": True, "filterChanges": True}}
                         if visual == "slicer" else {}),
                      **({"display": {"mode": "hidden"}} if vid in hidden_ids else {}),
                      # numeric fields (Period, Year) on a chart axis are categories, not a continuous scale
                      **({"objects": {"categoryAxis": [{"properties": {"axisType": {
                          "expr": {"Literal": {"Value": "'Categorical'"}}}}}]}}
                         if "Category" in roles and visual not in ("pieChart", "funnel", "scatterChart") else {}),
                      "vcObjects": {"title": [{"properties": {
                          "show": {"expr": {"Literal": {"Value": "true"}}},
                          "text": {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}}}}]}}}
        out.append({**pos, "config": json.dumps(config), "filters": "[]"})
    return out


def role_tmdl(user: str) -> str:
    values, omit = SECTION_ACCESS[user]
    allowed = sorted(FLIGHT_TYPES) if "*" in values else sorted(set(values))
    filt = "INLFED[%FLIGHTTYPE] IN {" + ", ".join(f'"{v}"' for v in allowed) + "}"
    lines = [f"role {tname(user)}", "\tmodelPermission: read", "", f"\ttablePermission INLFED = {filt}", ""]
    # QlikView's reduction also drops dimension rows no surviving fact row uses; relationships only filter
    # dimension -> fact, so each dimension gets its own filter on the keys of the role's facts.
    scope = "{" + ", ".join(f'"{FLIGHT_TYPES[v]}"' for v in allowed) + "}"
    keyed = [(name, key, key) for name, _, key, _, _ in DIMENSIONS if name != "Flight Types"]
    keyed += [("Master Calendar", "Period", "Period"), ("Group A", "Group A Period", "Period"),
              ("Group B", "Group B Period", "Period")]
    for table, col, key in keyed:
        lines += [f"\ttablePermission {tname(table)} = {c(table, col)} IN CALCULATETABLE(VALUES({m(key)}), "
                  f"'Flight Types'[Flight Type] IN {scope})", ""]
    if omit:
        lines += [f"\ttablePermission {MD}", "", f"\t\tcolumnPermission {tname(omit)} = none", ""]
    lines += [f"\tannotation QlikSectionAccess = USERID {user}; %FLIGHTTYPE {', '.join(values)}"
              + (f"; OMIT {omit}" if omit else ""), ""]
    return "\n".join(lines)


def build(data_root: str = DEFAULT_ROOT, cfg: AirlineApp = CH15) -> Path:
    global CFG, APP, SLUG
    CFG, APP, SLUG = cfg, cfg.app, cfg.slug
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = APPS / SLUG
    sm, rp = root / f"{SLUG}.SemanticModel", root / f"{SLUG}.Report"
    roles = SECTION_ACCESS if cfg.section_access else {}
    for d in (sm / "definition" / "tables", sm / "definition" / "roles", rp):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.tmdl"):
            f.unlink()
    if not roles:
        (sm / "definition" / "roles").rmdir()
    measures: dict[str, dict] = {}
    for k in kpi_list(manifest):
        pk = k["parity_key"]
        if pk not in MEASURES:
            raise SystemExit(f"{k['kpi']}: no measure for ParityKey {pk}: {k['expression']}")
        mz = measures.setdefault(pk, {"parity_key": pk, "name": MEASURES[pk][0],
                                      "dax": MEASURES[pk][1].replace("'INLFED-1'", tname(cfg.metric_table)),
                                      "fmt": MEASURES[pk][2], "kpis": [], "qlik": " ".join(k["expression"].split())})
        mz["kpis"].append(k["kpi"])
        for d in k["dims"]:
            if d.startswith("=") and d not in {x[2] for x in CALC_DIMS} | {x[2] for x in SEGMENTS}:
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
    for user in roles:
        (sm / "definition" / "roles" / f"{user}.tmdl").write_text(role_tmdl(user), encoding="utf-8")
    (sm / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n", encoding="utf-8")
    refs = "\n".join(f"ref table {tname(t)}" for t in specs) + "\n\n" + \
        "\n".join(f"ref role {tname(u)}" for u in roles)
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
    sections, unmapped_boxes = report_sections(manifest, specs, measures) if cfg.report_pages else ([
        {"name": "ReportSection", "displayName": "Page 1", "displayOption": 1, "ordinal": 0,
         "width": 1280, "height": 720, "config": "{}", "filters": "[]", "visualContainers": []}], {})
    (rp / "report.json").write_text(json.dumps({
        "config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
        "layoutOptimization": 0, "resourcePackages": [],
        "sections": sections}, indent=2) + "\n")
    (root / f"{SLUG}.pbip").write_text(json.dumps(
        {"version": "1.0", "artifacts": [{"report": {"path": f"{SLUG}.Report"}}], "settings": {"enableAutoRecovery": True}},
        indent=2) + "\n")
    (root / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    (root / "model.json").write_text(json.dumps(
        {"app": APP, "generated_by": "powerbi/tools/build_airline_base.py",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in measures.values()],
         "calculated_dimensions": [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q, "dax": d}
                                   for t, col, q, d, _ in CALC_DIMS]
                                  + [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q,
                                      "dax": "segment table + '# of Carriers'"} for t, col, q, _, _, _ in SEGMENTS],
         "roles": {u: {"flight_types": v, "omit": o} for u, (v, o) in roles.items()},
         **({"unmapped_list_boxes": unmapped_boxes} if cfg.report_pages else {}),
         "semantic_gaps": gaps() + ([
             "List boxes -> slicers on the field named by the box caption, on the page of the box's sheet (one per field "
             "and page). Boxes whose caption is no model field are not rebuilt (see unmapped_list_boxes): "
             + "; ".join(f"{k} {v!r}" for k, v in unmapped_boxes.items())
             + ". Their captions name no model field (multi boxes list several fields under one caption). Objects "
             "inside containers (on no sheet's object list) are placed on the first sheet with a container."]
             if cfg.report_pages else [])}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(specs)} tables, {len(rels) // 4} relationships, {len(roles)} roles, "
          f"{len(measures)} measures, {len(CALC_DIMS)} calculated columns")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", choices=[*AIRLINE_APPS, "all"], default="all")
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    args = ap.parse_args(argv)
    for name, cfg in AIRLINE_APPS.items():
        if args.app in (name, "all"):
            build(args.data_root, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
