import sys
from pathlib import Path

import pytest

POWERBI = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(POWERBI / "tools"), str(POWERBI / "parity")]

CH03 = "Chapter03__Solution_Chapter 3_Airline Operations"


def pytest_collection_modifyitems(config, items):
    parquet = POWERBI / "data" / "parquet"
    if parquet.exists():
        return
    skip = pytest.mark.skip(reason="run powerbi/tools/convert_sources.py first")
    for item in items:
        if "needs_parquet" in item.keywords:
            item.add_marker(skip)
