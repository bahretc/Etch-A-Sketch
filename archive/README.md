# Evaluation archive metadata (docs/10)

Derived metadata for the 60-evaluation Drive archive; built by
`safety-eval archive-manifest`. The evaluation FILES (workbooks, fiches,
emails, reports) stay in Google Drive - manifest lines and inventories carry
their Drive file IDs so tools fetch on demand.

- `manifest.jsonl` - one record per work order: classification
  (analysis type, countermeasure family, county/division, completion year),
  companion cluster, the recorded train/verify split, flags, and key-file
  Drive IDs.
- `meta/<WO>.yaml` - the same records, one file per evaluation.
- `inventory/<WO>.json` - full recursive file listing of each Drive folder
  (path, Drive ID, size) captured 2026-07-24.

The split is assigned once and recorded here (docs/10): rerunning the
builder must not move evaluations between halves; treat manifest edits to
`split` as a deliberate, reviewed act.
