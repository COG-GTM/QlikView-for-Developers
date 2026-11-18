# Parity harness

Goal: every KPI/chart expression of a migrated app gives the same numbers in Power BI (DAX)
as QlikView's expression computed from the same source data.

```
manifest KPIs ──► harness.py source ──► expected/<app>.json.gz      (Linux/CI, from Parquet)
PBIP (TMDL)   ──► harness.py queries ─► dax/<app>.queries.json
                  run_dax.ps1 (Windows, Power BI Desktop) ──► dax/<app>.results.json
                  harness.py compare ──► reports/<app>.md / .json   (pass / fail / missing / unsupported)
```

## 1. Source side (`harness.py source`)

* Reads `inventory/manifests/<app>.json` → every entry of `kpis` (expressions with
  variables already expanded) and the chart dimensions.
* Builds the source model: one DuckDB view per Qlik table over the Parquet. Generated from
  the load script for plain-load apps (Ch03/04/06/07); otherwise from
  `parity/models/<app>.sql`, written by that app's migration (see `parity/models/README.md`).
  View row counts are recorded next to the inventory's.
* Parses each expression (`qlik_expr.py`) and evaluates it (`engine.py`) with no selections:
  aggregations with `DISTINCT`, `TOTAL <fields>`, set analysis (`$`, `1`, field value lists,
  numeric search strings, `+ - * /`), `Aggr()`, `If()`, arithmetic, `$(var)` / `$(=expr)`.
  Fields from several tables are joined along shared key fields (Qlik associations).
* Apps whose sheets have no chart expressions (the Ch10 ETL demos) add `parity/checks/<app>.json`:
  data checks with the same shape as KPIs (`object`, `label`, `expression`, `dims`, ids `CHK01#1@…`)
  that pin the transformed table itself; they go through `source`, `queries` and `compare` unchanged.
* Grains: grand total, the chart's dimensions, and each drill-down level / cyclic
  alternative of grouped dimensions (Ch03 `Time` = Year, Year+Month).
* Unsupported constructs (`Dimensionality()`, `Pick()`, alternate states, `e()`/`p()`,
  calculated dimensions, variables defined only in missing include files) are listed as
  `unsupported` with the reason instead of being guessed; extend `qlik_expr.py`/`engine.py`
  when an app needs them.
* Apps with no chart expressions (Chapter 10 ETL demos such as `Hierarchy example`) get
  full-table parity instead: every row of each model table, columns in Qlik field order,
  under `tables` with id `table:<Qlik table>`.
* Result ids: `<object>#<n>@<grain>` (e.g. `CH01#1@Year+Month`). Output is gzip JSON,
  byte-reproducible (CI checks the committed Chapter 03 file).

## 2. DAX side (`harness.py queries` + `run_dax.ps1`)

* `queries` reads the app's TMDL: KPI → measure by `annotation ParityKey`; Qlik field →
  column by `sourceColumn`. Each result id becomes
  `EVALUATE ROW("value", [M])` or `EVALUATE SUMMARIZECOLUMNS('T'[c1], …, "value", [M])`.
  KPIs without an annotated measure are listed under `unmapped`. Full-table entries become
  `EVALUATE SELECTCOLUMNS('T', "field", 'T'[col], …)`, matching columns by name or
  `sourceColumn` (so DAX calculated columns can stand in for script-generated fields).
* `run_dax.ps1` (Windows PowerShell 5.1+) runs the queries with ADOMD.NET against the model
  open in Power BI Desktop (port from `msmdsrv.port.txt` under
  `%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces`), or against any
  XMLA endpoint via `-Server`/`-Database` (Premium/Fabric workspace, or Analysis Services).
  It writes `{"app", "produced_by", "executed_at", "results": [{"id", "columns", "rows"}]}`.
* Procedure on the Windows machine: get the Parquet (convert under WSL or download the CI
  artifact) → open `apps/<Slug>/<Slug>.pbip` → set `DataRoot` → Refresh → run `queries`
  then `run_dax.ps1` → run `compare` → commit `reports/<app>.md` with the app's PR.
* Not run yet: no Windows machine or Power BI workspace is connected to this project.
  When one is, the same script runs unattended against a published model's XMLA endpoint.

## 3. Comparison (`harness.py compare`)

* Rows are matched on dimension values (numbers compared numerically, dates by ISO date,
  text exactly). Blank and 0 are equal (Qlik hides zero rows, DAX drops blank rows).
* Full-table results must match as a multiset of rows, each cell compared like a dimension value.
* Values: `rel_tol=1e-9`, `abs_tol=1e-6` by default (`--rel-tol`, `--abs-tol`).
* Exit code 0 only when every evaluated result passes; `fail` lists up to 5 example rows.

## 4. Known semantic gaps to keep in mind

* Baseline is "no selections"; apps that open with saved selections or default bookmarks
  should add those as an explicit state in their own test.
* Chart presentation limits (Top 10, suppress-zero, sorting) are not compared; the full
  result set is.
* Qlik's associative model is approximated by left joins from the largest table; measures
  over dimension-only fields with unassociated rows may need an app-specific model view.
