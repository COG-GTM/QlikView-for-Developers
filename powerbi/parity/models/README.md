# Per-app source models

The parity harness evaluates an app's expressions over one DuckDB view per Qlik table.
For apps whose load script only does plain loads (Chapters 03, 04, 06, 07) the views are
generated from the recovered script. Every other app's migration adds
`<manifest name>.sql` here: DuckDB SQL that creates a view named exactly like each Qlik
table in the manifest's `data_model`, reading Parquet via `read_parquet('{parquet}/<source path>.parquet')`
(`{parquet}` is replaced with `powerbi/data/parquet`; `{repo}` with the repository root, for
text sources read in place such as `{repo}/Chapter10/Production Planning - Legacy.txt`). It must reproduce the load script's
logic (WHERE Exists, joins, ApplyMap, CROSSTABLE, master calendar, ...) independently of the
Power Query being validated, so the comparison stays a real cross-check. The harness reports
each view's row count next to the inventory's (`model_tables` in the expected results); they
must match.
