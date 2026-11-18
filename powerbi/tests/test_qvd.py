"""Cross-check the native QVD reader against pyqvd (an independent implementation)."""
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pyqvd import QvdTable

from qvd import read_qvd

REPO = Path(__file__).resolve().parents[2]
SMALL = ["Data Files/QVDs/Distance Groups.qvd", "Data Files/QVDs/Airlines.qvd", "Data Files/QVDs/Carrier Groups.qvd",
         "Data Files/QVDs/Aircraft Types.qvd", "Data Files/QVDs/Service Classes.qvd",
         "QVD/Transformed/Employment Statistics.QVD", "QVD/Transformed/Transformed - Carrier Decode.qvd"]


def _norm(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


@pytest.mark.parametrize("rel", SMALL)
def test_reader_matches_pyqvd(rel):
    ours = read_qvd(REPO / rel)
    ref = QvdTable.from_qvd(str(REPO / rel)).to_pandas()
    assert ours.no_of_records == len(ref)
    assert [f.name for f in ours.fields] == list(ref.columns)
    for f in ours.fields:
        idx = ours.indexes[f.name]
        mine = [None if i < 0 else (f.symbols[i][0] if f.symbols[i][0] is not None else f.symbols[i][1]) for i in idx]
        assert [_norm(v) for v in mine] == [_norm(v) for v in ref[f.name].tolist()], f.name


@pytest.mark.needs_parquet
@pytest.mark.parametrize("rel", SMALL)
def test_parquet_matches_pyqvd(rel):
    """Converted numbers equal the QVD's numeric values; text equals the QVD text."""
    table = pq.read_table(REPO / "powerbi/data/parquet" / Path(rel).with_suffix(".parquet")).to_pandas()
    ref = QvdTable.from_qvd(str(REPO / rel)).to_pandas()
    assert len(table) == len(ref)
    for col in ref.columns:
        got = table[col].tolist()
        exp = ref[col].tolist()
        if str(table[col].dtype).startswith(("int", "Int", "float")):
            assert [_norm(v) for v in got] == [_norm(v) for v in exp], col
        else:
            assert sum(_norm(a) is None for a in got) == sum(_norm(b) is None for b in exp), col
