# QlikView → Power BI migration foundation

Shared base for the per-app migrations of this repo's 18 QlikView apps (13 Airline Operations
chapter versions + 5 Chapter 09/10 demos).

| Path | What it is |
|---|---|
| `inventory/` | Per-app manifests (sources, model, keys, KPIs with variables expanded), recovered load scripts, gap list, known row-count exceptions |
| `tools/convert_sources.py` | Converts every QVD, the Access database, Excel workbooks and CSVs to Parquet under `data/parquet/` (generated, not committed) and writes `data/catalog.json` |
| `tools/verify_conversion.py` | Row-count verification against each source and against the inventory → `data/conversion_report.md` |
| `tools/build_ch03_airline.py` | Builds the full Chapter 3 Airline Operations PBIP (model + Main/Dashboard pages) from the Ch15 base |
| `tools/scaffold_pbip.py` | Generates a PBIP (TMDL) skeleton for an app per [docs/CONVENTIONS.md](docs/CONVENTIONS.md) |
| `tools/build_report.py` | Writes report pages (slicers, charts with Top N filters) for a scaffolded plain-load app from its sheet layout and the PBIP's `ParityKey` measures |
| `apps/` | One PBIP folder per migrated app (Chapter 03 scaffold is the reference layout) |
| `parity/` | Parity harness: recomputes every KPI/chart expression from source, generates DAX queries, compares — see [docs/PARITY.md](docs/PARITY.md) |
| `tests/` | `python -m pytest` (run from `powerbi/`) |

## Quick start (Linux, macOS or WSL)

```bash
sudo apt-get install -y mdbtools            # Access (.mdb) export
pip install -r powerbi/requirements.txt
python powerbi/tools/convert_sources.py     # ~30 s, ~220 MB of Parquet
python powerbi/tools/verify_conversion.py   # exits 1 on any unexplained row-count mismatch
python powerbi/parity/harness.py source --all
(cd powerbi && python -m pytest -q)
```

On a Windows machine without WSL, download the `powerbi-parquet` artifact of the
"Power BI foundation" workflow run instead of converting locally, and unpack it so that
`powerbi/data/parquet/` exists; point each PBIP's `DataRoot` parameter at that folder.

## Status of the verification

* Integrity: all 76 Parquet tables have exactly their source's row count (QVD header
  `NoOfRecords`, Access/Excel/CSV data rows) and catalog sha256s match the source files.
* Inventory: 44 plain-load tables match the inventory exactly; 8 differ for a documented
  reason (`inventory/row_count_exceptions.json`: the .qvw files of Ch04–08 were reloaded
  from an older copy of `Dimension Tables.mdb`); 115 tables are built by script
  transformations and are checked by each app's source model (`parity/models/`).
* Parity: all 8 Chapter 03 KPI expressions (2 charts × 4) are recomputed from source for
  the grand total and every chart grain, and match an independent pyqvd + pandas
  computation on the original QVD. Chapters 04, 06 and 07 (40/41) also evaluate.
  Chapter 10 Production Planning: the source model reproduces the report-file cleanup and
  its 50 rows equal the rows stored in the .qvw (test decodes them). The DAX
  side is generated and ready to run on Windows; it has not been run yet.
* Chapter 07 (`apps/Chapter07_Airline_Operations`, built from the Chapter 15 base by
  `tools/build_ch07_airline.py`): 41/41 KPIs evaluate, 12 base measures + `Deal Status`, 83 DAX
  queries generated, 7 report pages (one per sheet).
* Chapter 15 (Airline Operations base model, `apps/Chapter15_Airline_Operations`): its 14
  source-model tables match the inventory (after reproducing Section Access reduction for
  ADMIN), all 92 KPI expressions evaluate, and 182 DAX queries (role ADMIN) are generated.
* Chapter 11 (Airline Operations, `apps/Chapter11_Airline_Operations`, built by
  `tools/build_airline_ch11.py` from the Chapter 15 base): its 13 source-model tables match the
  inventory, all 66 KPI expressions evaluate, and 133 DAX queries are generated (no Section Access).
* Chapter 09 Concatenated tables (`apps/Chapter09_Concatenated_tables`, derived from the
  Chapter 15 base): its 11 source-model tables match the inventory, all 42 KPI expressions
  evaluate, and 85 DAX queries are generated.
* Chapter 04 (`apps/Chapter04_Airline_Operations`): scaffolded plain-load model (12 tables,
  11 relationships, 4 measures) with Main and Dashboard report pages (all 20 list boxes
  as slicers, from captions in the .qvw, plus a synced Dashboard dropdown for each Main-only field so
  Main selections filter the charts; the search object SO01 has no equivalent); all 8 KPI expressions
  match pyqvd + pandas on the original QVD, and 20 DAX queries plus 11 relationship checks
  are generated. Origin/Destination Airports differ from the inventory only by the
  documented superset exceptions.
* Chapter 13 (Airline Operations, `apps/Chapter13_Airline_Operations`, built from the Chapter 15
  base by `tools/build_airline_base.py`): no Section Access, so its 13 source-model tables match
  the unreduced inventory (Main Data keeps the Employment Statistics rows), all 92 KPI expressions
  evaluate, 182 DAX queries are generated, and the report has one page per QlikView sheet (14)
  with a visual per chart and slicers for the list boxes (4 boxes without a model field are listed
  in `model.json`).
