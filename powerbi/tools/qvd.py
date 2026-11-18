"""Minimal, dependency-light QVD reader (numpy only).

QVD layout: an XML header (``QvdTableHeader``) terminated by ``\\r\\n\\0``, then
per-field symbol tables and a bit-packed index table. Offsets in the header are
relative to the first byte after the XML header.

Symbol type bytes: 1=int32, 2=float64, 4=NUL-terminated string,
5=int32+string (dual), 6=float64+string (dual).
Each record of the index table is ``RecordByteSize`` bytes read as one
little-endian integer; a field's symbol index is
``((record >> BitOffset) & (2**BitWidth - 1)) + Bias``. Negative indexes are NULL.
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_HEADER_END = b"</QvdTableHeader>"


@dataclass
class QvdField:
    name: str
    bit_offset: int
    bit_width: int
    bias: int
    offset: int
    length: int
    no_of_symbols: int
    number_format: dict
    tags: list[str]
    # symbol values: (number or None, text or None)
    symbols: list[tuple[float | int | None, str | None]] = field(default_factory=list)
    symbol_types: set[int] = field(default_factory=set)


@dataclass
class QvdFile:
    path: Path
    table_name: str
    no_of_records: int
    record_byte_size: int
    fields: list[QvdField]
    header: dict
    # per field: int array of symbol indexes (negative = NULL)
    indexes: dict[str, np.ndarray]


def _text(el, tag, default=""):
    child = el.find(tag)
    return child.text if child is not None and child.text is not None else default


def _parse_symbols(buf: bytes, f: QvdField) -> None:
    pos, end = f.offset, f.offset + f.length
    syms = []
    types = set()
    while pos < end:
        t = buf[pos]
        pos += 1
        types.add(t)
        if t == 1:
            (v,) = struct.unpack_from("<i", buf, pos)
            pos += 4
            syms.append((v, None))
        elif t == 2:
            (v,) = struct.unpack_from("<d", buf, pos)
            pos += 8
            syms.append((v, None))
        elif t == 4:
            z = buf.index(b"\0", pos)
            syms.append((None, buf[pos:z].decode("utf-8")))
            pos = z + 1
        elif t in (5, 6):
            if t == 5:
                (v,) = struct.unpack_from("<i", buf, pos)
                pos += 4
            else:
                (v,) = struct.unpack_from("<d", buf, pos)
                pos += 8
            z = buf.index(b"\0", pos)
            syms.append((v, buf[pos:z].decode("utf-8")))
            pos = z + 1
        else:
            raise ValueError(f"{f.name}: unknown QVD symbol type {t} at {pos - 1}")
    if len(syms) != f.no_of_symbols:
        raise ValueError(f"{f.name}: expected {f.no_of_symbols} symbols, parsed {len(syms)}")
    f.symbols = syms
    f.symbol_types = types


def _unpack_indexes(buf: bytes, offset: int, n: int, rbs: int, fields: list[QvdField]) -> dict:
    raw = np.frombuffer(buf, dtype=np.uint8, count=n * rbs, offset=offset).reshape(n, rbs)
    out = {}
    for f in fields:
        if f.bit_width == 0:
            idx = np.zeros(n, dtype=np.int64)
        else:
            b0 = f.bit_offset // 8
            b1 = (f.bit_offset + f.bit_width - 1) // 8
            if b1 - b0 + 1 > 8:
                raise ValueError(f"{f.name}: field spans more than 8 bytes")
            acc = np.zeros(n, dtype=np.uint64)
            for i, b in enumerate(range(b0, b1 + 1)):
                acc |= raw[:, b].astype(np.uint64) << np.uint64(8 * i)
            acc >>= np.uint64(f.bit_offset - 8 * b0)
            acc &= np.uint64((1 << f.bit_width) - 1)
            idx = acc.astype(np.int64)
        out[f.name] = idx + f.bias
    return out


def read_qvd(path: str | Path) -> QvdFile:
    path = Path(path)
    buf = path.read_bytes()
    hend = buf.index(_HEADER_END) + len(_HEADER_END)
    root = ET.fromstring(buf[:hend].decode("utf-8"))
    # binary section starts after the header terminator (\r\n and/or \0)
    start = hend
    while start < len(buf) and buf[start] in (0x0D, 0x0A):
        start += 1
    if start < len(buf) and buf[start] == 0:
        start += 1
    body = buf[start:]

    fields = []
    for fh in root.find("Fields").findall("QvdFieldHeader"):
        nf = fh.find("NumberFormat")
        tags_el = fh.find("Tags")
        fields.append(
            QvdField(
                name=_text(fh, "FieldName"),
                bit_offset=int(_text(fh, "BitOffset", "0")),
                bit_width=int(_text(fh, "BitWidth", "0")),
                bias=int(_text(fh, "Bias", "0")),
                offset=int(_text(fh, "Offset", "0")),
                length=int(_text(fh, "Length", "0")),
                no_of_symbols=int(_text(fh, "NoOfSymbols", "0")),
                number_format={c.tag: (c.text or "") for c in nf} if nf is not None else {},
                tags=[t.text for t in tags_el.findall("String")] if tags_el is not None else [],
            )
        )
    for f in fields:
        _parse_symbols(body, f)
    n = int(_text(root, "NoOfRecords", "0"))
    rbs = int(_text(root, "RecordByteSize", "0"))
    idx_offset = int(_text(root, "Offset", "0"))
    indexes = _unpack_indexes(body, idx_offset, n, rbs, fields)
    for f in fields:
        bad = indexes[f.name] >= len(f.symbols)
        if bad.any():
            raise ValueError(f"{path.name}:{f.name}: symbol index out of range")
    header = {
        "TableName": _text(root, "TableName"),
        "CreatorDoc": _text(root, "CreatorDoc"),
        "CreateUtcTime": _text(root, "CreateUtcTime"),
        "QvBuildNo": _text(root, "QvBuildNo"),
    }
    return QvdFile(path, header["TableName"], n, rbs, fields, header, indexes)
