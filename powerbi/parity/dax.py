"""Generate the DAX queries that produce the Power BI side of the parity comparison.

Reads the app's TMDL (``*.SemanticModel/definition/tables/*.tmdl``): a KPI maps to the
measure whose ``annotation ParityKey`` equals the KPI's parity key (see harness.parity_key),
and a Qlik field maps to the column whose ``sourceColumn`` (or name) is that field.
Each expected result id gets one query:
  grand total -> EVALUATE ROW("value", [Measure])
  grain       -> EVALUATE SUMMARIZECOLUMNS('T'[c1], 'T'[c2], "value", [Measure])
  table check -> EVALUATE GROUPBY('T', 'T'[c1], 'T'[c2], "__rows", SUMX(CURRENTGROUP(), 1))
                 (rows of the Qlik table per field combination; when the Power BI table holds more
                 columns than the Qlik table, e.g. a GENERIC LOAD pivoted into one table, only rows
                 where one of the Qlik table's non-key fields is not blank)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from harness import DAX, load_expected, show


def unquote_tmdl(name: str) -> str:
    name = name.strip()
    return name[1:-1].replace("''", "'") if name.startswith("'") and name.endswith("'") else name


def dax_table(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def dax_col(table: str, col: str) -> str:
    return f"{dax_table(table)}[{col.replace(']', ']]')}]"


def read_tmdl(pbip: Path) -> dict:
    model = {"columns": [], "measures": []}
    tables_dir = next(pbip.glob("*.SemanticModel")) / "definition" / "tables"
    for f in sorted(tables_dir.glob("*.tmdl")):
        table, current = None, None
        for line in f.read_text(encoding="utf-8").splitlines():
            if m := re.match(r"^table (.+)$", line):
                table = unquote_tmdl(m.group(1))
            elif m := re.match(r"^\tcolumn ('(?:[^']|'')*'|[^=\s]+)", line):
                current = {"table": table, "name": unquote_tmdl(m.group(1)), "source": None, "hidden": False}
                model["columns"].append(current)
            elif m := re.match(r"^\tmeasure ('(?:[^']|'')*'|[^=\s]+)\s*=", line):
                current = {"table": table, "name": unquote_tmdl(m.group(1)), "keys": []}
                model["measures"].append(current)
            elif re.match(r"^\t\S", line):
                current = None
            elif current is not None and (m := re.match(r"^\t\tsourceColumn:\s*(.+)$", line)):
                current["source"] = m.group(1).strip()
            elif current is not None and re.match(r"^\t\tisHidden\s*$", line):
                current["hidden"] = True
            elif current is not None and (m := re.match(r"^\t\tannotation ParityKey\s*=\s*(\S+)", line)):
                current.setdefault("keys", []).append(m.group(1))
    return model


def column_for(model: dict, field: str) -> dict | None:
    hits = [c for c in model["columns"] if (c["source"] or c["name"]) == field or c["name"] == field]
    hits.sort(key=lambda c: c["hidden"])
    return hits[0] if hits else None


def table_query(model: dict, fields: list[str], keys: set[str]) -> tuple[str | None, str | None]:
    cols = [column_for(model, f) for f in fields]
    if None in cols:
        return None, f"no column for {[f for f, c in zip(fields, cols) if c is None]}"
    tables = {c["table"] for c in cols}
    if len(tables) != 1:
        return None, f"fields are spread over Power BI tables {sorted(tables)}"
    table = tables.pop()
    src = dax_table(table)
    others = {c["name"] for c in model["columns"] if c["table"] == table and not c["name"].endswith("__num")}
    if others - {c["name"] for c in cols}:
        attrs = [c for f, c in zip(fields, cols) if f not in keys] or cols
        cond = " || ".join(f"NOT ISBLANK({dax_col(table, c['name'])})" for c in attrs)
        src = f"FILTER({src}, {cond})"
    group = ", ".join(dax_col(table, c["name"]) for c in cols)
    return f'EVALUATE GROUPBY({src}, {group}, "__rows", SUMX(CURRENTGROUP(), 1))', None


def write_queries(app: str, pbip: Path) -> str:
    expected = load_expected(app)
    model = read_tmdl(pbip)
    by_key: dict[str, dict] = {}
    for m in model["measures"]:
        for k in m.get("keys", []):
            if k in by_key:
                raise ValueError(f"ParityKey {k} is on two measures: {by_key[k]['name']!r} and {m['name']!r}")
            by_key[k] = m
    queries, unmapped = [], []
    keys = set(expected.get("key_fields", []))
    for k in expected["kpis"]:
        if k.get("kind") == "table" and k["status"] == "ok":
            for r in k["results"]:
                query, reason = table_query(model, r["grain"], keys)
                if query:
                    queries.append({"id": r["id"], "measure": None, "grain": r["grain"], "query": query})
                else:
                    unmapped.append({"id": r["id"], "reason": reason})
            continue
        measure = by_key.get(k["parity_key"])
        if k["status"] != "ok":
            continue
        if not measure:
            unmapped.append({"kpi": k["kpi"], "reason": f"no measure with ParityKey {k['parity_key']}"})
            continue
        for r in k["results"]:
            cols = [column_for(model, f) for f in r["grain"]]
            if None in cols:
                unmapped.append({"id": r["id"], "reason": f"no column for {r['grain']}"})
                continue
            mref = f"[{measure['name'].replace(']', ']]')}]"
            if not cols:
                query = f'EVALUATE ROW("value", {mref})'
            else:
                group = ", ".join(dax_col(c["table"], c["name"]) for c in cols)
                query = f'EVALUATE SUMMARIZECOLUMNS({group}, "value", {mref})'
            queries.append({"id": r["id"], "measure": measure["name"], "grain": r["grain"], "query": query})
    DAX.mkdir(exist_ok=True)
    out = DAX / f"{app}.queries.json"
    out.write_text(json.dumps({"app": app, "pbip": show(pbip), "queries": queries,
                               "unmapped": unmapped}, indent=1, ensure_ascii=False) + "\n")
    return f"{len(queries)} DAX queries, {len(unmapped)} unmapped -> {show(out)}"
