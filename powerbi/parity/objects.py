"""Sheet objects that show data without expressions: table boxes, list boxes, and table row counts.

Apps whose sheets have no charts (e.g. the Chapter 10 ETL demos) are verified on the rows their
objects show. ``objects/<manifest name>.json`` lists them as recovered from the .qvw layout:

  {"objects": [{"id": "TB01", "type": "table box", "fields": ["A", "B"]},
               {"id": "LB01", "type": "list box", "fields": ["A"]},
               {"id": "ROWS", "type": "row count", "table": "T"}]}

A table box shows the distinct combinations of its fields, a list box the distinct non-null
values of its field. Result ids: ``<id>@<field+field>`` and ``<id>@<table>``.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine import qi

OBJECTS = Path(__file__).resolve().parent / "objects"


def load_spec(app: str) -> list[dict] | None:
    path = OBJECTS / f"{app}.json"
    return json.loads(path.read_text(encoding="utf-8"))["objects"] if path.exists() else None


def _plain(v):
    return v.item() if hasattr(v, "item") else v


def evaluate(model, spec: list[dict]) -> list[dict]:
    out = []
    for o in spec:
        if o["type"] == "row count":
            n = model.con.execute(f"SELECT count(*) FROM {qi(o['table'])}").fetchone()[0]
            out.append({"object": o["id"], "type": o["type"], "table": o["table"], "status": "ok",
                        "results": [{"id": f"{o['id']}@{o['table']}", "grain": [], "row_count": 1, "rows": [[n]]}]})
            continue
        fields = o["fields"]
        frm, cols = model.from_clause(set(fields))
        sel = ", ".join(f"{cols[f]} AS {qi(f)}" for f in fields)
        where = f" WHERE {cols[fields[0]]} IS NOT NULL" if o["type"] == "list box" else ""
        rows = [[_plain(x) for x in r] for r in model.con.execute(f"SELECT DISTINCT {sel} FROM {frm}{where}").fetchall()]
        rows.sort(key=lambda r: [str(x) for x in r])
        out.append({"object": o["id"], "type": o["type"], "fields": fields, "status": "ok",
                    "results": [{"id": f"{o['id']}@{'+'.join(fields)}", "grain": fields, "row_count": len(rows),
                                 "rows": rows}]})
    return out
