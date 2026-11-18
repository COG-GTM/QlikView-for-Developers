"""Minimal QlikView load-script reader: splits a .qvs into LOAD/SELECT chains per table label.

Used to (a) decide which inventory tables are plain loads of one converted source, so
their row counts can be checked against the Parquet output, and (b) build the parity
harness's source model (one DuckDB view per Qlik table) for apps made only of plain loads.
Anything it does not understand is reported as "derived" and left to the per-app model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

KEYWORDS = ("LOAD", "SELECT", "SQL", "MAPPING", "CROSSTABLE", "GENERIC", "HIERARCHY", "HIERARCHYBELONGSTO",
            "NOCONCATENATE", "CONCATENATE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "KEEP", "ADD", "BUFFER",
            "FIRST", "DISTINCT", "INTERVALMATCH", "REPLACE", "SEMANTIC")
LABEL_RE = re.compile(r"^\s*(\[[^\]]+\]|[A-Za-z_%$][\w %$.\-]*?)\s*:\s*(?=(?:" + "|".join(KEYWORDS) + r")\b)",
                      re.I | re.S)
TARGET_PREFIX_RE = re.compile(r"\b(?:CONCATENATE|JOIN|KEEP)\s*\(\s*\[?([^\])]+?)\]?\s*\)", re.I)
TRANSFORM_PREFIX_RE = re.compile(r"\b(CONCATENATE|JOIN|KEEP|MAPPING|CROSSTABLE|GENERIC|HIERARCHY\w*|INTERVALMATCH|"
                                 r"FIRST|ADD|REPLACE|SEMANTIC)\b", re.I)


@dataclass
class Field:
    expr: str
    name: str

    @property
    def is_direct(self) -> bool:
        return self.expr == "*" or bool(re.fullmatch(r"\[[^\]]+\]|`[^`]+`|\"[^\"]+\"|[\w%#$.]+", self.expr.strip()))

    @property
    def source_name(self) -> str:
        return unquote(self.expr)


@dataclass
class Load:
    label: str | None
    prefix: str
    fields: list[Field]
    source_kind: str  # file | sql | resident | inline | autogenerate | none
    source: str | None
    clauses: list[str] = field(default_factory=list)
    distinct: bool = False
    text: str = ""
    preceding: list["Load"] = field(default_factory=list)

    @property
    def target(self) -> str | None:
        m = TARGET_PREFIX_RE.search(self.prefix)
        return m.group(1).strip() if m else None

    @property
    def is_plain(self) -> bool:
        layers = [self, *self.preceding]
        return (self.source_kind in ("file", "sql")
                and not TRANSFORM_PREFIX_RE.search(self.prefix)
                and not any(ly.clauses or ly.distinct for ly in layers)
                and all(f.is_direct for ly in layers for f in ly.fields))

    @property
    def output_fields(self) -> list[Field]:
        return (self.preceding[0] if self.preceding else self).fields


def unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] + s[-1] in ("[]", "``", '""', "''"):
        return s[1:-1]
    return s


def strip_comments(text: str) -> str:
    out, i, n = [], 0, len(text)
    quote = None
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "['\"`":
            quote = "]" if c == "[" else c
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r"(?im)^\s*REM\b[^;]*;", "", "".join(out))


def split_statements(text: str) -> list[str]:
    stmts, buf, quote = [], [], None
    for c in strip_comments(text):
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            continue
        if c in "['\"`":
            quote = "]" if c == "[" else c
        if c == ";":
            stmts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
    if "".join(buf).strip():
        stmts.append("".join(buf).strip())
    return [s for s in stmts if s]


def split_top(s: str, sep: str = ",") -> list[str]:
    parts, buf, depth, quote = [], [], 0, None
    for c in s:
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            continue
        if c in "['\"`":
            quote = "]" if c == "[" else c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == sep and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
    if "".join(buf).strip():
        parts.append("".join(buf).strip())
    return parts


def _find_kw(s: str, kw: str) -> int:
    """Index of keyword at top level (outside quotes/brackets/parens), or -1."""
    depth, quote, i = 0, None, 0
    pat = re.compile(r"\b%s\b" % kw, re.I)
    while i < len(s):
        c = s[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "['\"`":
            quote = "]" if c == "[" else c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and pat.match(s, i) and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] == "_")):
            return i
        i += 1
    return -1


def parse_fields(s: str) -> list[Field]:
    fields = []
    for part in split_top(s):
        m = re.match(r"^(.*?)\s+as\s+(\[[^\]]+\]|`[^`]+`|\"[^\"]+\"|[\w%#$.]+)\s*$", part, re.I | re.S)
        if m:
            fields.append(Field(m.group(1).strip(), unquote(m.group(2))))
        else:
            fields.append(Field(part.strip(), unquote(part)))
    return fields


def parse_statement(stmt: str) -> Load | None:
    label = None
    m = LABEL_RE.match(stmt)
    if m:
        label = unquote(m.group(1))
        stmt = stmt[m.end():]
    load_at, sql_at = _find_kw(stmt, "LOAD"), _find_kw(stmt, "SELECT")
    if load_at < 0 and sql_at < 0:
        return None
    if load_at >= 0 and (sql_at < 0 or load_at < sql_at):
        prefix, body = stmt[:load_at], stmt[load_at + 4:]
        distinct = bool(re.match(r"\s*DISTINCT\b", body, re.I))
        if distinct:
            body = re.sub(r"^\s*DISTINCT\b", "", body, flags=re.I)
        ends = {kw: _find_kw(body, kw) for kw in ("FROM", "RESIDENT", "INLINE", "AUTOGENERATE", "WHERE", "WHILE",
                                                  "GROUP", "ORDER")}
        cut = min([v for v in ends.values() if v >= 0], default=len(body))
        fields = parse_fields(body[:cut])
        rest = body[cut:]
        kind, source = "none", None
        if ends["FROM"] >= 0:
            kind = "file"
            src = rest[4:].strip()
            mm = re.match(r"(\[[^\]]+\]|'[^']+'|\S+)", src)
            source = unquote(mm.group(1)) if mm else src
        elif ends["RESIDENT"] >= 0:
            kind = "resident"
            mm = re.match(r"\s*RESIDENT\s+(\[[^\]]+\]|\S+)", rest, re.I)
            source = unquote(mm.group(1)) if mm else None
        elif ends["INLINE"] >= 0:
            kind = "inline"
        elif ends["AUTOGENERATE"] >= 0:
            kind = "autogenerate"
        clauses = [kw for kw in ("WHERE", "WHILE", "GROUP", "ORDER") if _find_kw(rest, kw) >= 0]
        return Load(label, prefix.strip(), fields, kind, source, clauses, distinct, stmt)
    prefix, body = stmt[:sql_at], stmt[sql_at + 6:]
    prefix = re.sub(r"\bSQL\s*$", "", prefix.strip(), flags=re.I).strip()
    frm = _find_kw(body, "FROM")
    fields = parse_fields(body[:frm]) if frm >= 0 else []
    mm = re.match(r"\s*FROM\s+(`[^`]+`|\[[^\]]+\]|\"[^\"]+\"|\S+)", body[frm:], re.I) if frm >= 0 else None
    source = unquote(mm.group(1)) if mm else None
    clauses = [kw for kw in ("WHERE", "GROUP", "ORDER", "JOIN") if _find_kw(body[frm:] if frm >= 0 else "", kw) >= 0]
    return Load(label, prefix, fields, "sql", source, clauses, False, stmt)


def parse_script(text: str) -> list[Load]:
    """Return loads in script order; preceding loads are folded into the load they read from."""
    loads, pending = [], []
    for stmt in split_statements(text):
        ld = parse_statement(stmt)
        if ld is None:
            continue
        if ld.source_kind == "none":
            pending.append(ld)
            continue
        if pending:
            top = pending[0]
            ld.preceding = pending
            ld.label = ld.label or top.label
            ld.prefix = (top.prefix + " " + ld.prefix).strip()
            pending = []
        loads.append(ld)
    return loads


def table_loads(loads: list[Load]) -> dict[str, list[Load]]:
    """Group loads by the table they end up in (label, or explicit CONCATENATE/JOIN/KEEP target)."""
    tables: dict[str, list[Load]] = {}
    last = None
    for ld in loads:
        name = ld.target or ld.label
        if name is None and re.search(r"\b(JOIN|CONCATENATE)\b", ld.prefix, re.I):
            name = last
        if name is None:
            continue
        tables.setdefault(name, []).append(ld)
        last = name
    return tables


def plain_tables(text: str) -> dict[str, Load]:
    """Tables built by exactly one plain load of one source and never targeted again."""
    loads = parse_script(text)
    grouped = table_loads(loads)
    fieldsets = {}
    for ld in loads:
        fieldsets.setdefault(frozenset(f.name for f in ld.output_fields), []).append(ld)
    out = {}
    for name, lds in grouped.items():
        if len(lds) != 1 or not lds[0].is_plain:
            continue
        ld = lds[0]
        if len(fieldsets[frozenset(f.name for f in ld.output_fields)]) > 1:
            continue  # QlikView would auto-concatenate identical field sets
        if any(o.source_kind == "resident" and o.source == name and not o.label for o in loads):
            continue
        out[name] = ld
    return out
