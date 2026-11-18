"""Verify the Parquet conversion.

1. Integrity: every Parquet table has exactly the source's own row count (QVD header
   NoOfRecords, Access table rows, sheet/CSV data rows) and the source file still has the
   sha256 recorded in catalog.json.
2. Inventory: for every app manifest, every Qlik table that the recovered load script builds
   with one plain LOAD/SELECT of one source (no WHERE, JOIN, CONCATENATE, DISTINCT, ...) must
   have the same row count in Parquet as in the inventory (the row count QlikView stored in
   the .qvw at its last reload). Tables built by transformations are listed as "derived":
   their counts are reproduced by that app's source model (powerbi/parity/models/).
   Known differences between the repo's data files and what the author reloaded are listed
   with a reason in powerbi/inventory/row_count_exceptions.json.

Writes powerbi/data/conversion_report.md and exits non-zero on any unexplained mismatch.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_sources import CATALOG, REPO, sha256  # noqa: E402
from qlik_script import plain_tables  # noqa: E402

INVENTORY = REPO / "powerbi" / "inventory"
EXCEPTIONS = INVENTORY / "row_count_exceptions.json"
REPORT = REPO / "powerbi" / "data" / "conversion_report.md"


def _norm(p: str) -> str:
    return re.sub(r"^\$\([^)]*\)|^(\.\.[\\/])+", "", p.strip().strip("'\"[]")).replace("\\", "/").lower()


def resolve_source(manifest: dict, load) -> tuple[str, str | None] | None:
    """Map a plain load to (catalog source path, table name within the source)."""
    sources = manifest["script"]["sources"]
    if load.source_kind == "sql":
        for s in sources:
            m = re.match(r"(.+\.mdb) \(table: (.+)\)$", s.get("resolved") or "")
            if m and m.group(2).lower() == load.source.lower():
                return m.group(1), m.group(2)
        return None
    want = _norm(load.source)
    for s in sources:
        if s.get("resolved") and (_norm(s["path"]) == want or want.endswith(_norm(s["resolved"]))):
            return s["resolved"], None
    base = want.rsplit("/", 1)[-1]
    hits = [s["resolved"] for s in sources if s.get("resolved") and s["resolved"].lower().rsplit("/", 1)[-1] == base]
    return (hits[0], None) if len(set(hits)) == 1 else None


def catalog_table(catalog: dict, source: str, table: str | None) -> dict | None:
    entry = catalog["sources"].get(source)
    if not entry:
        return None
    tables = entry["tables"]
    if table is None:
        return tables[0] if len(tables) == 1 else None
    return next((t for t in tables if t["table"].lower() == table.lower()), None)


def coverage_problem(covers: dict) -> str | None:
    """An exception's superset claim: every key value used by `fact` exists in `table`. None when it holds."""
    import pyarrow.compute as pc

    paths = [REPO / covers["table"], REPO / covers["fact"]]
    if not all(p.exists() for p in paths):
        return None if not (REPO / "powerbi/data/parquet").exists() else f"missing {covers['table']} or {covers['fact']}"
    have = pc.unique(pq.read_table(paths[0], columns=[covers["key"]])[covers["key"]])
    used = pc.drop_null(pc.unique(pq.read_table(paths[1], columns=[covers["fact_key"]])[covers["fact_key"]]))
    missing = len(used) - pc.sum(pc.is_in(used, value_set=have)).as_py()
    return f"{missing} {covers['fact_key']} values used by the fact table are missing" if missing else None


def check_integrity(catalog: dict) -> list[dict]:
    rows = []
    for src, entry in catalog["sources"].items():
        sha_ok = sha256(REPO / src) == entry["sha256"]
        for t in entry["tables"]:
            path = REPO / t["parquet"]
            actual = pq.ParquetFile(path).metadata.num_rows if path.exists() else None
            rows.append({"source": src, "table": t["table"], "source_rows": t["source_rows"], "parquet_rows": actual,
                         "ok": sha_ok and actual == t["source_rows"] == t["rows"], "sha_ok": sha_ok})
    return rows


def check_inventory(catalog: dict) -> list[dict]:
    exceptions = json.loads(EXCEPTIONS.read_text())["exceptions"] if EXCEPTIONS.exists() else []
    out = []
    for mf in sorted((INVENTORY / "manifests").glob("*.json")):
        manifest = json.loads(mf.read_text())
        app = mf.stem
        script = (INVENTORY / manifest["script"]["file"]).read_text(encoding="utf-8")
        plain = plain_tables(script)
        for t in manifest["data_model"]["tables"]:
            if t["name"].startswith("$$"):
                continue
            row = {"app": app, "table": t["name"], "inventory_rows": t["rows"]}
            load = plain.get(t["name"])
            resolved = resolve_source(manifest, load) if load else None
            ct = catalog_table(catalog, *resolved) if resolved else None
            if not load:
                row.update(status="derived")
            elif not ct:
                row.update(status="MISSING_SOURCE", reason=f"plain load of {load.source!r} has no converted table")
            else:
                row.update(source=resolved[0] + (f" :: {resolved[1]}" if resolved[1] else ""),
                           parquet=ct["parquet"], parquet_rows=ct["rows"])
                if ct["rows"] == t["rows"]:
                    row["status"] = "match"
                else:
                    exc = next((e for e in exceptions if e["table"] == t["name"] and re.fullmatch(e["apps"], app)
                                and e["source"] == row["source"] and e["inventory_rows"] == t["rows"]
                                and e["parquet_rows"] == ct["rows"]), None)
                    problem = exc and coverage_problem(exc["covers"]) if exc and exc.get("covers") else None
                    if exc and not problem:
                        row.update(status="explained", reason=exc["reason"])
                    else:
                        row.update(status="MISMATCH", reason=problem)
            out.append(row)
    return out


def write_report(integrity: list[dict], inventory: list[dict]) -> None:
    lines = ["# Parquet conversion verification", "",
             "Generated by `python powerbi/tools/verify_conversion.py`.", "",
             "## 1. Source integrity (Parquet rows = source's own row count)", "",
             "| Source | Table | Source rows | Parquet rows | OK |", "|---|---|---:|---:|:-:|"]
    for r in integrity:
        lines.append(f"| {r['source']} | {r['table']} | {r['source_rows']:,} | {r['parquet_rows']:,} | "
                     f"{'yes' if r['ok'] else 'NO'} |")
    counts = {}
    for r in inventory:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines += ["", "## 2. Inventory row counts (plain-load tables per app)", "",
              "Status counts: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), "",
              "| App | Qlik table | Inventory rows | Parquet rows | Status | Source / reason |",
              "|---|---|---:|---:|---|---|"]
    for r in inventory:
        pr = f"{r['parquet_rows']:,}" if "parquet_rows" in r else ""
        note = r.get("reason") or r.get("source", "built by script transformations; checked by the app's source model")
        lines.append(f"| {r['app']} | {r['table']} | {r['inventory_rows']:,} | {pr} | {r['status']} | {note} |")
    REPORT.write_text("\n".join(lines) + "\n")


def main() -> int:
    catalog = json.loads(CATALOG.read_text())
    integrity = check_integrity(catalog)
    inventory = check_inventory(catalog)
    write_report(integrity, inventory)
    bad_int = [r for r in integrity if not r["ok"]]
    bad_inv = [r for r in inventory if r["status"] in ("MISMATCH", "MISSING_SOURCE")]
    by = lambda s: sum(r["status"] == s for r in inventory)  # noqa: E731
    print(f"integrity: {len(integrity) - len(bad_int)}/{len(integrity)} parquet tables match their source row count")
    print(f"inventory: {by('match')} match, {by('explained')} explained, {len(bad_inv)} mismatch/missing, "
          f"{by('derived')} derived (app source model)")
    for r in bad_int + bad_inv:
        print("FAIL", r)
    print(f"report: {REPORT.relative_to(REPO)}")
    return 1 if bad_int or bad_inv else 0


if __name__ == "__main__":
    sys.exit(main())
