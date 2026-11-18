"""Read each sheet's object ids and the list boxes' captions from a QlikView 11 .qvw (read-only).

The document block (the first zlib stream after the 23-byte header) stores every sheet as its name, `Document\\SHnn`
and the ids of its objects; a list box's caption, which QlikView sets to the list box's field unless renamed, is the
string stored right before its id and the 'ffffff' colour that follows it. Captions are what QlikView shows, so
`build_airline_base.py` maps them back onto model fields and lists the ones it cannot map.

    python powerbi/tools/extract_sheet_objects.py --app "Chapter14__Solution_Chapter 14_Airline Operations"
"""
import argparse
import json
import re
import zlib
from pathlib import Path

POWERBI = Path(__file__).resolve().parents[1]
REPO = POWERBI.parent
OUT = POWERBI / "inventory" / "sheet_objects"
STR = re.compile(rb"[\x20-\x7e]{3,}")


def doc_block(qvw: Path) -> bytes:
    return zlib.decompressobj().decompress(qvw.read_bytes()[23:])


def strings(b: bytes) -> list[tuple[int, str]]:
    return [(m.start(), m.group().decode("latin1")) for m in STR.finditer(b)]


def extract(app: str) -> dict:
    manifest = json.loads((POWERBI / "inventory" / "manifests" / f"{app}.json").read_text())
    s = strings(doc_block(REPO / manifest["path"]))
    ids = set(manifest["objects"]["ids"])
    captions: dict[str, str] = {}
    for i in range(1, len(s) - 1):
        oid = s[i][1]
        if oid.startswith("LB") and oid in ids and s[i + 1][1].startswith("ffffff") and oid not in captions:
            captions[oid] = s[i - 1][1]
    sheets = []
    for i, (_, text) in enumerate(s):
        m = re.fullmatch(r"Document\\(SH\w+)", text)
        if not m:
            continue
        objs = []
        for _, t in s[i + 1:]:
            oid = t[:len(t)] if t in ids else (t[:4] if t[:4] in ids and len(t) <= 5 else None)
            if oid is None or oid.startswith("SH"):
                break
            if oid not in objs:
                objs.append(oid)
        sheets.append({"id": m.group(1), "name": s[i - 1][1], "objects": objs})
    order = {sh["id"]: n for n, sh in enumerate(manifest["sheets"])}
    sheets = sorted({sh["id"]: sh for sh in sheets if sh["id"] in order}.values(), key=lambda sh: order[sh["id"]])
    for sh in sheets:
        sh["name"] = next(x["name"] for x in manifest["sheets"] if x["id"] == sh["id"])
    return {"app": app, "generated_by": "powerbi/tools/extract_sheet_objects.py",
            "list_box_captions": dict(sorted(captions.items())), "sheets": sheets}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", required=True, action="append")
    for app in ap.parse_args(argv).app:
        OUT.mkdir(parents=True, exist_ok=True)
        out = extract(app)
        (OUT / f"{app}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{app}: {len(out['sheets'])} sheets, {len(out['list_box_captions'])} list boxes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
