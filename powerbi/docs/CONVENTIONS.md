# PBIP / TMDL and Power Query conventions

Every per-app migration follows these so the parity harness, CI and reviewers can treat
all 18 apps the same way. `tools/scaffold_pbip.py` emits exactly this layout.

## 1. Project layout

```
powerbi/apps/<Slug>/                     Slug = <Chapter>_<app name>, e.g. Chapter03_Airline_Operations
  <Slug>.pbip
  <Slug>.SemanticModel/
    definition.pbism
    definition/
      database.tmdl                      compatibilityLevel 1567
      model.tmdl                         culture en-US, ref table list
      expressions.tmdl                   DataRoot parameter + fnReadParquet function (shared, identical in every app)
      relationships.tmdl
      tables/<Qlik table name>.tmdl      one file per Qlik table, same name as in the manifest
  <Slug>.Report/
    definition.pbir                      byPath ../<Slug>.SemanticModel
    report.json
  scaffold.json                          what was generated, and KPIs that still need hand-written DAX
  .gitignore                             .pbi/localSettings.json, .pbi/cache.abf
```

Text formats only (PBIP + TMDL); never commit `.pbix`. Lineage tags are deterministic
(uuid5 of app/table/object) so regenerating does not create diffs.

## 2. Data access (Power Query)

* Power BI reads only Parquet produced by `tools/convert_sources.py`, never the QVD/MDB.
  The Parquet path mirrors the source path:
  `Data Files/QVDs/Flight Data.qvd` → `Data Files/QVDs/Flight Data.parquet`,
  `Data Files/MDBs/Dimension Tables.mdb` table `Airlines` → `Data Files/MDBs/Dimension Tables/Airlines.parquet`,
  `Data Files/Excel/Comments.xls` sheet `Tables` → `Data Files/Excel/Comments/Tables.parquet`.
  `data/catalog.json` lists every file with its row count and column types.
* Text sources Power BI reads natively and that need QlikView-style parsing
  (`Chapter10/Production Planning - Legacy.txt`) are read directly with `Csv.Document`
  from the checkout; such apps add a `SourceRoot` text parameter (the repository root,
  ending with `\`) next to the shared queries.
* Every app has the same two shared queries:
  * `DataRoot` — text parameter, the folder holding the Parquet (ends with `\`).
  * `fnReadParquet(relativePath)` — `Parquet.Document(File.Contents(DataRoot & path))`, path with `/`.
* Each table partition is `Source = fnReadParquet("<path>")` → `Table.SelectColumns` (the
  fields the Qlik LOAD lists, in order) → `Table.RenameColumns` (Qlik `AS` aliases) →
  transformation steps → `Table.TransformColumnTypes` (explicit types, always last).
* Translate the load script's transformations into named M steps that mirror it:

| QlikView | Power Query |
|---|---|
| `LOAD ... FROM x.qvd (qvd)` | `fnReadParquet("…/x.parquet")` + `Table.SelectColumns` |
| `WHERE Exists([%Key])` | `Table.Join`/`Table.NestedJoin` inner with the distinct keys of the referencing table |
| `LEFT JOIN (T)` / `LEFT KEEP (T)` | `Table.NestedJoin` + `Table.ExpandTableColumn` / inner-join filter, keep T's rows |
| `CONCATENATE (T)` | `Table.Combine` (missing columns become null) |
| `MAPPING LOAD` + `ApplyMap()` | small lookup query + `Table.NestedJoin` LeftOuter with default value |
| `CROSSTABLE(attr, data, n)` | `Table.UnpivotOtherColumns(first n columns, "attr", "data")` |
| `GENERIC LOAD` | `Table.Pivot` on the attribute column (one table, not one per attribute) |
| `HIERARCHY(...)` | parent/child table + DAX `PATH`/`PATHITEM` columns |
| master calendar (`AUTOGENERATE`, `IterNo()`) | `List.Dates` calendar table marked as date table |
| `AutoNumber()` | keep the natural key (Power BI does not need surrogate integers) |

## 3. Types (QlikView duals)

QVD values are duals (number + text). The converter writes:

* numbers when every value's text is just its number formatted → `int64`/`double`;
  leading zeros are dropped as in Qlik's numeric interpretation (`'08'` → 8);
* `date` when the texts are the dates of the numbers (Qlik day numbers since 1899-12-30);
* text when the texts are labels (`Month` = `'Jan'` … with 1 … 12): the text column plus
  `<field>__num` with the number. In TMDL the label column gets `sortByColumn: <field>__num`
  and the `__num` column is hidden;
* text when any value is non-numeric (mixed fields such as carrier codes stay text).

Access/Excel/CSV columns follow the same rules; Access types come from the .mdb schema.

## 4. Model

* One TMDL table per Qlik table, same table and column names as Qlik (including `%`, `#`,
  spaces and apostrophes) so manifests, harness and DAX refer to the same names.
* `%` key fields are hidden; relationships come from `manifest.pbip_plan.relationships_from_keys`,
  many (fact) → one (dimension), single direction. Synthetic keys (`$$SysTable`) are not
  reproduced: resolve them with a link table or composite key in the app's migration.
* Measures: one per distinct KPI expression, on the fact table, named after the first chart
  label that uses it; every measure that implements a Qlik expression carries
  `annotation ParityKey = <harness.parity_key(expression)>`, plus `QlikExpression` and
  `QlikObjects` for reviewers. The ParityKey is how the harness finds the measure.
* Format strings: Qlik `ThousandSep`/`DecimalSep`/`MoneyFormat` → `#,0`, `#,0.00`,
  `$#,0.00;-$#,0.00`; ratios `0.00%`; `DateFormat YYYY-MM-DD` → `yyyy-mm-dd`.
* Section access (Ch15) → one RLS role per Qlik USERID filtering the reduction field's table
  (`INLFED[%FLIGHTTYPE]`, `*` = every value listed in Section Access); `OMIT` → OLS
  (`columnPermission … = none`). Passwords are never migrated; role members are assigned in
  the Power BI service.
* Apps whose script transforms tables are generated by their own builder instead of
  `scaffold_pbip.py` (Ch15: `tools/build_airline_base.py`, the base for the Airline chapters):
  calculated dimensions become calculated columns with `annotation ParityKey`, alternate
  states become disconnected tables, and each app lists its semantic gaps in `model.json`.
