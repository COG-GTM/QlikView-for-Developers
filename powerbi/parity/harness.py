"""Parity harness CLI.

  python powerbi/parity/harness.py source  [--app NAME | --all]      # recompute KPIs from Parquet -> expected/<app>.json
  python powerbi/parity/harness.py queries --app NAME --pbip DIR      # DAX queries for the app's PBIP -> dax/<app>.queries.json
  python powerbi/parity/harness.py compare --app NAME --results FILE  # compare DAX results with expected -> reports/<app>.md

DAX results are produced on Windows by run_dax.ps1 against Power BI Desktop (see docs/PARITY.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qlik_expr as q  # noqa: E402
from engine import INVENTORY, REPO, Evaluator, ModelUnavailable, SourceModel  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPECTED, DAX, REPORTS = HERE / "expected", HERE / "dax", HERE / "reports"
CHECKS = HERE / "checks"


def show(path) -> str:
    """Repo-relative path for messages (absolute when outside the repo)."""
    try:
        return Path(path).resolve().relative_to(REPO).as_posix()
    except ValueError:
        return str(path)


LITERAL_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\[[^\]]*\]")


def parity_key(expression: str) -> str:
    """Stable id of a Qlik expression; PBIP measures carry it as `annotation ParityKey`.

    Whitespace and case are normalized only outside 'strings', "search strings" and [field names],
    whose contents are significant.
    """
    text, parts, pos = expression.strip().lstrip("="), [], 0
    for m in LITERAL_RE.finditer(text):
        parts.append(re.sub(r"\s+", "", text[pos:m.start()]).lower())
        parts.append(m.group())
        pos = m.end()
    parts.append(re.sub(r"\s+", "", text[pos:]).lower())
    return hashlib.sha1("".join(parts).encode()).hexdigest()[:12]


def grains(dims: list[str], groups: dict[str, dict]) -> list[list[str]]:
    """Grand total, the chart's first-level grain, and every drill-down / cyclic alternative."""
    out = [[]]
    if not dims:
        return out
    levels = []
    for d in dims:
        g = groups.get(d)
        if not g:
            levels.append([[d]])
        elif g["type"] == "drill-down":
            levels.append([g["fields"][:i] for i in range(1, len(g["fields"]) + 1)])
        else:
            levels.append([[f] for f in g["fields"]])
    base = [lv[0] for lv in levels]
    out.append([f for part in base for f in part])
    for i, lv in enumerate(levels):
        for alt in lv[1:]:
            variant = base[:i] + [alt] + base[i + 1:]
            out.append([f for part in variant for f in part])
    uniq = []
    for g in out:
        if g not in uniq:
            uniq.append(g)
    return uniq


def parity_checks(app: str | None) -> list[dict]:
    """Data checks for apps whose QlikView sheets have no chart expressions (``checks/<app>.json``).

    Same shape as manifest KPIs, so they flow through source, queries and compare unchanged.
    """
    path = CHECKS / f"{app}.json"
    if not app or not path.exists():
        return []
    return [{"object": c["object"], "caption": c.get("caption"), "label": c["label"], "expanded": c["expression"],
             "dims": c["dims"]} for c in json.loads(path.read_text(encoding="utf-8"))["checks"]]


def kpi_list(manifest: dict, app: str | None = None) -> list[dict]:
    groups = {g["name"]: g for g in manifest["data_model"].get("groups", [])}
    counter, out = {}, []
    for k in manifest["kpis"] + parity_checks(app):
        obj = k["object"].split(" ")[0]
        counter[obj] = counter.get(obj, 0) + 1
        out.append({"kpi": f"{obj}#{counter[obj]}", "object": k["object"], "caption": k.get("caption"),
                    "label": k["label"], "expression": k["expanded"], "dims": k["dims"],
                    "parity_key": parity_key(k["expanded"]), "grains": grains(k["dims"], groups)})
    return out


def _json_value(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def cmd_source(app: str) -> dict:
    manifest = json.loads((INVENTORY / "manifests" / f"{app}.json").read_text())
    started = time.time()
    result = {"app": app, "baseline": "no selections", "kpis": []}
    try:
        model = SourceModel(app)
    except ModelUnavailable as e:
        result.update(status="model_unavailable", reason=str(e),
                      kpis=[{**k, "status": "model_unavailable"} for k in kpi_list(manifest, app)])
        return result
    ev = Evaluator(model)
    result.update(status="ok", model_source=model.model_source, model_tables=model.table_check)
    for k in kpi_list(manifest, app):
        entry = {**k, "results": []}
        try:
            if any(d.startswith("=") for d in k["dims"]):
                raise q.Unsupported("calculated dimension")
            node = ev.compile(k["expression"])
            for grain in k["grains"]:
                df = ev.evaluate(node, grain)
                if "__all" in df:
                    df = df.drop(columns="__all")
                df = df[df["value"].notna()]
                rows = [[_json_value(x) for x in r] for r in df[grain + ["value"]].itertuples(index=False)]
                rows.sort(key=lambda r: [str(x) for x in r])
                entry["results"].append({"id": f"{k['kpi']}@{'+'.join(grain) or 'total'}", "grain": grain,
                                         "row_count": len(rows), "rows": rows})
            entry["status"] = "ok"
        except q.Unsupported as e:
            entry.update(status="unsupported", reason=str(e), results=[])
        result["kpis"].append(entry)
    result["elapsed_s"] = round(time.time() - started, 1)
    return result


def write_expected(app: str) -> Path:
    res = cmd_source(app)
    EXPECTED.mkdir(exist_ok=True)
    out = EXPECTED / f"{app}.json.gz"
    res.pop("elapsed_s", None)
    payload = (json.dumps(res, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    with open(out, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0, filename="") as f:
        f.write(payload)  # mtime=0: byte-identical output, so CI can diff it
    ok = sum(k["status"] == "ok" for k in res["kpis"])
    print(f"{app}: {res['status']}; {ok}/{len(res['kpis'])} KPI expressions evaluated from source -> "
          f"{show(out)}")
    if res["status"] != "ok":
        print(f"   {res['reason'][:160]}")
        return out
    for k in res["kpis"]:
        if k["status"] != "ok":
            print(f"   {k['kpi']} {k['label']!r}: {k['status']} ({k.get('reason', res.get('reason', ''))[:110]})")
    return out


def load_expected(app: str) -> dict:
    with gzip.open(EXPECTED / f"{app}.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("source")
    s.add_argument("--app")
    s.add_argument("--all", action="store_true")
    qq = sub.add_parser("queries")
    qq.add_argument("--app", required=True)
    qq.add_argument("--pbip", required=True, help="PBIP folder of the app (contains *.SemanticModel)")
    c = sub.add_parser("compare")
    c.add_argument("--app", required=True)
    c.add_argument("--results", required=True)
    c.add_argument("--rel-tol", type=float, default=1e-9)
    c.add_argument("--abs-tol", type=float, default=1e-6)
    args = ap.parse_args(argv)
    if args.cmd == "source":
        apps = [p.stem for p in sorted((INVENTORY / "manifests").glob("*.json"))] if args.all else [args.app]
        for app in apps:
            write_expected(app)
        return 0
    if args.cmd == "queries":
        from dax import write_queries
        print(write_queries(args.app, Path(args.pbip)))
        return 0
    from compare import compare_files
    return compare_files(args.app, Path(args.results), args.rel_tol, args.abs_tol)


if __name__ == "__main__":
    sys.exit(main())
