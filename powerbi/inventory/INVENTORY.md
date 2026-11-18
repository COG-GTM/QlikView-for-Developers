# QlikView-for-Developers → Power BI: app inventory & migration manifest

Source: COG-GTM/QlikView-for-Developers (18 .qvw, Chapters 03–15). Per-app manifests: `manifests/<Chapter>__<app>.json`; verbatim load scripts recovered from the QVW binaries: `scripts/*.qvs`; converter trial metrics: `q2p_trial_results.json`.

| App | Script lines / tabs | Sources (QVD/CSV/XLS/MDB/inline) | Tables (rows) | Keys | Vars | Sheets | Charts / exprs | Qlik-only exprs | Converter trial: tables (generic) / DAX (unconverted) / rels / pages |
|---|---|---|---|---|---|---|---|---|---|
| Chapter03/Solution_Chapter 3_Airline Operations.qvw | 127 / 5 | QVD 8 | 11 (1,258,055) | 7 | 0 | 2 | 2 / 8 | 0 | 10 (1) / 7 (0) / 8 / 2 |
| Chapter04/Solution_Chapter 4_Airline Operations.qvw | 155 / 5 | QVD 8, CSV 2, MS 2 | 15 (1,266,072) | 11 | 0 | 2 | 2 / 8 | 0 | 14 (1) / 7 (0) / 12 / 2 |
| Chapter06/Solution_Chapter 6_Airline Operations.qvw | 155 / 5 | QVD 8, CSV 2, MS 2 | 15 (1,266,072) | 11 | 0 | 2 | 2 / 8 | 0 | 14 (1) / 7 (0) / 12 / 2 |
| Chapter07/Solution_Chapter 7_Airline Operations.qvw | 155 / 5 | QVD 8, CSV 2, MS 2 | 15 (1,266,072) | 11 | 8 | 7 | 22 / 41 | 0 | 14 (1) / 26 (7) / 12 / 7 |
| Chapter08/Solution_Chapter 8_Airline Operations.qvw | 279 / 9 | CSV 5, Excel 2, QVD 6, MS 2 | 14 (1,266,061) | 10 | 10 | 7 | 23 / 42 | 0 | 15 (2) / 28 (7) / 2 / 7 |
| Chapter09/Solution_Chapter 9_Airline Operations.qvw | 382 / 11 | CSV 5, Excel 2, QVD 7, MS 2 | 15 (1,267,445) | 11 | 10 | 8 | 23 / 42 | 0 | 23 (8) / 28 (7) / 3 / 8 |
| Chapter09/Solution_Chapter 9_Concatenated tables.qvw | 349 / 10 | CSV 5, Excel 2, QVD 7, MS 2 | 14 (1,267,409) | 10 | 10 | 8 | 23 / 42 | 0 | 20 (7) / 28 (7) / 2 / 8 |
| Chapter09/Solution_Chapter 9_Link table.qvw | 416 / 11 | CSV 5, Excel 2, QVD 7, MS 2 | 16 (1,277,479) | 11 | 10 | 8 | 23 / 42 | 0 | 23 (8) / 28 (7) / 2 / 8 |
| Chapter09/Solution_Dimensionless Facts.qvw | 56 / 1 | — | 5 (771) | 1 | 0 | 1 | 1 / 1 | 0 | 4 (1) / 1 (0) / 1 / 1 |
| Chapter10/Crosstable example.qvw | 32 / 1 | Excel 1 | 4 (48) | 0 | 0 | 1 | 0 / 0 | 0 | 2 (0) / 0 (0) / 0 / 1 |
| Chapter10/Generic Load.qvw | 22 / 1 | Excel 1 | 8 (10) | 1 | 0 | 1 | 0 / 0 | 0 | 6 (0) / 0 (0) / 0 / 1 |
| Chapter10/Hierarchy example.qvw | 31 / 1 | Excel 1 | 4 (10) | 0 | 0 | 1 | 0 / 0 | 0 | 2 (1) / 0 (0) / 1 / 1 |
| Chapter10/Production Planning.qvw | 39 / 1 | Text 1 | 4 (50) | 0 | 0 | 1 | 0 / 0 | 0 | 3 (1) / 0 (0) / 2 / 1 |
| Chapter11/Solution_Chapter 11_Airline Operations.qvw | 390 / 12 | CSV 5, Excel 2, QVD 7, MS 2, INLINE 1 | 16 (1,267,448) | 11 | 14 | 10 | 38 / 66 | 7 | 24 (8) / 43 (18) / 3 / 10 |
| Chapter12/Solution_Chapter 12_Airline Operations.qvw | 395 / 12 | CSV 5, Excel 2, QVD 7, MS 2, INLINE 1 | 16 (1,268,477) | 11 | 14 | 13 | 47 / 85 | 22 | 24 (8) / 58 (24) / 4 / 13 |
| Chapter13/Solution_Chapter 13_Airline Operations.qvw | 379 / 12 | Excel 2, QVD 12, INLINE 1 | 16 (1,268,477) | 11 | 14 | 14 | 50 / 92 | 27 | 23 (8) / 63 (27) / 4 / 14 |
| Chapter14/Solution_Chapter 14_Airline Operations.qvw | 379 / 12 | Excel 2, QVD 12, INLINE 1 | 16 (1,268,477) | 11 | 14 | 15 | 50 / 92 | 27 | 23 (8) / 63 (27) / 4 / 15 |
| Chapter15/Solution_Chapter 15_Airline Operations.qvw | 403 / 13 | Excel 2, QVD 12, INLINE 3 | 17 (1,265,789) | 12 | 14 | 15 | 50 / 92 | 27 | 24 (8) / 63 (27) / 14 / 15 |

## Converter verdict (COG-GTM/Qlik-To-PowerBI)

- **Cannot read .qvw.** Extractor parses QVF (Qlik Sense) or exported JSON only; preflight lists .qvw but nothing parses it. All trials used intermediate JSON built from these manifests.
- **Runs on all 18, reports 100% fidelity, but output is not usable as-is:** `$(eLoadFactor)`-style variable expansion, `TOTAL <dims>`, `Dimensionality()`, Aggr and inter-record functions are copied verbatim into DAX (7–27 measures per Airline app).
- **Model:** all columns typed text; QVD partitions point at placeholder paths; generic `TableN` names for unlabeled loads; Ch08+ scripts lose the `%`-key relationships (2–4 rels vs 12 in Ch04–07) and add a wrong `Main Data[# Ramp-To-Ramp Time] → Calendar[Date]` relationship.
- **Use it for:** PBIP/TMDL scaffolding, page/visual skeletons, simple Sum/Count measures. Hand-write M (sources, mapping, calendar, crosstable/generic/hierarchy) and Qlik-semantic DAX; build relationships from `pbip_plan.relationships_from_keys`.

## Cannot be extracted or converted

1. **Include files** `config.qvs`, `tracerowcount.qvs`, `SetVariables.txt` (Ch08–15) are not in the repo or the QVW; `vFolderSourceData` resolved from repo layout (`Data Files/`, `QVD/Source`, `QVD/Transformed`). Every source path in the manifests resolves to a file in the repo.
2. **QVW layout/formatting** (object positions, colours, chart properties beyond type/dims/expressions, macros/actions on buttons, bookmarks content) is not decoded; sheets/objects inventoried by ID, type, caption, dims, expressions only.
3. **QVD files** are not readable by Power BI; must be pre-converted (Parquet/CSV) offline before PBIP refresh.
4. **Section Access (Ch15)**: Qlik USERID/PASSWORD credentials have no PBI equivalent → RLS role on `%FLIGHTTYPE` + OLS for `Carrier Name` (OMIT).
5. **Qlik-only expression semantics** (TOTAL qualifiers, Aggr, Dimensionality, Above/RangeSum, $-expanded parameterised variables like `eDeparturesPerformed_VarUnit(1000)`): manual DAX; expanded forms are in each manifest `kpis[].expanded`.
6. **QlikView-only objects** (multi box, current selections, statistics box, search object, input box/slider bound to variables, containers, bookmark objects, buttons with actions): approximate with slicers, field parameters, what-if parameters, bookmarks.
7. **Ch10 ETL demos** (CROSSTABLE, GENERIC LOAD, HIERARCHY): converter does not emit equivalent M; hand-write Table.UnpivotOtherColumns / pivot / PATH().
8. **Synthetic keys / link table (Ch09)**: model must be re-normalised (link table kept as bridge, synthetic keys replaced by composite keys).

## Per-app gaps

**Chapter03/Solution_Chapter 3_Airline Operations.qvw**
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- Synthetic/system tables in model: $$SysTable 8, $$SysTable 9, $$SysTable 10
- QlikView-only/approximate objects: search object×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter04/Solution_Chapter 4_Airline Operations.qvw**
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- Synthetic/system tables in model: $$SysTable 12, $$SysTable 13, $$SysTable 14
- QlikView-only/approximate objects: search object×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter06/Solution_Chapter 6_Airline Operations.qvw**
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- Synthetic/system tables in model: $$SysTable 12, $$SysTable 13, $$SysTable 14
- QlikView-only/approximate objects: search object×1, bookmark object×1, current selections×1, multi box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter07/Solution_Chapter 7_Airline Operations.qvw**
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- Synthetic/system tables in model: $$SysTable 12, $$SysTable 13, $$SysTable 14
- QlikView-only/approximate objects: text object×5, multi box×1, button×3, bookmark object×1, current selections×1, search object×1, container×1, statistics box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter08/Solution_Chapter 8_Airline Operations.qvw**
- Include files not in repo, cannot be extracted: config.qvs, tracerowcount.qvs (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- STORE INTO .qvd (QVD generator tab): ETL side effect, drop or move to dataflow
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- Synthetic/system tables in model: $$SysTable 11, $$SysTable 12, $$SysTable 13
- QlikView-only/approximate objects: text object×5, multi box×2, current selections×1, bookmark object×1, button×3, search object×1, container×1, statistics box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter09/Solution_Chapter 9_Airline Operations.qvw**
- Include files not in repo, cannot be extracted: config.qvs, tracerowcount.qvs (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- Master calendar via AUTOGENERATE/WHILE/Peek: replace with DAX CALENDAR or M List.Dates; converter mis-relates Calendar.Date
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- STORE INTO .qvd (QVD generator tab): ETL side effect, drop or move to dataflow
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- LEFT KEEP: emulate with M inner merge/filter
- Synthetic/system tables in model: $$SysTable 12, $$SysTable 13, $$SysTable 14
- QlikView-only/approximate objects: text object×5, multi box×2, search object×1, button×3, bookmark object×1, current selections×1, container×1, statistics box×1, table box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter09/Solution_Chapter 9_Concatenated tables.qvw**
- Include files not in repo, cannot be extracted: config.qvs, tracerowcount.qvs (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- STORE INTO .qvd (QVD generator tab): ETL side effect, drop or move to dataflow
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- LEFT KEEP: emulate with M inner merge/filter
- Synthetic/system tables in model: $$SysTable 11, $$SysTable 12, $$SysTable 13
- QlikView-only/approximate objects: text object×5, multi box×2, search object×1, button×3, bookmark object×1, current selections×1, container×1, statistics box×1, table box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter09/Solution_Chapter 9_Link table.qvw**
- Include files not in repo, cannot be extracted: config.qvs, tracerowcount.qvs (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- STORE INTO .qvd (QVD generator tab): ETL side effect, drop or move to dataflow
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- LEFT KEEP: emulate with M inner merge/filter
- Synthetic/system tables in model: $$SysTable 13, $$SysTable 14, $$SysTable 15
- QlikView-only/approximate objects: text object×5, multi box×2, search object×1, button×3, bookmark object×1, current selections×1, container×1, statistics box×1, table box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter09/Solution_Dimensionless Facts.qvw**
- Synthetic/system tables in model: $$SysTable 2, $$SysTable 3, $$SysTable 4

**Chapter10/Crosstable example.qvw**
- CROSSTABLE: converter does not emit Table.UnpivotOtherColumns; hand-write M
- Synthetic/system tables in model: $$SysTable 1, $$SysTable 2, $$SysTable 3

**Chapter10/Generic Load.qvw**
- GENERIC LOAD: converter emits per-attribute tables; hand-write M pivot to one table
- Synthetic/system tables in model: $$SysTable 5, $$SysTable 6, $$SysTable 7

**Chapter10/Hierarchy example.qvw**
- HIERARCHY(): no M equivalent emitted; use PATH()/PATHITEM() calculated columns
- Synthetic/system tables in model: $$SysTable 1, $$SysTable 2, $$SysTable 3
- QlikView-only/approximate objects: table box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter10/Production Planning.qvw**
- Synthetic/system tables in model: $$SysTable 1, $$SysTable 2, $$SysTable 3
- QlikView-only/approximate objects: table box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter11/Solution_Chapter 11_Airline Operations.qvw**
- Include files not in repo, cannot be extracted: config.qvs, tracerowcount.qvs (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- Master calendar via AUTOGENERATE/WHILE/Peek: replace with DAX CALENDAR or M List.Dates; converter mis-relates Calendar.Date
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- STORE INTO .qvd (QVD generator tab): ETL side effect, drop or move to dataflow
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- LEFT KEEP: emulate with M inner merge/filter
- 7/66 chart expressions use Qlik-only semantics (TOTAL, Aggr, Dimensionality, inter-record, $-expansion...) needing hand-written DAX
- Synthetic/system tables in model: $$SysTable 13, $$SysTable 14, $$SysTable 15
- QlikView-only/approximate objects: text object×6, bookmark object×1, multi box×2, current selections×1, button×3, search object×1, container×1, statistics box×1, table box×1, slider/calendar×1, input box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter12/Solution_Chapter 12_Airline Operations.qvw**
- Include files not in repo, cannot be extracted: config.qvs, tracerowcount.qvs, SetVariables.txt (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- MS Access .mdb via Jet OLEDB: needs Access.Database M connector (32/64-bit ACE driver) or pre-export to CSV
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- Master calendar via AUTOGENERATE/WHILE/Peek: replace with DAX CALENDAR or M List.Dates; converter mis-relates Calendar.Date
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- STORE INTO .qvd (QVD generator tab): ETL side effect, drop or move to dataflow
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- LEFT KEEP: emulate with M inner merge/filter
- 22/85 chart expressions use Qlik-only semantics (TOTAL, Aggr, Dimensionality, inter-record, $-expansion...) needing hand-written DAX
- Synthetic/system tables in model: $$SysTable 13, $$SysTable 14, $$SysTable 15
- QlikView-only/approximate objects: text object×6, multi box×2, search object×1, button×3, current selections×3, bookmark object×1, container×3, statistics box×1, table box×1, input box×1, slider/calendar×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter13/Solution_Chapter 13_Airline Operations.qvw**
- Include files not in repo, cannot be extracted: ..\0.Includes\config.qvs, ..\0.Includes\tracerowcount.qvs, ..\0.Includes\SetVariables.txt (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- Master calendar via AUTOGENERATE/WHILE/Peek: replace with DAX CALENDAR or M List.Dates; converter mis-relates Calendar.Date
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- 27/92 chart expressions use Qlik-only semantics (TOTAL, Aggr, Dimensionality, inter-record, $-expansion...) needing hand-written DAX
- Synthetic/system tables in model: $$SysTable 13, $$SysTable 14, $$SysTable 15
- QlikView-only/approximate objects: text object×6, multi box×2, search object×1, button×3, current selections×3, bookmark object×1, container×3, statistics box×1, table box×1, input box×1, slider/calendar×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter14/Solution_Chapter 14_Airline Operations.qvw**
- Include files not in repo, cannot be extracted: ..\0.Includes\config.qvs, ..\0.Includes\tracerowcount.qvs, ..\0.Includes\SetVariables.txt (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- Master calendar via AUTOGENERATE/WHILE/Peek: replace with DAX CALENDAR or M List.Dates; converter mis-relates Calendar.Date
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- 27/92 chart expressions use Qlik-only semantics (TOTAL, Aggr, Dimensionality, inter-record, $-expansion...) needing hand-written DAX
- Synthetic/system tables in model: $$SysTable 13, $$SysTable 14, $$SysTable 15
- QlikView-only/approximate objects: bookmark object×2, text object×6, button×3, search object×1, multi box×2, current selections×3, container×3, statistics box×1, table box×1, input box×1, slider/calendar×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)

**Chapter15/Solution_Chapter 15_Airline Operations.qvw**
- Include files not in repo, cannot be extracted: ..\0.Includes\config.qvs, ..\0.Includes\tracerowcount.qvs, ..\0.Includes\SetVariables.txt (defines vFolderSourceData etc.; source paths resolved by repo layout instead)
- Section Access (USERID/PASSWORD + %FLIGHTTYPE reduction, OMIT Carrier Name): no PBI equivalent for credentials; map to RLS role on Flight Type + OLS for Carrier Name; converter ignores it
- QVD sources: Power BI cannot read QVD natively; converter emits Qvd.Document/placeholder CSV paths. Pre-convert QVDs to Parquet/CSV
- MAPPING LOAD/ApplyMap: converter emits lookup table + no merge; hand-write M merge
- Master calendar via AUTOGENERATE/WHILE/Peek: replace with DAX CALENDAR or M List.Dates; converter mis-relates Calendar.Date
- COMMENT FIELDS/TABLES USING Comments.xls: map to TMDL descriptions manually
- IF $(vLoadMainData) conditional load: no M equivalent; always load
- 27/92 chart expressions use Qlik-only semantics (TOTAL, Aggr, Dimensionality, inter-record, $-expansion...) needing hand-written DAX
- Synthetic/system tables in model: $$SysTable 14, $$SysTable 15, $$SysTable 16
- QlikView-only/approximate objects: bookmark object×2, text object×6, button×3, current selections×3, multi box×2, search object×1, container×3, statistics box×1, table box×1, slider/calendar×1, input box×1 (map to slicers/bookmarks/cards/field parameters/buttons manually)
