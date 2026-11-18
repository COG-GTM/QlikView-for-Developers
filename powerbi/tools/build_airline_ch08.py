"""Generate the Chapter 08 Airline Operations PBIP, derived from the Chapter 15 base model.

Chapter 08's script is a subset of Chapter 15's: plain loads of Data Files/ (no WHERE Exists, master calendar,
employment statistics, inline tables or Section Access) plus the transformed [Aircraft Types] (ApplyMap, LEFT JOIN,
CONCATENATE), and COMMENT TABLES / FIELDS from Comments.xls. Measures and calculated columns are taken from
build_airline_base.py by ParityKey, keeping only those this app's charts use; build() fails if one is missing.

    python powerbi/tools/build_airline_ch08.py [--data-root C:\\path\\to\\powerbi\\data\\parquet\\]
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

APP = "Chapter08__Solution_Chapter 8_Airline Operations"
SLUG = "Chapter08_Airline_Operations"
PARQUET = POWERBI / "data" / "parquet"
FLIGHT = "Data Files/QVDs/Flight Data.parquet"
BASE = "Data Files/CSVs/Aircraft_Base_File.parquet"
GROUPS = "Data Files/CSVs/Aircraft_Group.parquet"
UPDATE = "Data Files/CSVs/Aircraft_2010_Update.parquet"
MANUFACTURERS = "Data Files/CSVs/Aircraft_Manufacturers.parquet"
COMMENTS = "Data Files/Excel/Comments/{}.parquet"

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
    "Destination Country", "Year", "Period", "Quarter", "Month (#)", "Month", "From - To Airport Code",
    "From - To Airport ID", "From - To City", "From - To State Code", "From - To State"]

# (table, parquet, key, label columns): plain LOADs, every row kept
DIMENSIONS = [
    ("Carrier Groups", "Data Files/QVDs/Carrier Groups.parquet", "%Carrier Group ID", ["Carrier Group"]),
    ("Airlines", "Data Files/QVDs/Airlines.parquet", "%Airline ID", ["Airline"]),
    ("Carrier Operating Region", "Data Files/QVDs/Carrier Operating Region.parquet", "%Region Code",
     ["Carrier's Operating Region"]),
    ("Flight Types", "Data Files/QVDs/Flight Types.parquet", "%Datasource ID", ["Flight Type"]),
    ("Distance Groups", "Data Files/QVDs/Distance Groups.parquet", "%Distance Group ID", ["Distance Interval"]),
    ("Origin Airports", "Data Files/MDBs/Dimension Tables/Origin Airports.parquet", "%Origin Airport ID",
     ["Origin Airport"]),
    ("Destination Airports", "Data Files/MDBs/Dimension Tables/Destination Airports.parquet",
     "%Destination Airport ID", ["Destination Airport"]),
    ("Origin Markets", "Data Files/CSVs/Origin Markets.parquet", "%Origin Airport Market ID", ["Origin Market"]),
    ("Destination Markets", "Data Files/CSVs/Destination Markets.parquet", "%Destination Airport Market ID",
     ["Destination Market"]),
]
AIRCRAFT = "Aircraft Types"
AIRCRAFT_KEY = "%Aircraft Type ID"
# Aircraft_Base_File.csv / Aircraft_2010_Update.csv field -> Qlik alias
AIRCRAFT_ALIASES = [("AC_TYPEID", AIRCRAFT_KEY), ("SSD_NAME", "Aircraft Name"),
                    ("MANUFACTURER", "Aircraft Manufacturer"), ("LONG_NAME", "Aircraft Name Full"),
                    ("SHORT_NAME", "Aircraft Name Abbreviated"), ("BEGIN_DATE", "Aircraft Begin Date"),
                    ("END_DATE", "Aircraft End Date")]

GAPS = [
    "Origin / Destination Airports: the repo's Dimension Tables.mdb holds 6,209 airports each; the .qvw was reloaded "
    "from an older .mdb with 2,104 / 2,169 (inventory/row_count_exceptions.json). The repo tables are supersets of "
    "every airport ID Main Data uses, so measures are unaffected; only unassociated airport rows differ.",
    "IF '$(vLoadMainData)' = 'Y' conditional load: the script always sets 'Y'; Main Data is always loaded.",
    "STORE [Aircraft Types] INTO 'Aircraft Types Transformed.qvd' is an ETL side effect and is not migrated.",
    "COMMENT TABLES / COMMENT FIELDS USING Comments.xls -> TMDL descriptions on the table and on every column of that "
    "name (QlikView comments a field in all tables).",
    "MAPPING LOAD + ApplyMap('Map_Manufacturer_Country', MANUFACTURER, 'Unknown') -> Table.NestedJoin LeftOuter "
    "with 'Unknown' for unmatched manufacturers.",
    "SubField(AC_GROUPNAME, ', ', 2) for a group name without a second part ('Helicopter/Stol') -> null.",
    "Month (Flight Data dual) -> text column sorted by the hidden Month__num.",
    "Calculated dimension (Flight Type deal status) -> calculated column 'Deal Status' on Flight Types.",
    "Synthetic keys ($$SysTable 11-13) are not reproduced: every dimension joins Main Data on its one % key.",
    "QlikView-only sheet objects (multi boxes, current selections, bookmark object, buttons, search object, container, "
    "statistics box, text objects) and chart layout are not migrated; the report has one empty page.",
]


def comments() -> tuple[dict[str, str], dict[str, str]]:
    """COMMENT TABLES / FIELDS USING Map_Table_Comments / Map_Field_Comments (first row per name, like a mapping)."""
    out = []
    for sheet, key in (("Tables", "TableName"), ("Fields", "FieldName")):
        path = PARQUET / COMMENTS.format(sheet)
        if not path.exists():
            raise SystemExit(f"{show(path)} missing: run powerbi/tools/convert_sources.py first")
        df = pd.read_parquet(path).dropna(subset=[key]).drop_duplicates(key)
        out.append({str(k): " ".join(str(v).split()) for k, v in zip(df[key], df["Comment"]) if pd.notna(v)})
    return out[0], out[1]


def aircraft_m(types: dict) -> tuple[list[tuple[str, str]], str]:
    base_cols = [s for s, _ in AIRCRAFT_ALIASES]
    renames = "{" + ", ".join(f'{{"{s}", "{t}"}}' for s, t in AIRCRAFT_ALIASES) + "}"
    country = "Aircraft Manufacturer Country"
    cols = [(AIRCRAFT_KEY, types[BASE]["AC_TYPEID"]), ("Aircraft Name", "string"), ("Aircraft Manufacturer", "string"),
            (country, "string"), ("Aircraft Name Full", "string"), ("Aircraft Name Abbreviated", "string"),
            ("Aircraft Begin Date", types[BASE]["BEGIN_DATE"]), ("Aircraft End Date", types[BASE]["END_DATE"]),
            ("Aircraft Age Classification", "string"), ("Aircraft Engine Type", "string"),
            ("Aircraft Number Of Engines", "string")]

    def apply_map(src: str, dst: str) -> list[str]:
        return [f'{dst}Joined = Table.NestedJoin({src}, {{"Aircraft Manufacturer"}}, Manufacturers, {{"Company"}}, '
                f'"Map", JoinKind.LeftOuter)',
                f'{dst}Mapped = Table.ExpandTableColumn({dst}Joined, "Map", {{"Country"}}, {{"{country}"}})',
                f'{dst} = Table.ReplaceValue({dst}Mapped, null, "Unknown", Replacer.ReplaceValue, {{"{country}"}})']

    def sub_field(n: int) -> str:
        return (f'each if [AC_GROUPNAME] = null then null else let Parts = Text.Split([AC_GROUPNAME], ", ") in '
                f'if List.Count(Parts) >= {n} then Parts{{{n - 1}}} else null')
    steps = [
        "// Map_Manufacturer_Country: MAPPING LOAD Company, Country (first row per Company)",
        f'Manufacturers = Table.Distinct(Table.SelectColumns(fnReadParquet("{MANUFACTURERS}"), {{"Company", "Country"}}), '
        '{"Company"})',
        f'Base = Table.SelectColumns(fnReadParquet("{BASE}"), {m_list(base_cols[:1] + ["AC_GROUP"] + base_cols[1:])})',
        f'BaseRenamed = Table.RenameColumns(Base, {renames[:-1]}, {{"AC_GROUP", "%Aircraft Group Type"}}}})',
        *apply_map("BaseRenamed", "BaseCountry"),
        'BaseAged = Table.AddColumn(BaseCountry, "Aircraft Age Classification", each if [Aircraft Begin Date] <> null '
        'and Date.Year([Aircraft Begin Date]) < 1990 then "Classic" else "Current")',
        "// LEFT JOIN Aircraft_Group.csv on [%Aircraft Group Type], then DROP FIELD [%Aircraft Group Type]",
        f'Groups = Table.SelectColumns(fnReadParquet("{GROUPS}"), '
        '{"Aircraft Group ID", "Aircraft Engine Type", "Aircraft Number Of Engines"})',
        'GroupJoined = Table.NestedJoin(BaseAged, {"%Aircraft Group Type"}, Groups, {"Aircraft Group ID"}, "Group", '
        "JoinKind.LeftOuter)",
        'GroupExpanded = Table.ExpandTableColumn(GroupJoined, "Group", {"Aircraft Engine Type", '
        '"Aircraft Number Of Engines"})',
        'BaseFinal = Table.RemoveColumns(GroupExpanded, {"%Aircraft Group Type"})',
        "// CONCATENATE the 2010 update: engine type / count from SubField(AC_GROUPNAME, ', ', 1 / 2), all 'Current'",
        f'Update = Table.SelectColumns(fnReadParquet("{UPDATE}"), {m_list(base_cols[:1] + ["AC_GROUPNAME"] + base_cols[1:])})',
        f"UpdateRenamed = Table.RenameColumns(Update, {renames})",
        f'UpdateEngine = Table.AddColumn(UpdateRenamed, "Aircraft Engine Type", {sub_field(1)})',
        f'UpdateEngines = Table.AddColumn(UpdateEngine, "Aircraft Number Of Engines", {sub_field(2)})',
        *apply_map("UpdateEngines", "UpdateCountry"),
        'UpdateAged = Table.AddColumn(UpdateCountry, "Aircraft Age Classification", each "Current")',
        'UpdateFinal = Table.RemoveColumns(UpdateAged, {"AC_GROUPNAME"})',
        "Combined = Table.Combine({BaseFinal, UpdateFinal})",
        f"Selected = Table.SelectColumns(Combined, {m_list(n for n, _ in cols)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(cols)})"]
    return cols, re.sub(r"(//[^\n]*),\n", r"\1\n", m_let(steps, "Typed"))


def table_specs(types: dict) -> dict[str, dict]:
    md_cols = [(x, types[FLIGHT][x]) for x in FLIGHT_COLS]
    md_cols.insert(FLIGHT_COLS.index("Month") + 1, ("Month__num", types[FLIGHT]["Month__num"]))
    specs = {"Main Data": {"cols": md_cols, "m": m_let([
        f'Source = fnReadParquet("{FLIGHT}")',
        f"Selected = Table.SelectColumns(Source, {m_list(n for n, _ in md_cols)})",
        f"Typed = Table.TransformColumnTypes(Selected, {m_types(md_cols)})"], "Typed")}}
    for name, path, key, labels in DIMENSIONS[:4]:
        specs[name] = plain_spec(types, path, [key, *labels])
    cols, m = aircraft_m(types)
    specs[AIRCRAFT] = {"cols": cols, "m": m}
    for name, path, key, labels in DIMENSIONS[4:]:
        specs[name] = plain_spec(types, path, [key, *labels])
    return specs


def plain_spec(types: dict, path: str, names: list[str]) -> dict:
    cols = [(x, types[path][x]) for x in names]
    return {"cols": cols, "m": m_let([f'Source = fnReadParquet("{path}")',
                                      f"Selected = Table.SelectColumns(Source, {m_list(names)})",
                                      f"Typed = Table.TransformColumnTypes(Selected, {m_types(cols)})"], "Typed")}


def description(text: str | None, indent: str) -> list[str]:
    return [f"{indent}/// {text}"] if text else []


def write_table(path: Path, name: str, spec: dict, measures: list[dict], calc: list[tuple],
                table_comments: dict, field_comments: dict):
    names = {n for n, _ in spec["cols"]}
    lines = description(table_comments.get(name), "") + [f"table {tname(name)}", f"\tlineageTag: {tag(SLUG, name)}", ""]
    for mz in measures:
        lines += [f"\tmeasure {tname(mz['name'])} = {mz['dax']}"]
        if mz["fmt"]:
            lines.append(f"\t\tformatString: {mz['fmt']}")
        lines += [f"\t\tlineageTag: {tag(SLUG, name, 'm', mz['parity_key'])}", "",
                  f"\t\tannotation ParityKey = {mz['parity_key']}", f"\t\tannotation QlikExpression = {mz['qlik']}",
                  f"\t\tannotation QlikObjects = {', '.join(mz['kpis'])}", ""]
    for col, typ in spec["cols"]:
        dtype, _, fmt = TYPE_MAP[typ]
        lines += description(field_comments.get(col), "\t") + [f"\tcolumn {tname(col)}", f"\t\tdataType: {dtype}"]
        if col.startswith("%") or col.endswith("__num"):
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
    rels = [("Main Data", key, name, key) for name, _, key, _ in DIMENSIONS]
    rels.insert(4, ("Main Data", AIRCRAFT_KEY, AIRCRAFT, AIRCRAFT_KEY))
    return rels


def build(data_root: str = DEFAULT_ROOT) -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{APP}.json").read_text())
    root = APPS / SLUG
    sm, rp = root / f"{SLUG}.SemanticModel", root / f"{SLUG}.Report"
    for d in (sm / "definition" / "tables", rp):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.tmdl"):
            f.unlink()
    measures: dict[str, dict] = {}
    calc_dims = []
    for k in kpi_list(manifest):
        pk = k["parity_key"]
        if pk not in MEASURES:
            raise SystemExit(f"{k['kpi']}: no measure for ParityKey {pk}: {k['expression']}")
        name, dax, fmt = MEASURES[pk]
        mz = measures.setdefault(pk, {"parity_key": pk, "name": name, "dax": dax, "fmt": fmt, "kpis": [],
                                      "qlik": " ".join(k["expression"].split())})
        mz["kpis"].append(k["kpi"])
        for d in k["dims"]:
            if d.startswith("="):
                hit = next((x for x in CALC_DIMS if x[2] == d), None)
                if not hit:
                    raise SystemExit(f"{k['kpi']}: no calculated column for dimension {d!r}")
                if hit not in calc_dims:
                    calc_dims.append(hit)
    refs = {r for mz in measures.values() for r in re.findall(r"(?<!')\[([^\]]+)\]", mz["dax"])
            if not any(r == c for c in FLIGHT_COLS)}
    if missing := refs - {mz["name"] for mz in measures.values()}:
        raise SystemExit(f"measures reference measures this app does not have: {sorted(missing)}")
    specs = table_specs(catalog_types())
    table_comments, field_comments = comments()
    for name, spec in specs.items():
        write_table(sm / "definition" / "tables", name, spec,
                    list(measures.values()) if name == "Main Data" else [],
                    [x for x in calc_dims if x[0] == name], table_comments, field_comments)
    rels = []
    for ft, fc, tt, tc in relationships():
        rels += [f"relationship {tag(SLUG, 'rel', ft, fc, tt)}", f"\tfromColumn: {tname(ft)}.{tname(fc)}",
                 f"\ttoColumn: {tname(tt)}.{tname(tc)}", ""]
    (sm / "definition" / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")
    (sm / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n", encoding="utf-8")
    refs_tmdl = "\n".join(f"ref table {tname(t)}" for t in specs)
    order = ["DataRoot", "fnReadParquet", *specs]
    (sm / "definition" / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        f"\tannotation PBI_QueryOrder = {json.dumps(order)}\n\n{refs_tmdl}\n", encoding="utf-8")
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
        {"app": APP, "generated_by": "powerbi/tools/build_airline_ch08.py",
         "derived_from": "powerbi/tools/build_airline_base.py (Chapter 15 base model)",
         "measures": [{"name": x["name"], "parity_key": x["parity_key"], "kpis": x["kpis"], "dax": x["dax"]}
                      for x in measures.values()],
         "calculated_dimensions": [{"table": t, "column": col, "parity_key": parity_key(q), "qlik": q, "dax": d}
                                   for t, col, q, d, _ in calc_dims],
         "descriptions": {"tables": table_comments, "fields": field_comments},
         "semantic_gaps": GAPS}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(specs)} tables, {len(rels) // 4} relationships, {len(measures)} measures, "
          f"{len(calc_dims)} calculated columns")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    build(ap.parse_args(argv).data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
