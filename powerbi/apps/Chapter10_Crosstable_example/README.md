# Chapter10 / Crosstable example

Source: `Chapter10/Crosstable example.qvw` (one sheet, `Main`, no charts). Hand-written PBIP; the
load script uses `CROSSTABLE`, which `tools/scaffold_pbip.py` does not translate.

| QlikView | Power BI |
|---|---|
| `CrossTable(Month, Sales) LOAD Department, Jan, …, Dec FROM [Crosstable example.xls] (… Sheet1$)` | table `Sheet1$`: `fnReadParquet("Chapter10/Crosstable example/Sheet1.parquet")` → `Table.SelectColumns` → `Table.UnpivotOtherColumns({"Department"}, "Month", "Sales")` |
| `Month` text values in load order (Jan … Dec) | `Month` sorted by hidden `Month__num` (column position in the LOAD) |
| `$$SysTable 1-3` | not reproduced (QlikView system tables) |
| sheet `Main` (empty) | report page `Main` (empty) |

The QlikView format variables (`DD/MM/YY`, Spanish month/day names) are not used by any field
or object of this app, so they have no Power BI counterpart.

## Parity

No Qlik expressions exist, so `powerbi/parity/checks/Chapter10__Crosstable example.json` defines
data checks on the unpivoted table (every Department × Month cell, totals per Department and per
Month, row count per Department), mapped to the measures `Total Sales` and `Sales Count` by
`annotation ParityKey`. Source side: `powerbi/parity/models/Chapter10__Crosstable example.sql`
(DuckDB `UNPIVOT`), 48 rows = inventory; checked against an independent melt of the .xls in
`tests/test_parity_ch10_crosstable.py`. Expected results are committed in
`powerbi/parity/expected/`.

DAX run (Windows, Power BI Desktop), from the repo root:

```powershell
# Parquet: python powerbi/tools/convert_sources.py, or the CI "powerbi-parquet" artifact
# open powerbi/apps/Chapter10_Crosstable_example/Chapter10_Crosstable_example.pbip, set DataRoot, Refresh
python powerbi/parity/harness.py queries --app "Chapter10__Crosstable example" --pbip powerbi/apps/Chapter10_Crosstable_example
.\powerbi\parity\run_dax.ps1 -Queries "powerbi\parity\dax\Chapter10__Crosstable example.queries.json" `
                             -Out "powerbi\parity\dax\Chapter10__Crosstable example.results.json"
python powerbi/parity/harness.py compare --app "Chapter10__Crosstable example" --results "powerbi/parity/dax/Chapter10__Crosstable example.results.json"
```
