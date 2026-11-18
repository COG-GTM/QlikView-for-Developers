# Chapter 14 – Airline Operations

Power BI version of `Chapter14/Solution_Chapter 14_Airline Operations.qvw`. Its load script is Chapter 15's without
the hidden Section Access tab, and its 15 sheets and 92 chart expressions are the same, so it is generated from the
Chapter 15 base by `powerbi/tools/build_airline_base.py` (`--app "Chapter14__Solution_Chapter 14_Airline Operations"`;
do not edit the TMDL by hand; change the builder and rerun it).

| Qlik | Power BI |
| --- | --- |
| `[Main Data]` = Flight Data.qvd + Concatenate Employment Statistics.QVD (1,258,763 rows, nothing reduced) | `Main Data` (`Table.Combine`) |
| `[Master Calendar]` (AUTOGENERATE / WHILE / AutoNumber) | `Master Calendar`, one row per month, `PeriodID` / `QuarterID` |
| `WHERE Exists(key)` + `'Unknown'` members | `fnFactKeys` + `Table.SelectRows` / `List.Difference` |
| Metric picker inline table (`INLFED`) and `$($(=eMetric))` | `INLFED` + `Selected Metric` (SWITCH on SELECTEDVALUE) |
| No Section Access | no roles; every user sees all rows, including the Employment Statistics rows |
| Alternate states Group A / Group B | disconnected `Group A` / `Group B` period tables |
| Calculated dimensions (Aggr/Class buckets, deal status) | calculated columns with `annotation ParityKey` |
| 92 chart expressions (48 distinct) | 48 measures with `annotation ParityKey` |

Semantic differences are listed in `model.json` (`semantic_gaps`). Parity: source side in
`powerbi/parity/expected/` (`parity/models/Chapter14__Solution_Chapter 14_Airline Operations.sql`), DAX queries
(no role) in `powerbi/parity/dax/`.
