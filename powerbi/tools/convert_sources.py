"""Convert the repo's data sources that Power BI cannot read directly into Parquet.

Converted: every QVD (*.qvd), every table of every MS Access database (*.mdb),
every sheet of legacy Excel (*.xls) and Excel (*.xlsx) workbooks, and the
delimited CSV files. Report-style text files (Production Planning - Legacy.txt)
are left as-is: Power BI reads them natively and their QlikView transformation
filters belong in the app's Power Query.

Output mirrors the source path under ``powerbi/data/parquet``:
    Data Files/QVDs/Flight Data.qvd        -> Data Files/QVDs/Flight Data.parquet
    Data Files/MDBs/Dimension Tables.mdb   -> Data Files/MDBs/Dimension Tables/<table>.parquet
    Data Files/Excel/Comments.xls          -> Data Files/Excel/Comments/<sheet>.parquet
and ``powerbi/data/catalog.json`` records, per source, its sha256, the source's
own row count (QVD header NoOfRecords, Access row count, sheet rows) and each
Parquet table's rows and column types. See powerbi/docs/CONVENTIONS.md for the
QlikView dual-value typing rules.

Usage: python powerbi/tools/convert_sources.py [--only GLOB] [--check]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fnmatch
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qvd import read_qvd  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "powerbi" / "data" / "parquet"
CATALOG = REPO / "powerbi" / "data" / "catalog.json"
QLIK_EPOCH = dt.date(1899, 12, 30)
EXCLUDE_DIRS = {".git", "powerbi"}
NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


# ---------------------------------------------------------------- typing rules

def _as_number(text: str):
    t = text.strip().replace(",", "") if text is not None else ""
    if not NUM_RE.match(t):
        return None
    v = float(t)
    return int(v) if v.is_integer() and "e" not in t.lower() and abs(v) < 2**62 else v


def _date_text(num) -> str | None:
    if num is None or float(num) != int(num):
        return None
    return (QLIK_EPOCH + dt.timedelta(days=int(num))).isoformat()


def classify_symbols(symbols: list[tuple]) -> tuple[str, list, list | None]:
    """Decide the Parquet type for a field from its distinct (number, text) values.

    Returns (kind, values, sort_numbers) where kind is int64|float64|date|string and
    ``sort_numbers`` is the numeric half of text duals (``<field>__num`` column) or None.
    """
    nums, texts = [], []
    for num, text in symbols:
        if num is None and text is not None and text != "":
            num = _as_number(text) if NUM_RE.match(text.strip().replace(",", "")) else None
            if num is None:
                break  # genuine text value -> string column
        nums.append(num)
        texts.append(text)
    else:
        # every value numeric (or a dual of a number). Dates?
        duals = [(n, t) for n, t in zip(nums, texts) if t not in (None, "") and n is not None]
        if duals and all(DATE_RE.match(t) and _date_text(n) == t for n, t in duals):
            return "date", nums, None
        if all(t in (None, "") or _as_number(t) == n or (_as_number(t) is not None and float(_as_number(t)) == float(n))
               for n, t in zip(nums, texts)):
            present = [n for n in nums if n is not None]
            if all(isinstance(n, int) or float(n).is_integer() for n in present):
                return "int64", [None if n is None else int(n) for n in nums], None
            return "float64", [None if n is None else float(n) for n in nums], None
        # text duals such as Month = ('Jan', 1): keep text, expose number for sorting
        out_text = [t if t is not None else (None if n is None else _fmt(n)) for n, t in zip(nums, texts)]
        return "string", out_text, nums
    out = []
    for num, text in symbols:
        out.append(text if text is not None else (None if num is None else _fmt(num)))
    return "string", out, None


def _fmt(n) -> str:
    return str(int(n)) if float(n).is_integer() else repr(float(n))


def _arrow_array(kind: str, values: list):
    if kind == "int64":
        return pa.array(values, type=pa.int64())
    if kind == "float64":
        return pa.array(values, type=pa.float64())
    if kind == "date":
        return pa.array([None if v is None else QLIK_EPOCH + dt.timedelta(days=int(v)) for v in values], type=pa.date32())
    if kind == "timestamp":
        return pa.array(values, type=pa.timestamp("us"))
    return pa.array(values, type=pa.string())


def table_from_symbols(columns: list[tuple[str, list[tuple], np.ndarray]]) -> tuple[pa.Table, list[dict]]:
    """columns: (name, distinct symbols, per-row symbol index with <0 meaning NULL)."""
    arrays, names, meta = [], [], []
    for name, symbols, idx in columns:
        kind, values, sort_nums = classify_symbols(symbols)
        dictionary = _arrow_array(kind, values)
        null = idx < 0
        safe = np.where(null, 0, idx)
        if len(dictionary) == 0:
            arr = pa.nulls(len(idx), type=dictionary.type)
        else:
            arr = dictionary.take(pa.array(safe, mask=null))
        arrays.append(arr)
        names.append(name)
        col = {"name": name, "type": kind}
        if sort_nums is not None:
            sd = pa.array([None if v is None else float(v) for v in sort_nums], type=pa.float64())
            arrays.append(sd.take(pa.array(safe, mask=null)))
            names.append(f"{name}__num")
            col["sort_by"] = f"{name}__num"
            meta.append(col)
            meta.append({"name": f"{name}__num", "type": "float64", "dual_number_of": name})
            continue
        meta.append(col)
    return pa.table(arrays, names=names), meta


def table_from_rows(header: list[str], rows: list[list], declared: dict | None = None) -> tuple[pa.Table, list[dict]]:
    """Type text rows (CSV/Access/Excel) with the same rules as QVD symbols."""
    cols = []
    for i, name in enumerate(header):
        raw = [r[i] if i < len(r) else None for r in rows]
        raw = [None if v is None or (isinstance(v, str) and v == "") else v for v in raw]
        decl = (declared or {}).get(name)
        if decl in ("timestamp", "date"):
            vals = [None if v is None else _parse_ts(v) for v in raw]
            if decl == "date" or all(v is None or (v.hour == v.minute == v.second == 0) for v in vals):
                cols.append((name, "date", [None if v is None else v.date() for v in vals]))
            else:
                cols.append((name, "timestamp", vals))
            continue
        if decl == "string":
            cols.append((name, "string", [None if v is None else str(v) for v in raw]))
            continue
        distinct = sorted({str(v) for v in raw if v is not None})
        symbols = [(None, s) for s in distinct]
        if distinct and all(DATE_RE.match(s) for s in distinct):
            cols.append((name, "date", [None if v is None else dt.date.fromisoformat(str(v)) for v in raw]))
            continue
        kind, values, _ = classify_symbols(symbols)
        lookup = dict(zip(distinct, values))
        cols.append((name, kind, [None if v is None else lookup[str(v)] for v in raw]))
    arrays, meta = [], []
    for name, kind, vals in cols:
        if kind == "date":
            arrays.append(pa.array(vals, type=pa.date32()))
        else:
            arrays.append(_arrow_array(kind, vals))
        meta.append({"name": name, "type": kind})
    return pa.table(arrays, names=[c[0] for c in cols]), meta


def _parse_ts(v) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%m/%d/%y %H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"unparseable timestamp {s!r}")


# ---------------------------------------------------------------- writers

def write_parquet(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd", compression_level=9, use_dictionary=True,
                   write_statistics=True, row_group_size=256_000)


def convert_qvd(src: Path) -> dict:
    q = read_qvd(src)
    table, cols = table_from_symbols([(f.name, f.symbols, q.indexes[f.name]) for f in q.fields])
    out = OUT / Path(rel(src)).with_suffix(".parquet")
    write_parquet(table, out)
    return {"tables": [{"table": q.table_name, "parquet": rel(out), "source_rows": q.no_of_records,
                        "rows": table.num_rows, "columns": cols}],
            "qvd_header": q.header}


ACCESS_TYPES = {"Integer": "int64", "Long Integer": "int64", "Byte": "int64", "Double": "float64",
                "Single": "float64", "Currency": "float64", "DateTime": "timestamp", "Boolean": "int64"}


def _mdb_schema(src: Path) -> dict[str, dict[str, str]]:
    ddl = subprocess.run(["mdb-schema", str(src), "access"], check=True, capture_output=True, text=True).stdout
    schema, current = {}, None
    for line in ddl.splitlines():
        m = re.match(r"CREATE TABLE \[(.+)\]", line)
        if m:
            current = schema.setdefault(m.group(1), {})
            continue
        m = re.match(r"\s*\[(.+?)\]\s+(.+?),?\s*$", line)
        if current is not None and m:
            t = m.group(2).rstrip(",").strip()
            current[m.group(1)] = next((v for k, v in ACCESS_TYPES.items() if t == k), "string")
    return schema


def convert_mdb(src: Path) -> dict:
    if not shutil.which("mdb-export"):
        raise SystemExit("mdbtools (mdb-export) is required to convert .mdb files: apt-get install mdbtools")
    schema = _mdb_schema(src)
    names = subprocess.run(["mdb-tables", "-1", str(src)], check=True, capture_output=True, text=True).stdout.split("\n")
    tables = []
    for name in [n for n in names if n]:
        out_csv = subprocess.run(["mdb-export", "-D", "%Y-%m-%d %H:%M:%S", str(src), name],
                                 check=True, capture_output=True, text=True).stdout
        rows = list(csv.reader(io.StringIO(out_csv)))
        header, body = rows[0], rows[1:]
        table, cols = table_from_rows(header, body, schema.get(name))
        out = OUT / Path(rel(src)).with_suffix("") / f"{name}.parquet"
        write_parquet(table, out)
        tables.append({"table": name, "parquet": rel(out), "source_rows": len(body), "rows": table.num_rows,
                       "columns": cols})
    return {"tables": tables}


def convert_excel(src: Path) -> dict:
    import pandas as pd

    engine = "xlrd" if src.suffix.lower() == ".xls" else "openpyxl"
    sheets = pd.read_excel(src, sheet_name=None, header=None, dtype=object, engine=engine)
    tables = []
    for sheet, df in sheets.items():
        df = df.dropna(how="all")
        if df.empty:
            continue
        header = [str(h) for h in df.iloc[0].tolist()]
        body = [[_excel_cell(v) for v in row] for row in df.iloc[1:].itertuples(index=False)]
        table, cols = table_from_rows(header, body)
        out = OUT / Path(rel(src)).with_suffix("") / f"{sheet}.parquet"
        write_parquet(table, out)
        tables.append({"table": sheet, "parquet": rel(out), "source_rows": len(body), "rows": table.num_rows,
                       "columns": cols})
    return {"tables": tables}


def _excel_cell(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time() else v.isoformat(sep=" ")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def convert_csv(src: Path) -> dict:
    raw = src.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "cp1252"
    text = raw.decode(encoding)
    first = text.splitlines()[0]
    delimiter = max([";", "\t", ","], key=first.count)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter, quotechar='"') if r]
    header, body = rows[0], rows[1:]
    table, cols = table_from_rows(header, body)
    out = OUT / Path(rel(src)).with_suffix(".parquet")
    write_parquet(table, out)
    return {"tables": [{"table": src.stem, "parquet": rel(out), "source_rows": len(body), "rows": table.num_rows,
                        "columns": cols}],
            "csv": {"encoding": encoding, "delimiter": delimiter}}


CONVERTERS = {".qvd": ("QVD", convert_qvd), ".mdb": ("MS Access", convert_mdb), ".xls": ("Excel (biff)", convert_excel),
              ".xlsx": ("Excel (ooxml)", convert_excel), ".csv": ("CSV", convert_csv)}


def discover() -> list[Path]:
    found = []
    for p in sorted(REPO.rglob("*")):
        if not p.is_file() or EXCLUDE_DIRS & set(p.relative_to(REPO).parts[:1]):
            continue
        if p.suffix.lower() in CONVERTERS:
            found.append(p)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="glob on repo-relative source path")
    args = ap.parse_args(argv)
    catalog = json.loads(CATALOG.read_text()) if CATALOG.exists() and args.only else {"sources": {}}
    for src in discover():
        r = rel(src)
        if args.only and not fnmatch.fnmatch(r, args.only):
            continue
        kind, fn = CONVERTERS[src.suffix.lower()]
        entry = {"kind": kind, "sha256": sha256(src), "bytes": src.stat().st_size, **fn(src)}
        for t in entry["tables"]:
            t["parquet_bytes"] = (REPO / t["parquet"]).stat().st_size
        catalog["sources"][r] = entry
        print(f"{r}: " + ", ".join(f"{t['table']}={t['rows']}" for t in entry["tables"]), flush=True)
    catalog["generator"] = {"script": "powerbi/tools/convert_sources.py", "pyarrow": pa.__version__}
    catalog["sources"] = dict(sorted(catalog["sources"].items()))
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
