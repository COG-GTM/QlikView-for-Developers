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
* Also evaluated: `Dimensionality()` (the number of grain dimensions) and `Pick()`;
  alternate states declared in the app's overlay and `e()`/`p()` (no selections: the full
  set, nothing excluded); calculated dimensions (`=expr`, materialised as a table keyed by
  their `Aggr()` dimensions or referenced fields, with `Class()`/`Replace()`); `Min`/`Max`
  of duals on their number; `$()` of a name that evaluates to null (no value).
* `parity/models/<app>.overlay.json` supplies what the .qvw does not store: variables from
  missing include files (marked `reconstructed`), declared alternate states, and
  `parity_role`, the Section Access user the `.sql` model reduces the data for.
* Section Access: the model reduces rows the way QlikView does on open (only rows associated
  with the user's reduction values survive, `*` = every listed value), so the expected
  results are what that user sees. Chapter 15's stored row counts are the ADMIN-reduced ones.
* Still unsupported (`Above()`, `Rank()`, `Concat()`, bookmarks, ...) is listed as
  `unsupported` with the reason instead of being guessed; extend `qlik_expr.py`/`engine.py`
  when an app needs it.
* Result ids: `<object>#<n>@<grain>` (e.g. `CH01#1@Year+Month`). Output is gzip JSON,
  byte-reproducible (CI checks the committed Chapter 03 and 15 files).

## 2. DAX side (`harness.py queries` + `run_dax.ps1`)

* `queries` reads the app's TMDL: KPI → measure by `annotation ParityKey`; Qlik field →
  column by `sourceColumn`; a calculated dimension → the calculated column annotated with
  `ParityKey = <parity_key(dimension text)>`. The queries file carries the overlay's
  `parity_role`, and `run_dax.ps1` connects with `Roles=<role>`. Each result id becomes
  `EVALUATE ROW("value", [M])` or `EVALUATE SUMMARIZECOLUMNS('T'[c1], …, "value", [M])`.
  KPIs without an annotated measure are listed under `unmapped`.
* `run_dax.ps1` (Windows PowerShell 5.1+) runs the queries with ADOMD.NET against the model
  open in Power BI Desktop (port from `msmdsrv.port.txt` under
  `%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces`), or against any
  XMLA endpoint via `-Server`/`-Database` (Premium/Fabric workspace, or Analysis Services).
  It writes `{"app", "produced_by", "executed_at", "results": [{"id", "columns", "rows"}]}`.
* Procedure on the Windows machine: get the Parquet (convert under WSL or download the CI
  artifact) → open `apps/<Slug>/<Slug>.pbip` → set `DataRoot` → Refresh → run `queries`
  then `run_dax.ps1` → run `compare` → commit `reports/<app>.md` with the app's PR.
* Windows runs are done by a separate Power BI Desktop session after each app merges; the
  same script also runs unattended against a published model's XMLA endpoint.

## 3. Comparison (`harness.py compare`)

* Rows are matched on dimension values (numbers compared numerically, dates by ISO date,
  text exactly). Blank and 0 are equal (Qlik hides zero rows, DAX drops blank rows).
* Values: `rel_tol=1e-9`, `abs_tol=1e-6` by default (`--rel-tol`, `--abs-tol`).
* Exit code 0 only when every evaluated result passes; `fail` lists up to 5 example rows.

## 4. Known semantic gaps to keep in mind

* Baseline is "no selections"; apps that open with saved selections or default bookmarks
  should add those as an explicit state in their own test.
* Chart presentation limits (Top 10, suppress-zero, sorting) are not compared; the full
  result set is.
* Qlik's associative model is approximated by left joins from the largest table; measures
  over dimension-only fields with unassociated rows may need an app-specific model view.
