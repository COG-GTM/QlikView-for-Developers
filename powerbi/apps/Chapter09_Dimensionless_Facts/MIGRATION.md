# Chapter09 / Solution_Dimensionless Facts.qvw → Power BI

| QlikView | Power BI |
|---|---|
| `Aircrafts` ← `Chapter09/Aircrafts.csv` (`AC_TYPEID as [%Aircraft Type ID]`) | table `Aircrafts`, partition reads `Chapter09/Aircrafts.parquet` |
| `Flights` ← `Chapter09/Flights.csv` | table `Flights`, partition reads `Chapter09/Flights.parquet` |
| `Temp_Aircraft_Type_ID` + `CONCATENATE (Aircrafts) LOAD DISTINCT ... RESIDENT Flights WHERE NOT Exists(...)`, `DROP TABLE Temp_...` | `Aircrafts` steps `FlightKeys` → `MissingKeys` (left-anti join) → `Unknown` rows → `Table.Combine`; no temp table |
| `%Aircraft Type ID` association | relationship `Flights` (many) → `Aircrafts` (one), key hidden |
| CH01 "Flights by Group": `Sum ([# Departures Performed]) /1000` by `Aircraft Group` | measure `Flights by Group` = `DIVIDE(SUM(Flights[# Departures Performed]), 1000)`, clustered column chart |
| LB01 list box `Aircraft Name` | slicer on `Aircrafts[Aircraft Name]` |

Notes
* The synthetic `$$SysTable` entries in the inventory are QlikView system tables, not a synthetic key;
  the model has a single key, so nothing needs a link table.
* The 82 added rows are named `'Unknown: ' & [%Aircraft Type ID]`, and QlikView uses the key's text as read
  from `Flights.csv`, zero-padded to 3 digits (`Unknown: 007`). The Parquet stores the number, so the
  Power Query rebuilds the text with `Text.PadStart(..., 3, "0")`; the test checks every key of the CSV and
  the 82 names stored in the .qvw.
* Every fact row now has an aircraft, so the chart has no blank/`-` bar: `Unknown` carries 499.028 of 3,713.82.

Parity: `parity/expected/Chapter09__Solution_Dimensionless Facts.json.gz` (source side, 2 results);
DAX queries ready in `parity/dax/Chapter09__Solution_Dimensionless Facts.queries.json` for `run_dax.ps1`.
