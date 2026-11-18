"""Every report visual titled 'Top N ...' (QlikView's capped dimension) keeps only the top N rows, sorted by its measure."""
import json
import re
from pathlib import Path

import pytest

APPS = Path(__file__).resolve().parents[1] / "apps"
REPORTS = sorted(APPS.glob("*/*.Report/report.json"))


def top_n_visuals(report: Path):
    for sec in json.loads(report.read_text())["sections"]:
        for vc in sec["visualContainers"]:
            single = json.loads(vc["config"])["singleVisual"]
            if single["visualType"] == "slicer":
                continue
            title = json.dumps(single.get("vcObjects", {}).get("title", ""))
            if m := re.search(r"\bTop (\d+)\b", title):
                yield sec["displayName"], int(m.group(1)), vc, single


@pytest.mark.parametrize("report", REPORTS, ids=[r.parts[-3] for r in REPORTS])
def test_top_n_visuals_are_capped(report):
    for page, n, vc, single in top_n_visuals(report):
        top = [f for f in json.loads(vc["filters"]) if f["type"] == "TopN"]
        assert len(top) == 1, f"{page}: Top {n} visual without a TopN filter"
        assert top[0]["filter"]["From"][0]["Expression"]["Subquery"]["Query"]["Top"] == n
        order = single["prototypeQuery"].get("OrderBy") or single.get("orderBy") or []
        assert order and order[0]["Direction"] == 2, f"{page}: Top {n} visual not sorted descending"
