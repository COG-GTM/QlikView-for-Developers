"""Parser for QlikView chart expressions (the subset used by the inventory's KPIs).

``parse(text)`` returns an AST of small dataclasses. ``expand_dollars`` performs $(var),
$(var(args)) and $(=expr) expansion before parsing. Anything outside the supported subset
raises ``Unsupported`` with a reason; the harness records that KPI as unsupported rather
than guessing, so per-app work can extend the subset where needed.

Supported: numbers, 'strings', [field]/field refs, + - * / & unary -, comparisons,
AND/OR/NOT, If(), Sum/Count/Avg/Min/Max/Only with DISTINCT, TOTAL [<fields>] and set
analysis ({$}, {1}, {$<F={v,..}, F={"<=n"}>}, set operators + - * /), Aggr(expr, dims),
Num()/Fabs()/RangeSum() pass-through.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class Unsupported(Exception):
    pass


AGGS = {"sum", "count", "avg", "min", "max", "only"}
UNSUPPORTED_FUNCS = {"secondarydimensionality", "match", "column", "above", "below",
                     "before", "after", "rank", "getselectedcount", "getfieldselections", "rowno", "fieldindex",
                     "firstsortedvalue", "concat", "stdev", "median", "fractile", "e", "p"}
ROW_FUNCS = ("if", "num", "fabs", "rangesum", "round", "alt", "dimensionality", "pick", "class", "replace")


@dataclass
class Num:
    value: float


@dataclass
class Str:
    value: str


@dataclass
class FieldRef:
    name: str


@dataclass
class BinOp:
    op: str
    left: object
    right: object


@dataclass
class Unary:
    op: str
    operand: object


@dataclass
class Func:
    name: str
    args: list


@dataclass
class SetModifier:
    field: str
    op: str  # '=', '+=', '-=', '*='
    values: list  # list[(kind, value)] kind in num|str|search|all
    exclude_all: bool = False  # F = (empty) -> clear selections on F


@dataclass
class SetTerm:
    identifier: str  # '$', '1', '0' or an alternate state name
    modifiers: list[SetModifier] = field(default_factory=list)


@dataclass
class SetOp:
    op: str
    left: object
    right: object


@dataclass
class Agg:
    func: str
    arg: object
    distinct: bool = False
    total: list[str] | None = None  # None = no TOTAL; [] = TOTAL over everything
    set_expr: object = None


@dataclass
class Aggr:
    expr: object
    dims: list[str]


# ------------------------------------------------------------------ dollar expansion

DOLLAR_RE = re.compile(r"\$\(")


def expand_dollars(text: str, variables: dict[str, str], evaluate=None, depth: int = 0) -> str:
    """Expand $(var), $(var(a,b)) with $1..$n, and $(=expr) via ``evaluate(expr) -> str``."""
    if depth > 10:
        raise Unsupported("dollar expansion too deep")
    out, i = [], 0
    while True:
        m = DOLLAR_RE.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        j, depth_p = m.end(), 1
        while j < len(text) and depth_p:
            depth_p += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        inner = expand_dollars(text[m.end():j - 1], variables, evaluate, depth + 1)
        if inner.startswith("="):
            if evaluate is None:
                raise Unsupported(f"$(={inner[1:]}) needs evaluation")
            out.append(evaluate(inner[1:]))
        elif not inner.strip():
            out.append("")  # $() of a name that evaluated to null expands to nothing
        else:
            mm = re.fullmatch(r"\s*([\w.]+)\s*(?:\((.*)\))?\s*", inner, re.S)
            if not mm or mm.group(1) not in variables:
                raise Unsupported(f"variable {inner.strip()!r} is not defined in the manifest")
            value = variables[mm.group(1)]
            if mm.group(2) is not None:
                for n, arg in enumerate([a.strip() for a in mm.group(2).split(",")], start=1):
                    value = value.replace(f"${n}", arg)
            out.append(expand_dollars(value, variables, evaluate, depth + 1))
        i = j
    return "".join(out)


# ------------------------------------------------------------------ tokenizer

TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+)
  | (?P<field>\[[^\]]*\])
  | (?P<str>'(?:[^']|'')*')
  | (?P<dq>"(?:[^"]|"")*")
  | (?P<op><>|<=|>=|\+=|-=|\*=|[-+*/&=<>(),{}$])
  | (?P<ident>[A-Za-z_%#][\w%#.]*)
""", re.X)


def tokenize(text: str) -> list[tuple[str, str]]:
    toks, i = [], 0
    while i < len(text):
        m = TOKEN_RE.match(text, i)
        if not m:
            raise Unsupported(f"cannot tokenize near {text[i:i + 20]!r}")
        i = m.end()
        kind = m.lastgroup
        if kind != "ws":
            toks.append((kind, m.group()))
    toks.append(("eof", ""))
    return toks


class Parser:
    def __init__(self, text: str):
        self.toks = tokenize(text)
        self.i = 0

    def peek(self, k=0):
        return self.toks[self.i + k]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def accept(self, value: str) -> bool:
        k, v = self.peek()
        if k in ("op", "ident") and v.lower() == value.lower():
            self.i += 1
            return True
        return False

    def expect(self, value: str):
        if not self.accept(value):
            raise Unsupported(f"expected {value!r} at {self.peek()[1]!r}")

    def parse(self):
        self.accept("=")
        node = self.expr()
        if self.peek()[0] != "eof":
            raise Unsupported(f"unexpected {self.peek()[1]!r}")
        return node

    def expr(self):
        node = self.and_()
        while self.accept("or"):
            node = BinOp("or", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.accept("and"):
            node = BinOp("and", node, self.not_())
        return node

    def not_(self):
        if self.accept("not"):
            return Unary("not", self.not_())
        return self.cmp()

    def cmp(self):
        node = self.add()
        k, v = self.peek()
        if k == "op" and v in ("=", "<>", "<", ">", "<=", ">="):
            self.next()
            node = BinOp(v, node, self.add())
        return node

    def add(self):
        node = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in "+-&":
            node = BinOp(self.next()[1], node, self.mul())
        return node

    def mul(self):
        node = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in "*/":
            node = BinOp(self.next()[1], node, self.unary())
        return node

    def unary(self):
        if self.accept("-"):
            return Unary("-", self.unary())
        if self.accept("+"):
            return self.unary()
        return self.primary()

    def primary(self):
        k, v = self.next()
        if k == "num":
            return Num(float(v))
        if k == "str":
            return Str(v[1:-1].replace("''", "'"))
        if k == "field":
            return FieldRef(v[1:-1])
        if k == "dq":
            return FieldRef(v[1:-1])
        if k == "op" and v == "(":
            node = self.expr()
            self.expect(")")
            return node
        if k == "ident":
            if self.peek() == ("op", "("):
                self.next()
                return self.call(v)
            return FieldRef(v)
        raise Unsupported(f"unexpected token {v!r}")

    def call(self, name: str):
        lname = name.lower()
        if lname in UNSUPPORTED_FUNCS:
            raise Unsupported(f"{name}() is not supported by the source evaluator")
        if lname in AGGS:
            set_expr = self.set_expression() if self.peek() == ("op", "{") else None
            distinct = self.accept("distinct")
            total = None
            if self.accept("total"):
                total = []
                if self.accept("<"):
                    while not self.accept(">"):
                        k, v = self.next()
                        if k == "field":
                            total.append(v[1:-1])
                        elif k == "ident":
                            total.append(v)
                        elif v != ",":
                            raise Unsupported(f"bad TOTAL field list near {v!r}")
            arg = self.expr()
            self.expect(")")
            return Agg(lname, arg, distinct, total, set_expr)
        if lname == "aggr":
            inner = self.expr()
            dims = []
            while self.accept(","):
                k, v = self.next()
                if k not in ("field", "ident"):
                    raise Unsupported("Aggr() dimension must be a field")
                dims.append(v[1:-1] if k == "field" else v)
            self.expect(")")
            return Aggr(inner, dims)
        args = []
        if not self.accept(")"):
            args.append(self.expr())
            while self.accept(","):
                args.append(self.expr())
            self.expect(")")
        if lname not in ROW_FUNCS:
            raise Unsupported(f"{name}() is not supported by the source evaluator")
        return Func(lname, args)

    # set analysis -------------------------------------------------------
    def set_expression(self):
        self.expect("{")
        node = self.set_term()
        while self.peek()[0] == "op" and self.peek()[1] in "+-*/":
            op = self.next()[1]
            node = SetOp(op, node, self.set_term())
        self.expect("}")
        return node

    def set_term(self):
        if self.accept("("):
            node = self.set_term()
            while self.peek()[0] == "op" and self.peek()[1] in "+-*/":
                node = SetOp(self.next()[1], node, self.set_term())
            self.expect(")")
            return node
        k, v = self.peek()
        identifier = "$"
        if k == "op" and v == "$":
            self.next()
        elif k == "num" and v in ("1", "0"):
            self.next()
            identifier = v
        elif k in ("field", "ident"):
            self.next()
            identifier = v[1:-1] if k == "field" else v
        mods = self.modifiers() if self.peek() == ("op", "<") else []
        return SetTerm(identifier, mods)

    def modifiers(self):
        self.expect("<")
        mods = []
        while True:
            k, v = self.next()
            if k not in ("field", "ident"):
                raise Unsupported(f"bad set modifier near {v!r}")
            fname = v[1:-1] if k == "field" else v
            op = self.next()[1]
            if op not in ("=", "+=", "-=", "*="):
                raise Unsupported(f"set modifier operator {op!r} not supported")
            if self.peek() in (("op", ","), ("op", ">")):
                mods.append(SetModifier(fname, op, [], exclude_all=True))
            else:
                if self.peek()[0] == "ident" and self.peek()[1].lower() in ("e", "p"):
                    func = self.next()[1].lower()
                    self.expect("(")
                    inner = self.set_expression() if self.peek() == ("op", "{") else None
                    kk, vv = self.next()
                    if kk not in ("field", "ident"):
                        raise Unsupported(f"bad {func}() argument near {vv!r}")
                    self.expect(")")
                    mods.append(SetModifier(fname, op, [(func, (vv[1:-1] if kk == "field" else vv, inner))]))
                    if self.accept(">"):
                        return mods
                    self.expect(",")
                    continue
                self.expect("{")
                values = []
                while not self.accept("}"):
                    kk, vv = self.next()
                    if kk == "num":
                        values.append(("num", float(vv)))
                    elif kk == "str":
                        values.append(("str", vv[1:-1].replace("''", "'")))
                    elif kk == "dq":
                        values.append(("search", vv[1:-1]))
                    elif kk == "op" and vv == "-":
                        nk, nv = self.next()
                        values.append(("num", -float(nv)))
                    elif vv != ",":
                        values.append(("str", vv))
                mods.append(SetModifier(fname, op, values))
            if self.accept(">"):
                return mods
            self.expect(",")


def parse(text: str):
    return Parser(text).parse()


def walk(node):
    """Every AST node under (and including) ``node``."""
    yield node
    if hasattr(node, "__dataclass_fields__"):
        for f in node.__dataclass_fields__:
            v = getattr(node, f)
            for x in (v if isinstance(v, list) else [v]):
                if hasattr(x, "__dataclass_fields__"):
                    yield from walk(x)


def fields_in(node) -> set[str]:
    """Field names referenced anywhere in an AST (including set modifiers and TOTAL/Aggr dims)."""
    out: set[str] = set()

    def walk(n):
        if isinstance(n, FieldRef):
            out.add(n.name)
        elif isinstance(n, SetModifier):
            out.add(n.field)
        elif isinstance(n, Aggr):
            out.update(n.dims)
        elif isinstance(n, Agg) and n.total:
            out.update(n.total)
        if hasattr(n, "__dataclass_fields__"):
            for f in n.__dataclass_fields__:
                v = getattr(n, f)
                for x in (v if isinstance(v, list) else [v]):
                    if hasattr(x, "__dataclass_fields__"):
                        walk(x)
    walk(node)
    return out
