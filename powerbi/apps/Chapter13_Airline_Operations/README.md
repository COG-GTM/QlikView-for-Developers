# Chapter 13 – Airline Operations

Power BI version of `Chapter13/Solution_Chapter 13_Airline Operations.qvw`. Generated from the Chapter 15 base
by `powerbi/tools/build_airline_base.py --app Chapter13` (do not edit the TMDL or report by hand; change the
builder and rerun it).

Chapter 13 has the same load script as Chapter 15 without the hidden Section Access script, so compared with the
base:

| Qlik (Chapter 13) | Power BI |
| --- | --- |
| No Section Access | no RLS/OLS roles; nothing reduced (Main Data 1,258,763 rows incl. Employment Statistics, Airlines 337) |
| Metric picker is the only inline table (`INLFED`) | `INLFED` + `Selected Metric` (SWITCH on `SELECTEDVALUE(INLFED[eMetric])`) |
| 14 sheets, 50 charts (92 expressions, 48 distinct) | one report page per sheet, a visual per chart; 48 measures with `annotation ParityKey` |

Everything else (Main Data, Master Calendar, `WHERE Exists` + `'Unknown'` members, Group A / Group B, calculated
dimensions) is the Chapter 15 base. Semantic differences are listed in `model.json` (`semantic_gaps`). Parity:
source side in `powerbi/parity/expected/` (from `parity/models/<app>.sql`), DAX queries in `powerbi/parity/dax/`
(no role).
