# 10 - Evaluation Archive (dataset for the report-drafting layer)

How to structure the archive of past evaluations so the future local LLM
layer (docs/07 Phase 5: Items for Discussion drafts, Additional Information
tables, and the aerial/map inserts on the 1-target and 2-target results
sheets) can train and verify against it. Written before that layer exists so
the archive is right the first time; restructuring later means re-verifying
everything.

## Layout

One folder per evaluation, keyed by order ID and project ID, with the same
shape every time:

```
archive/
  manifest.jsonl                    one line per evaluation (see below)
  41000075552_02-20-61721/          {order id}_{project id}
    meta.yaml                       identity, classification, split
    inputs/
      assignment.msg                the assignment/assumptions email thread
      OriginalFiche.csv             TEAAS fiche export(s)
      DetailedFiche.xlsx            coordinate ledger (or the fiche workbook)
      Before_ID.txt  After_ID.txt   TEAAS Crash ID lists
      Before_Import.txt ...         milepost import files (sections)
      setup.yaml  results.yaml      transcribed set-up/results inputs
    deliverable/
      Section Evaluation Workbook - 02-20-61721 (SS-6002M).xlsx
    reports/                        optional: supplemental report PDF/DOCX
```

Rules:

1. **The delivered workbook is stored byte-exact, never resaved** (docs/06).
   The aerial/map inserts, text boxes, and shapes live inside the xlsx zip
   (`xl/drawings/*.xml` + `xl/media/*`); a resave destroys the very artifacts
   the insert-drafting model needs to learn from, and the anchor cells and
   box text are only extractable while the file is intact.
2. **No DMV-349 binders or crash-report scans in the archive.** Redacted or
   not, report imagery is working material for the review queue, not
   training data. The workbooks and fiches are the sanitized record. If a
   binder page index (`binder_index.json`) exists, it may be kept in
   `inputs/` since it holds only IDs and page numbers.
3. Inputs are the AS-RECEIVED files; the archive is also a regression
   fixture, so the tool can re-derive the deliverable from inputs and diff
   against the stored one (that is exactly how the 04-15-39049 and SS-6002M
   validations in the test suite work).

## meta.yaml and the manifest

`meta.yaml` carries the classification the split is stratified on; the
manifest line is the same record plus the path, so tools read one file:

```yaml
order_id: "41000075552"
project_id: "02-20-61721"
tip: "SS-6002M"
analysis_type: section          # section | intersection
targets: 1                      # 1 or 2 (which results sheet was used)
countermeasure_family: rumble-strips   # rumble-strips | flashers-vewf |
                                       # awsc | resurfacing | markings | ...
county: Greene
division: "2"
completed: 2021                 # project completion year
companions: ["41000078043"]     # evaluations sharing a corridor/thread
split: train                    # train | verify - assigned once, recorded
```

Most of this comes straight out of `safety-eval parse-email` on the archived
assignment email; filling meta.yaml should be a script, not typing.

## The 50/50 split

- **Split by evaluation, never by sheet or row.** All text and tables inside
  one workbook are correlated (the Items for Discussion quote the Additional
  Information counts); splitting rows across train/verify leaks the answer.
- **Keep companion evaluations in the same half.** SS-6002M and SS-6002AS
  share a corridor, an email thread, and discussion text; one in each half
  is leakage. That is what the `companions` field is for.
- **Stratify** the halves on `analysis_type`, `targets`, and
  `countermeasure_family` so both halves see intersections and sections,
  1-target and 2-target sheets, and each treatment family. With a small
  archive, stratification matters more than the exact 50/50 ratio.
- **Assign once, record forever.** Set `split` when an evaluation enters the
  archive (a deterministic rule like hashing the order ID keeps it stable as
  the archive grows) and never move an evaluation after prompts or examples
  have been tuned against it.
- **The verify half is measured, not mined.** Few-shot exemplars, prompt
  wording, and style references come from the train half only. If the
  archive turns out small (a few dozen evaluations), consider leaving the
  50/50 assignment in place but reporting verify-half metrics
  per-stratum, since single-digit stratum counts swing hard.

## What the tool extracts (already possible with the current code)

Supervision pairs come from readers that already exist, so archiving the
files in this layout is the only prerequisite:

| From | Reader | Gives |
|---|---|---|
| assignment.msg | `assignment_email.py` | scope, countermeasure, targets, periods, notes (model INPUT) |
| fiche + ID lists + imports | `fiche_parser.py`, `teaas.py` | crash-level features (INPUT) |
| deliverable workbook | `review_queue.load_review_sheet`, `ledger.read_ledger`, `qc.recount` | determinations, departure ledger, every tally (INPUT and consistency gate) |
| results sheets | openpyxl read of the manual cells (`results_sheet.py` addresses) | Items for Discussion text, Additional Information rows (TARGET) |
| drawings XML + media | zip read, never resave | insert anchors, text box contents, image placement (TARGET for the insert layer) |

Every generated draft is checked with `safety-eval qc` against the same
workbook before it is ever compared to the archived text: a draft that
quotes a wrong count fails before style is even considered, and the docs/05
gate (no em dashes, plain tone) applies to all generated text.

## Linking the archive to the tool

The tool takes an `archive_root` (config key or `--archive` flag, added with
the Phase 5 work) and reads `manifest.jsonl`; nothing scans directories or
guesses. Keep the archive OUT of this repository (size, and the workbooks
are client deliverables): a synced Drive folder mirrored to a local path is
fine, since the tool only ever reads the local mirror. The repository keeps
the manifest schema, the loaders, and the split logic; the data stays yours.
