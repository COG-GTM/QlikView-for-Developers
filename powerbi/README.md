# QlikView → Power BI migration foundation

Shared base for the per-app migrations of this repo's 18 QlikView apps (13 Airline Operations
chapter versions + 5 Chapter 09/10 demos).

| Path | What it is |
|---|---|
| `inventory/` | Per-app manifests (sources, model, keys, KPIs with variables expanded), recovered load scripts, gap list, known row-count exceptions |
| `tools/convert_sources.py` | Converts every QVD, the Access database, Excel workbooks and CSVs to Parquet under `data/parquet/` (generated, not committed) and writes `data/catalog.json` |
| `tools/verify_conversion.py` | Row-count verification against each source and against the inventory → `data/conversion_report.md` |
| `tools/scaffold_pbip.py` | Generates a PBIP (TMDL) skeleton for an app per [docs/CONVENTIONS.md](docs/CONVENTIONS.md) |
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
  computation on the original QVD. Chapters 04, 06 and 07 (40/41) also evaluate. The DAX
  side is generated and ready to run on Windows; it has not been run yet.
