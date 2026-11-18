"""Scaffold a PBIP (TMDL semantic model + empty report) for an app from its manifest.

  python powerbi/tools/scaffold_pbip.py --app "Chapter03__Solution_Chapter 3_Airline Operations"

Writes powerbi/apps/<Slug>/ following docs/CONVENTIONS.md: one table per Qlik table read
from Parquet through the shared fnReadParquet function, relationships from the %-keys,
and one measure per distinct KPI expression (annotated with its ParityKey) when the
expression translates mechanically to DAX. Only apps made of plain loads can be scaffolded
fully; for the rest the per-app migration writes the Power Query by hand.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "parity"))
import qlik_expr as q  # noqa: E402
from convert_sources import CATALOG, REPO  # noqa: E402
from harness import kpi_list, show  # noqa: E402
from qlik_script import plain_tables  # noqa: E402
from verify_conversion import catalog_table, resolve_source  # noqa: E402

POWERBI = REPO / "powerbi"
APPS = POWERBI / "apps"
NS = uuid.UUID("5d6f0c2e-8f43-4a8e-9f1c-6a1f3b9a2c10")
TYPE_MAP = {"int64": ("int64", "Int64.Type", "0"), "float64": ("double", "type number", "#,0.00"),
            "string": ("string", "type text", None), "date": ("dateTime", "type date", "yyyy-mm-dd"),
            "timestamp": ("dateTime", "type datetime", "yyyy-mm-dd hh:mm:ss")}


def slug(app: str) -> str:
    chapter, name = app.split("__", 1)
    name = re.sub(r"^Solution_(Chapter \d+_)?", "", name)
    return f"{chapter}_{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')}"


def tag(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def tname(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


def dcol(table: str, col: str) -> str:
    return f"'{table.replace(chr(39), chr(39) * 2)}'[{col.replace(']', ']]')}]"


def to_dax(node, field_table: dict[str, str]) -> str:
    """Mechanical Qlik -> DAX for plain aggregations and arithmetic; raises Unsupported otherwise."""
    if isinstance(node, q.Num):
        return str(int(node.value)) if node.value.is_integer() else repr(node.value)
    if isinstance(node, q.Unary) and node.op == "-":
        return f"-{to_dax(node.operand, field_table)}"
    if isinstance(node, q.BinOp) and node.op in "+-*/":
        a, b = to_dax(node.left, field_table), to_dax(node.right, field_table)
        return f"DIVIDE({a}, {b})" if node.op == "/" else f"({a} {node.op} {b})"
    if isinstance(node, q.Agg) and node.set_expr is None and node.total is None and isinstance(node.arg, q.FieldRef):
        f = node.arg.name
        if f not in field_table:
            raise q.Unsupported(f"field {f!r} not in model")
        col = dcol(field_table[f], f)
        if node.func == "count":
            return f"DISTINCTCOUNT({col})" if node.distinct else f"COUNT({col})"
        if node.func in ("sum", "avg", "min", "max") and not node.distinct:
            return {"sum": "SUM", "avg": "AVERAGE", "min": "MIN", "max": "MAX"}[node.func] + f"({col})"
    raise q.Unsupported("needs a hand-written DAX measure")


def m_partition(path: str, cols: list[tuple[str, str, str]]) -> str:
    """cols: (source column, model column, M type)."""
    sel = ", ".join(f'"{s}"' for s, _, _ in cols)
    renames = [(s, n) for s, n, _ in cols if s != n]
    types = ", ".join(f'{{"{n}", {t}}}' for _, n, t in cols)
    steps = [f'Source = fnReadParquet("{path}")', f"Selected = Table.SelectColumns(Source, {{{sel}}})"]
    last = "Selected"
    if renames:
        steps.append(f"Renamed = Table.RenameColumns({last}, {{{', '.join(f'{{\"{s}\", \"{n}\"}}' for s, n in renames)}}})")
        last = "Renamed"
    steps.append(f"Typed = Table.TransformColumnTypes({last}, {{{types}}})")
    body = ",\n".join("\t\t\t\t    " + s for s in steps)
    return f"\t\t\t\tlet\n{body}\n\t\t\t\tin\n\t\t\t\t    Typed"


def scaffold(app: str, data_root: str) -> Path:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{app}.json").read_text())
    catalog = json.loads(CATALOG.read_text())
    script = (POWERBI / "inventory" / manifest["script"]["file"]).read_text(encoding="utf-8")
    plain = plain_tables(script)
    tables = [t for t in manifest["data_model"]["tables"] if not t["name"].startswith("$$")]
    missing = [t["name"] for t in tables if t["name"] not in plain]
    if missing:
        raise SystemExit(f"{app}: tables {missing} are built by script transformations; scaffold them by hand")
    s = slug(app)
    root = APPS / s
    sm = root / f"{s}.SemanticModel"
    rp = root / f"{s}.Report"
    (sm / "definition" / "tables").mkdir(parents=True, exist_ok=True)
    rp.mkdir(parents=True, exist_ok=True)

    keys = {k["field"] for k in manifest["data_model"]["key_fields"]}
    facts = set(manifest["pbip_plan"]["fact_tables"])
    model_tables, field_table = {}, {}
    for t in tables:
        load = plain[t["name"]]
        ct = catalog_table(catalog, *resolve_source(manifest, load))
        types = {c["name"]: c["type"] for c in ct["columns"]}
        sort_by = {c["name"]: c["sort_by"] for c in ct["columns"] if c.get("sort_by")}
        cols = []
        for f in load.output_fields:
            cols.append((f.source_name, f.name, types[f.source_name]))
            if f.source_name in sort_by:  # QlikView dual (e.g. Month 'Jan' = 1): keep its number to sort by
                cols.append((sort_by[f.source_name], f"{f.name}__num", "float64"))
        model_tables[t["name"]] = {"parquet": ct["parquet"].split("powerbi/data/parquet/", 1)[1], "cols": cols}
        for _, n, _ in cols:
            if n not in keys or t["name"] in facts:
                field_table.setdefault(n, t["name"])

    measures, skipped, used = {}, [], set()
    for k in kpi_list(manifest):
        if k["parity_key"] in measures:
            measures[k["parity_key"]]["kpis"].append(k["kpi"])
            continue
        try:
            dax = to_dax(q.parse(k["expression"]), field_table)
        except q.Unsupported as e:
            skipped.append({"kpi": k["kpi"], "label": k["label"], "expression": k["expression"], "reason": str(e)})
            continue
        name = k["label"] if k["label"] and k["label"] != "(no label)" else k["kpi"]
        all_cols = {n for t in model_tables.values() for _, n, _ in t["cols"]}
        if name in used or name in all_cols:
            name = f"{name} ({k['kpi']})"
        used.add(name)
        fmt = "0.00%" if "/" in k["expression"] and "1000" not in k["expression"] else "#,0"
        home = next(iter(facts)) if facts else tables[0]["name"]
        measures[k["parity_key"]] = {"name": name, "dax": dax, "kpis": [k["kpi"]], "fmt": fmt, "home": home,
                                     "qlik": " ".join(k["expression"].split())}

    for name, t in model_tables.items():
        lines = [f"table {tname(name)}", f"\tlineageTag: {tag(s, name)}", ""]
        for key, mz in measures.items():
            if mz["home"] != name:
                continue
            lines += [f"\tmeasure {tname(mz['name'])} = {mz['dax']}", f"\t\tformatString: {mz['fmt']}",
                      f"\t\tlineageTag: {tag(s, name, 'm', key)}", "",
                      f"\t\tannotation ParityKey = {key}", f"\t\tannotation QlikExpression = {mz['qlik']}",
                      f"\t\tannotation QlikObjects = {', '.join(mz['kpis'])}", ""]
        names = {n for _, n, _ in t["cols"]}
        for src, col, typ in t["cols"]:
            dtype, _, fmt = TYPE_MAP[typ]
            summarize = "sum" if col.startswith("#") else "none"
            lines += [f"\tcolumn {tname(col)}", f"\t\tdataType: {dtype}"]
            if col in keys or col.endswith("__num"):
                lines.append("\t\tisHidden")
            if f"{col}__num" in names:
                lines.append(f"\t\tsortByColumn: {tname(col + '__num')}")
            if fmt:
                lines.append(f"\t\tformatString: {fmt}")
            lines += [f"\t\tlineageTag: {tag(s, name, 'c', col)}", f"\t\tsummarizeBy: {summarize}",
                      f"\t\tsourceColumn: {col}", "", "\t\tannotation SummarizationSetBy = Automatic", ""]
        mcols = [(c, n, TYPE_MAP[ty][1]) for c, n, ty in t["cols"]]
        lines += [f"\tpartition {tname(name)} = m", "\t\tmode: import", "\t\tsource =",
                  m_partition(t["parquet"], mcols), ""]
        fname = re.sub(r'[<>:"/\\|?*]', "_", name)
        (sm / "definition" / "tables" / f"{fname}.tmdl").write_text("\n".join(lines), encoding="utf-8")

    rels = []
    for r in manifest["pbip_plan"]["relationships_from_keys"]:
        key, (a, b) = r["key"], r["tables"][:2]
        many, one = (a, b) if a in facts else (b, a)
        rels += [f"relationship {tag(s, 'rel', key)}", f"\tfromColumn: {tname(many)}.{tname(key)}",
                 f"\ttoColumn: {tname(one)}.{tname(key)}", ""]
    (sm / "definition" / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")
    (sm / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n", encoding="utf-8")
    refs = "\n".join(f"ref table {tname(t)}" for t in model_tables)
    (sm / "definition" / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        f"\tannotation PBI_QueryOrder = {json.dumps(['DataRoot', 'fnReadParquet', *model_tables])}\n\n{refs}\n",
        encoding="utf-8")
    (sm / "definition" / "expressions.tmdl").write_text(
        f'expression DataRoot = "{data_root}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f"\tlineageTag: {tag(s, 'DataRoot')}\n\n"
        "expression fnReadParquet =\n"
        "\t\t(relativePath as text) as table =>\n"
        "\t\tlet\n"
        '\t\t    FullPath = DataRoot & Text.Replace(relativePath, "/", "\\"),\n'
        "\t\t    Source = Parquet.Document(File.Contents(FullPath))\n"
        "\t\tin\n"
        "\t\t    Source\n"
        f"\tlineageTag: {tag(s, 'fnReadParquet')}\n", encoding="utf-8")
    (sm / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2) + "\n")
    (rp / "definition.pbir").write_text(json.dumps(
        {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{s}.SemanticModel"}}}, indent=2) + "\n")
    (rp / "report.json").write_text(json.dumps({
        "config": json.dumps({"version": "5.59", "themeCollection": {}, "activeSectionIndex": 0}),
        "layoutOptimization": 0, "resourcePackages": [],
        "sections": [{"name": "ReportSection", "displayName": "Page 1", "displayOption": 1, "ordinal": 0,
                      "width": 1280, "height": 720, "config": "{}", "filters": "[]", "visualContainers": []}]},
        indent=2) + "\n")
    (root / f"{s}.pbip").write_text(json.dumps(
        {"version": "1.0", "artifacts": [{"report": {"path": f"{s}.Report"}}], "settings": {"enableAutoRecovery": True}},
        indent=2) + "\n")
    (root / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    (root / "scaffold.json").write_text(json.dumps(
        {"app": app, "generated_by": "powerbi/tools/scaffold_pbip.py",
         "measures": [{"name": m["name"], "parity_key": k, "kpis": m["kpis"], "dax": m["dax"]} for k, m in measures.items()],
         "needs_hand_written_dax": skipped}, indent=1, ensure_ascii=False) + "\n")
    print(f"{show(root)}: {len(model_tables)} tables, {len(rels) // 4} relationships, "
          f"{len(measures)} measures, {len(skipped)} KPI expressions need hand-written DAX")
    return root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", required=True)
    ap.add_argument("--data-root", default="C:\\QlikView-for-Developers\\powerbi\\data\\parquet\\",
                    help="value of the DataRoot parameter (folder holding the converted Parquet)")
    args = ap.parse_args(argv)
    scaffold(args.app, args.data_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
