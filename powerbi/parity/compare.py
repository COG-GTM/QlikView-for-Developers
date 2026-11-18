"""Compare DAX results (from run_dax.ps1) with the source-side expected results.

Results file contract (written by run_dax.ps1, or any tool that can run DAX):
  {"app": ..., "produced_by": ..., "results": [{"id": "CH01#1@Year", "columns": [...], "rows": [[...], ...]}]}
Each row is the grain's dimension values in grain order followed by the measure value.
Blank and 0 are treated as equal (Qlik suppresses zero rows; DAX drops blank rows), dimension
values are compared as numbers when both parse as numbers and dates by their ISO date.
Relationship checks (result ids starting ``REL:``) fail on duplicated one-side keys and warn on
many-side keys with no match (those rows sit under the blank member, as in Qlik).
Rows Power BI cannot represent (e.g. two Qlik values differing only in letter case, which a Power BI
column stores as one value) are listed in ``parity/exceptions/<app>.json`` as
``[{"id": <result id>, "dims": [...], "reason": ...}]``; a result whose only mismatches are listed
there is ``known_difference`` instead of ``fail``.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from harness import DAX, REPORTS, load_expected, show

EXCEPTIONS = Path(__file__).resolve().parent / "exceptions"


def norm_dim(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    if re.fullmatch(r"-?\d+(\.\d+)?", s.strip()):
        return float(s)
    if m := re.fullmatch(r"(\d{4}-\d{2}-\d{2})(T00:00:00(\.0+)?)?", s):
        return m.group(1)
    return s


def norm_val(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return 0.0 if isinstance(v, float) and math.isnan(v) else float(v)
    try:
        return float(v)
    except ValueError:
        return str(v)


def close(a, b, rel, abs_):
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)
    return a == b


def compare_result(expected: dict, actual: dict | None, rel: float, abs_: float, known=frozenset()) -> dict:
    if actual is None:
        return {"id": expected["id"], "status": "missing"}
    n = len(expected["grain"])
    exp = {tuple(norm_dim(x) for x in r[:n]): norm_val(r[n]) for r in expected["rows"]}
    act = {tuple(norm_dim(x) for x in r[:n]): norm_val(r[-1]) for r in actual["rows"]}
    diffs = []
    for key in sorted(set(exp) | set(act), key=str):
        a, b = exp.get(key, 0.0), act.get(key, 0.0)
        if not close(a, b, rel, abs_):
            diffs.append({"dims": list(key), "source": a, "dax": b})
    listed = [d for d in diffs if (expected["id"], tuple(d["dims"])) in known]
    status = "pass" if not diffs else "known_difference" if len(listed) == len(diffs) else "fail"
    return {"id": expected["id"], "status": status, "rows": len(exp),
            "mismatches": len(diffs), "examples": diffs[:5]}


def check_relationship(result: dict) -> dict:
    row = dict(zip([c.strip("[]") for c in result["columns"]], result["rows"][0])) if result.get("rows") else {}
    counts = {k: int(row.get(k) or 0) for k in ("unmatched_keys", "unmatched_rows", "duplicate_keys")}
    status = "fail" if not row or counts["duplicate_keys"] else "warn" if counts["unmatched_keys"] else "pass"
    return {"id": result["id"], "status": status, **counts}


def compare_table(expected: dict, actual: dict | None) -> dict:
    """Full-table parity: the rows must match as a multiset, every cell compared like a dimension value."""
    if actual is None:
        return {"id": expected["id"], "status": "missing"}
    exp = Counter(tuple(norm_dim(x) for x in r) for r in expected["rows"])
    act = Counter(tuple(norm_dim(x) for x in r) for r in actual["rows"])
    diffs = [{"row": list(r), "source": exp[r], "dax": act[r]} for r in sorted(set(exp) | set(act), key=str)
             if exp[r] != act[r]]
    return {"id": expected["id"], "status": "pass" if not diffs else "fail", "rows": expected["row_count"],
            "mismatches": len(diffs), "examples": diffs[:5]}


def compare_rowset(expected: dict, actual: dict | None, known=frozenset()) -> dict:
    """Table/list box: the distinct rows shown must be the same set (no measure column)."""
    if actual is None:
        return {"id": expected["id"], "status": "missing"}
    n = len(expected["grain"])
    # A column the source holds as text (e.g. Product Line ID '03') is compared as text, so a
    # label that lost its leading zero ('3') fails instead of matching numerically.
    text = [any(isinstance(r[i], str) for r in expected["rows"]) for i in range(n)]

    def key(r):
        return tuple(str(x) if t and x is not None else norm_dim(x) for x, t in zip(r[:n], text))

    exp = {key(r) for r in expected["rows"]}
    act = {key(r) for r in actual["rows"]}
    diffs = [{"dims": list(k), "source": k in exp, "dax": k in act} for k in sorted(exp ^ act, key=str)]
    listed = [d for d in diffs if (expected["id"], tuple(norm_dim(x) for x in d["dims"])) in known]
    status = "pass" if not diffs else "known_difference" if len(listed) == len(diffs) else "fail"
    return {"id": expected["id"], "status": status, "rows": len(exp),
            "mismatches": len(diffs), "examples": diffs[:5]}


def compare(expected_doc: dict, results_doc: dict, rel=1e-9, abs_=1e-6, relationship_ids=(), exceptions=()) -> dict:
    if results_doc.get("app") != expected_doc["app"]:
        raise ValueError(f"results are for app {results_doc.get('app')!r}, expected {expected_doc['app']!r}")
    actual = {r["id"]: r for r in results_doc.get("results", [])}
    known = frozenset((e["id"], tuple(norm_dim(x) for x in e["dims"])) for e in exceptions)
    out = []
    for k in expected_doc["kpis"]:
        if k["status"] != "ok":
            out.append({"id": k["kpi"], "kpi": k["kpi"], "label": k["label"], "status": k["status"],
                        "reason": k.get("reason")})
            continue
        for r in k["results"]:
            out.append({"kpi": k["kpi"], "label": k["label"],
                        **compare_result(r, actual.get(r["id"]), rel, abs_, known)})
    for t in expected_doc.get("tables", []):
        out.append({"kpi": "table", "label": t["table"], **compare_table(t, actual.get(t["id"]))})
    for o in expected_doc.get("objects", []):
        for r in o["results"]:
            check = compare_result(r, actual.get(r["id"]), rel, abs_) if o["type"] == "row count" \
                else compare_rowset(r, actual.get(r["id"]), known)
            out.append({"kpi": o["object"], "label": o["type"], **check})
    summary = {}
    for r in out:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    rels = [check_relationship(r) for r in results_doc.get("results", []) if str(r.get("id", "")).startswith("REL:")]
    seen = {r["id"] for r in rels}
    rels += [{"id": i, "status": "missing", "unmatched_keys": 0, "unmatched_rows": 0, "duplicate_keys": 0}
             for i in relationship_ids if i not in seen]
    rel_summary = {}
    for r in rels:
        rel_summary[r["status"]] = rel_summary.get(r["status"], 0) + 1
    return {"app": expected_doc["app"], "produced_by": results_doc.get("produced_by"), "summary": summary,
            "results": out, "relationship_summary": rel_summary, "relationships": rels}


def compare_files(app: str, results: Path, rel: float, abs_: float) -> int:
    expected = load_expected(app)
    spec = DAX / f"{app}.queries.json"
    listed = json.loads(spec.read_text(encoding="utf-8")).get("relationships", []) if spec.exists() else []
    rel_ids = [r["id"] for r in listed]
    exc = EXCEPTIONS / f"{app}.json"
    exceptions = json.loads(exc.read_text(encoding="utf-8")) if exc.exists() else []
    report = compare(expected, json.loads(results.read_text(encoding="utf-8-sig")), rel, abs_, rel_ids, exceptions)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{app}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    lines = [f"# Parity: {app}", "", f"DAX results: {report['produced_by']}", "",
             "Summary: " + ", ".join(f"{k}: {v}" for k, v in sorted(report["summary"].items())), "",
             "| Result | KPI | Status | Rows | Mismatches |", "|---|---|---|---:|---:|"]
    for r in report["results"]:
        lines.append(f"| {r['id']} | {r['label']} | {r['status']} | {r.get('rows', '')} | {r.get('mismatches', '')} |")
    if report["relationships"]:
        lines += ["", "Relationships: " + ", ".join(f"{k}: {v}" for k, v in sorted(report["relationship_summary"].items())),
                  "", "| Relationship | Status | Unmatched keys | Unmatched rows | Duplicate keys |",
                  "|---|---|---:|---:|---:|"]
        for r in report["relationships"]:
            lines.append(f"| {r['id'][4:]} | {r['status']} | {r['unmatched_keys']} | {r['unmatched_rows']} "
                         f"| {r['duplicate_keys']} |")
    md = REPORTS / f"{app}.md"
    md.write_text("\n".join(lines) + "\n")
    print(f"{report['summary']} relationships {report['relationship_summary']} -> {show(md)}")
    ok = set(report["summary"]) <= {"pass", "known_difference", "unsupported", "model_unavailable"}
    return 0 if ok and set(report["relationship_summary"]) <= {"pass", "warn"} else 1
