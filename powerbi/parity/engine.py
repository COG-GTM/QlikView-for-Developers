"""Source-side evaluator: recompute Qlik chart expressions straight from the converted Parquet.

The source model is one DuckDB view per Qlik table. For apps whose recovered load script
only does plain loads of converted sources, the views are generated from the script; for
the others a per-app ``models/<manifest name>.sql`` (written by that app's migration)
defines them. Qlik's associative model is approximated by joining the tables an expression
needs along their shared field names (the %-keys), starting from the largest (fact) table.

The baseline state is "no selections" (the app as opened with selections cleared); every
expression is evaluated for its chart's grand total and for each chart-dimension grain.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import deque
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import qlik_expr as q  # noqa: E402
from qlik_script import plain_tables  # noqa: E402
from verify_conversion import catalog_table, resolve_source  # noqa: E402

POWERBI = Path(__file__).resolve().parents[1]
REPO = POWERBI.parent
INVENTORY = POWERBI / "inventory"
MODELS = Path(__file__).resolve().parent / "models"
CATALOG = POWERBI / "data" / "catalog.json"


class ModelUnavailable(Exception):
    pass


def qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ql(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class SourceModel:
    def __init__(self, app: str):
        self.app = app
        self.manifest = json.loads((INVENTORY / "manifests" / f"{app}.json").read_text())
        self.con = duckdb.connect()
        self.table_check: list[dict] = []
        self._build()
        self.columns = {t: [r[0] for r in self.con.execute(f"DESCRIBE {qi(t)}").fetchall()] for t in self.tables}
        self.rows = {t: self.con.execute(f"SELECT count(*) FROM {qi(t)}").fetchone()[0] for t in self.tables}
        for t in self.manifest["data_model"]["tables"]:
            if t["name"] in self.rows:
                self.table_check.append({"table": t["name"], "inventory_rows": t["rows"], "model_rows": self.rows[t["name"]]})

    def _build(self):
        override = MODELS / f"{self.app}.sql"
        if override.exists():
            sql = (override.read_text().replace("{parquet}", (POWERBI / "data" / "parquet").as_posix())
                   .replace("{repo}", REPO.as_posix()))
            self.con.execute(sql)
            self.model_source = override.relative_to(REPO).as_posix()
            self.tables = [r[0] for r in self.con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type='VIEW' OR table_type='BASE TABLE'"
            ).fetchall()]
            return
        catalog = json.loads(CATALOG.read_text())
        script = (INVENTORY / self.manifest["script"]["file"]).read_text(encoding="utf-8")
        plain = plain_tables(script)
        wanted = [t["name"] for t in self.manifest["data_model"]["tables"] if not t["name"].startswith("$$")]
        missing = [t for t in wanted if t not in plain]
        if missing:
            raise ModelUnavailable(f"tables built by script transformations need models/{self.app}.sql: {missing}")
        for name in wanted:
            load = plain[name]
            resolved = resolve_source(self.manifest, load)
            ct = catalog_table(catalog, *resolved) if resolved else None
            if not ct:
                raise ModelUnavailable(f"cannot resolve source of {name!r}: {load.source}")
            path = (REPO / ct["parquet"]).as_posix()
            if any(f.expr == "*" for f in load.output_fields):
                cols = "*"
            else:
                cols = ", ".join(f"{qi(f.source_name)} AS {qi(f.name)}" for f in load.output_fields)
            self.con.execute(f"CREATE VIEW {qi(name)} AS SELECT {cols} FROM read_parquet({ql(path)})")
        self.model_source = "generated from the recovered load script (plain loads)"
        self.tables = wanted

    # ------------------------------------------------------------ joins
    def tables_with(self, fld: str) -> list[str]:
        return [t for t in self.tables if fld in self.columns[t]]

    def from_clause(self, fields: set[str]) -> tuple[str, dict[str, str]]:
        """FROM clause joining the tables that hold ``fields``; returns (sql, field -> qualified column)."""
        need = []
        for f in sorted(fields):
            holders = self.tables_with(f)
            if not holders:
                raise q.Unsupported(f"field {f!r} is not in the source model")
            if not set(holders) & set(need):
                need.append(max(holders, key=lambda t: (len(self.columns[t]) == 1, self.rows[t]))
                            if len(holders) > 1 else holders[0])
        if not need:
            need = [max(self.tables, key=self.rows.get)]
        root = max(need, key=self.rows.get)
        joined, sql = [root], f"{qi(root)} AS t0"
        for target in [t for t in need if t != root]:
            if target in joined:
                continue
            path = self._path(joined, target)
            for t in path:
                if t in joined:
                    continue
                prev = next(j for j in joined if set(self.columns[j]) & set(self.columns[t]))
                keys = sorted(set(self.columns[prev]) & set(self.columns[t]))
                a_prev, a_new = f"t{joined.index(prev)}", f"t{len(joined)}"
                on = " AND ".join(f"{a_new}.{qi(k)} = {a_prev}.{qi(k)}" for k in keys)
                sql += f" LEFT JOIN {qi(t)} AS {a_new} ON {on}"
                joined.append(t)
        colmap = {}
        for f in fields:
            idx = next(i for i, t in enumerate(joined) if f in self.columns[t])
            colmap[f] = f"t{idx}.{qi(f)}"
        for i, t in enumerate(joined):
            for c in self.columns[t]:
                colmap.setdefault(c, f"t{i}.{qi(c)}")
        return sql, colmap

    def _path(self, joined: list[str], target: str) -> list[str]:
        prev = {t: None for t in joined}
        dq = deque(joined)
        while dq:
            cur = dq.popleft()
            if cur == target:
                break
            for t in self.tables:
                if t not in prev and set(self.columns[cur]) & set(self.columns[t]):
                    prev[t] = cur
                    dq.append(t)
        if target not in prev:
            raise q.Unsupported(f"table {target!r} is not associated with {joined[0]!r}")
        path, cur = [], target
        while cur not in joined:
            path.append(cur)
            cur = prev[cur]
        return list(reversed(path))


class Evaluator:
    def __init__(self, model: SourceModel):
        self.m = model
        self.variables = {v["name"]: v.get("definition", v.get("value", "")) for v in model.manifest.get("variables", [])
                          if v.get("name")}

    # ------------------------------------------------------------ public
    def compile(self, text: str):
        expanded = q.expand_dollars(text, self.variables, self.scalar_text)
        return q.parse(expanded)

    def scalar_text(self, text: str) -> str:
        v = self.evaluate(self.compile(text), [])["value"].iloc[0] if text else None
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ""
        return str(int(v)) if isinstance(v, (int, float)) and float(v).is_integer() else str(v)

    def evaluate(self, node, dims: list[str]) -> pd.DataFrame:
        frame = self.frame(dims, q.fields_in(node))
        value = self.ev(node, dims, frame)
        out = frame.copy()
        out["value"] = value.values if isinstance(value, pd.Series) else value
        return out

    # ------------------------------------------------------------ internals
    def frame(self, dims: list[str], fields: set[str] = frozenset()) -> pd.DataFrame:
        """Dimension combinations to report: joined with the expression's fields so that fact rows whose
        key has no dimension row show up as a null member (Qlik's '-' row, Power BI's blank row)."""
        if not dims:
            return pd.DataFrame({"__all": [0]})
        frm, cols = self.m.from_clause(set(dims) | {f for f in fields if self.m.tables_with(f)})
        sel = ", ".join(f"{cols[d]} AS {qi(d)}" for d in dims)
        return self.m.con.execute(f"SELECT DISTINCT {sel} FROM {frm}").df()

    def _align(self, df: pd.DataFrame, frame: pd.DataFrame, keys: list[str]) -> pd.Series:
        if not keys:
            return pd.Series([df["value"].iloc[0] if len(df) else None] * len(frame), index=frame.index)
        merged = frame[keys].merge(df, on=keys, how="left")
        return pd.Series(merged["value"].values, index=frame.index)

    def ev(self, node, dims, frame):
        if isinstance(node, q.Num):
            return node.value
        if isinstance(node, q.Str):
            return node.value
        if isinstance(node, q.FieldRef):
            return self.ev(q.Agg("only", node), dims, frame)
        if isinstance(node, q.Unary):
            v = self.ev(node.operand, dims, frame)
            return -v if node.op == "-" else ~v.astype(bool)
        if isinstance(node, q.BinOp):
            a, b = self.ev(node.left, dims, frame), self.ev(node.right, dims, frame)
            return binop(node.op, a, b)
        if isinstance(node, q.Func):
            args = [self.ev(a, dims, frame) for a in node.args]
            return func(node.name, args, frame)
        if isinstance(node, q.Agg):
            return self.agg(node, dims, frame)
        if isinstance(node, q.Aggr):
            raise q.Unsupported("Aggr() outside an aggregation function")
        raise q.Unsupported(f"cannot evaluate {type(node).__name__}")

    def agg(self, node: q.Agg, dims, frame):
        group = list(dims) if node.total is None else [d for d in dims if d in node.total]
        if isinstance(node.arg, q.Aggr):
            if node.set_expr is not None or node.distinct:
                raise q.Unsupported("set analysis / DISTINCT on an Aggr() wrapper")
            inner_dims = list(dict.fromkeys(group + node.arg.dims))
            inner = self.evaluate(node.arg.expr, inner_dims)
            inner = inner.dropna(subset=["value"])
            fn = {"sum": "sum", "avg": "mean", "min": "min", "max": "max", "count": "count"}.get(node.func)
            if fn is None:
                raise q.Unsupported(f"{node.func}(Aggr())")
            df = inner.groupby(group, dropna=False)["value"].agg(fn).reset_index() if group else \
                pd.DataFrame({"value": [getattr(inner["value"], fn)()]})
            return self._align(df, frame, group)
        fields = q.fields_in(node.arg) | set(group) | (q.fields_in(node.set_expr) if node.set_expr else set())
        frm, cols = self.m.from_clause(fields)
        arg = row_sql(node.arg, cols)
        f = node.func
        if f == "only":
            agg = f"CASE WHEN COUNT(DISTINCT {arg}) = 1 THEN MIN({arg}) END"
        elif f == "count":
            agg = f"COUNT({'DISTINCT ' if node.distinct else ''}{arg})"
        else:
            agg = f"{ {'sum': 'SUM', 'avg': 'AVG', 'min': 'MIN', 'max': 'MAX'}[f]}({'DISTINCT ' if node.distinct else ''}{arg})"
        where = set_sql(node.set_expr, cols, self.m) if node.set_expr is not None else "TRUE"
        sel = ", ".join([f"{cols[g]} AS {qi(g)}" for g in group] + [f"{agg} AS value"])
        sql = f"SELECT {sel} FROM {frm} WHERE {where}" + (" GROUP BY ALL" if group else "")
        df = self.m.con.execute(sql).df()
        return self._align(df, frame, group)


def binop(op, a, b):
    if op == "/":
        if isinstance(b, pd.Series):
            b = b.astype("float64").where(b != 0)
        elif b == 0:
            return float("nan") if not isinstance(a, pd.Series) else a * float("nan")
        return a / b
    if op == "&":
        return (a.astype(str) if isinstance(a, pd.Series) else str(a)) + (b.astype(str) if isinstance(b, pd.Series) else str(b))
    ops = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "=": lambda: a == b, "<>": lambda: a != b,
           "<": lambda: a < b, ">": lambda: a > b, "<=": lambda: a <= b, ">=": lambda: a >= b,
           "and": lambda: a & b, "or": lambda: a | b}
    return ops[op]()


def func(name, args, frame):
    idx = frame.index

    def ser(v):
        return v if isinstance(v, pd.Series) else pd.Series([v] * len(idx), index=idx, dtype=object)
    if name == "if":
        cond = ser(args[0]).fillna(False).astype(bool)
        other = ser(args[2]) if len(args) > 2 else ser(None)
        return ser(args[1]).where(cond, other)
    if name in ("num", "round"):
        return args[0]
    if name == "fabs":
        return ser(args[0]).abs()
    if name in ("rangesum", "alt"):
        if name == "alt":
            return ser(args[0]).combine_first(ser(args[1]))
        return sum(ser(a).fillna(0) for a in args)
    raise q.Unsupported(name)


def row_sql(node, cols) -> str:
    if isinstance(node, q.Num):
        return repr(node.value)
    if isinstance(node, q.Str):
        return ql(node.value)
    if isinstance(node, q.FieldRef):
        return cols[node.name]
    if isinstance(node, q.Unary):
        return f"(-{row_sql(node.operand, cols)})" if node.op == "-" else f"(NOT {row_sql(node.operand, cols)})"
    if isinstance(node, q.BinOp):
        op = {"&": "||", "=": "=", "<>": "<>", "and": "AND", "or": "OR"}.get(node.op, node.op)
        if node.op == "/":
            return f"({row_sql(node.left, cols)} / NULLIF({row_sql(node.right, cols)}, 0))"
        if node.op == "&":
            return f"(CAST({row_sql(node.left, cols)} AS VARCHAR) || CAST({row_sql(node.right, cols)} AS VARCHAR))"
        return f"({row_sql(node.left, cols)} {op} {row_sql(node.right, cols)})"
    if isinstance(node, q.Func) and node.name == "if":
        a = [row_sql(x, cols) for x in node.args] + ["NULL"]
        return f"(CASE WHEN {a[0]} THEN {a[1]} ELSE {a[2]} END)"
    if isinstance(node, q.Func) and node.name in ("num", "round"):
        return row_sql(node.args[0], cols)
    raise q.Unsupported(f"nested aggregation or {type(node).__name__} inside an aggregation needs Aggr()")


SEARCH_CMP = re.compile(r"^\s*(<=|>=|<|>|=)\s*(-?\d+(?:\.\d+)?)\s*$")


def _value_pred(col: str, num_col: str | None, kind: str, value) -> str:
    if kind == "num":
        p = f"TRY_CAST({col} AS DOUBLE) = {value!r}"
        return f"({p} OR {num_col} = {value!r})" if num_col else p
    if kind == "search":
        m = SEARCH_CMP.match(value)
        if m:
            target = num_col or f"TRY_CAST({col} AS DOUBLE)"
            return f"{target} {m.group(1)} {m.group(2)}"
        if "*" in value or "?" in value:
            return f"CAST({col} AS VARCHAR) ILIKE {ql(value.replace('*', '%').replace('?', '_'))}"
        return f"CAST({col} AS VARCHAR) ILIKE {ql(value)}"
    return f"CAST({col} AS VARCHAR) = {ql(value)}"


def set_sql(node, cols, model: SourceModel) -> str:
    if isinstance(node, q.SetOp):
        a, b = set_sql(node.left, cols, model), set_sql(node.right, cols, model)
        return {"+": f"(({a}) OR ({b}))", "*": f"(({a}) AND ({b}))", "-": f"(({a}) AND NOT ({b}))",
                "/": f"(({a}) <> ({b}))"}[node.op]
    if node.identifier == "0":
        return "FALSE"
    preds = []
    for mod in node.modifiers:
        if mod.exclude_all:
            continue
        col = cols[mod.field]
        num_col = cols.get(f"{mod.field}__num")
        any_of = " OR ".join(_value_pred(col, num_col, k, v) for k, v in mod.values) or "FALSE"
        preds.append(f"NOT COALESCE(({any_of}), FALSE)" if mod.op == "-=" else f"COALESCE(({any_of}), FALSE)")
    return " AND ".join(preds) or "TRUE"
