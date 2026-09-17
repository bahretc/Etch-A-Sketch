# safety-eval — NCDOT before/after safety-evaluation automation

Automates an NCDOT HSIP **before/after safety evaluation** end-to-end:

```
assignment (initial study)  ─┐
                             ├─►  parse  ─►  classify  ─►  before/after  ─►  workbook + report
TEAAS "fiche" report  ──────┘   (+OCR for PDFs)   (in-study, period,
                                                   target crash types)
```

Given the **original fiche** (the TEAAS crash listing) and the **initial study**
(the assignment / assumptions), it OCRs/parses the crash table, filters crashes
to the study section and period, classifies target crash types, computes the
before/after effectiveness, and writes a completed evaluation **workbook** and a
**Markdown report**.

> **Status:** working core engine (Phase 1 partial). Domain rules now come from
> the HSIP context pack in [`CLAUDE.md`](CLAUDE.md) + [`docs/`](docs/) (the
> ground truth exported from prior evaluation sessions): NCDOT T-code table
> (docs/09), EPDO 76.8/8.4/1.0 (docs/04), frontal-impact/lane-departure target
> sets (docs/03, docs/08), no-em-dash report style (docs/05). Items still marked
> `[VERIFY]` in the config are the ones the pack does not define (see below).
> `docs/07` lays out the full multi-phase app; see *Relationship to the full
> spec*.

## Install

Never installed a Python tool before? Read `INSTALL.md` and double click one
file. It builds the environment, installs everything, fetches Chromium and
prints what is available. Windows and Mac both covered.

Everything else:

```bash
pip install -e .            # core (PyYAML + openpyxl)
pip install -e '.[pdf]'     # + PDF text extraction (pdfplumber / pypdf)
pip install -e '.[ocr]'     # + OCR for scanned fiche (pytesseract / pdf2image)
pip install -e '.[ui]'      # + the Streamlit app (streamlit run streamlit_app.py)
pip install -e '.[maps]'    # + package map PDFs; then: playwright install chromium
pip install -e '.[llm]'     # + AI assist, QA sweep, chat, drafting (needs ANTHROPIC_API_KEY)
safety-eval doctor --network   # what is installed and which public services answer
```

Or all of them at once, which is what the double click installer runs:

```bash
pip install -e '.[pdf,ocr,ui,deliverables,maps,llm]'
```

**Beta (0.2.0b5).** The fatal slip and HSIP fiche workflows run start to
finish on the CLI and in the app; `docs/13-beta-walkthrough.md` is the
two-page tour and lists the known limits. New in this version: the app runs
in its own desktop window with no terminal and no browser chrome
(`python -m safety_eval.desktop`), the sidebar puts the study first and the
navigation follows the workflow with nothing folded away, the Overview shows
what the open study already has, fatal and HSIP studies get a Maps and
Checks page, and the Field Investigation builder is parked behind
`SAFETY_EVAL_FIELD_INVESTIGATION=1`. Added in 0.2.0b4: the double click
installer for Windows and Mac (`INSTALL.md`), one current model across the
assist calls. Added in 0.2.0b2: the route
centerline and its curves and crests (`route-features`), the location check
of coded mileposts against report coordinates and geocoded addresses
(`locate-check`), the Location / Area / AADT package maps from a study YAML
(`package-maps`), the strip CalculatedAADT workbook (`calc-aadt`), and two
review rules from live work (off-fiche initial study crashes get a fiche
row; off-LRS rows can be screened NIS).

## Use

```bash
# full pipeline -> output/<name>_Evaluation.xlsx + <name>_Report.md
safety-eval run \
  --fiche examples/example_fiche.csv \
  --assignment examples/example_assignment.yaml \
  --outdir output

# populate the REAL NCDOT Evaluation Workbook template (template-preserving)
safety-eval fill-template \
  --template "templates/Intersection Evaluation Workbook - 2023-12-04.xlsx" \
  --before examples/SS-6002AD/41000078044BEFORE1_CrashID.txt \
  --after  examples/SS-6002AD/41000078044AFTER1_CrashID.txt \
  --target1 "Frontal Impact" \
  --output out.xlsx --recalc

# Section workbook: ID lists + original fiche (C/F/L enrichment) + mileposts
# + Evaluation Set-up (dates, representative years, AADT tables)
safety-eval fill-template \
  --template "templates/Section Evaluation Workbook - 2023-12-04.xlsx" \
  --before examples/04-15-39049/Before_ID.txt \
  --after  examples/04-15-39049/After_ID.txt \
  --before-mp examples/04-15-39049/Before_Import.txt \
  --after-mp  examples/04-15-39049/After_Import.txt \
  --fiche examples/04-15-39049/OriginalFiche.csv \
  --setup examples/04-15-39049/setup.yaml \
  --results examples/04-15-39049/results.yaml \
  --binned --bin-routes "SR 1003" --bin-mp-range 17.691:17.811 \
  --output out.xlsx --recalc

# pull yearly station AADTs from the NCDOT AADT map's feature service
safety-eval aadt --where "COUNTY='JOHNSTON'" --point -78.35,35.65 --radius 500

# redact PII from an uploaded crash report before review (ZIPs and crash IDs kept)
safety-eval redact --input dmv349_binder.pdf --output dmv349_redacted.pdf

# OCR-index a scanned DMV-349 binder (crash-ID header box, psm 6, top-right
# crop), then pull any crash's pages as a REDACTED image-only PDF
safety-eval binder-index --binder binder_part1.pdf binder_part2.pdf \
  --output binder_index.json
safety-eval binder-get --index binder_index.json --crash-id 105904161 \
  --output 105904161_redacted.pdf

# parse the assignment/assumptions email thread directly (.msg/.eml):
# one draft assumptions + assignment YAML pair per 'Assignment #N' block
safety-eval parse-email --input "Assignment 22 & 23.msg" --outdir parsed

# lane departure CL/R ledger: change one crash's call on EVERY sheet at once
safety-eval ledger --workbook eval.xlsx --treatment dual          # report
safety-eval ledger --workbook eval.xlsx --crash-id 105274289 \
  --exclude --comment "side-street run-through; non-target" --output out.xlsx

# recount before delivering (docs/03 QC habits); exit 2 on any mismatch
safety-eval qc --workbook eval.xlsx --treatment dual

# TEAAS milepost import files from the reviewed Before/After sheets;
# exit 1 if any in-study crash had to be HELD for want of a milepost
safety-eval teaas-import --workbook eval.xlsx --outdir out/

# the app in its own desktop window (or: streamlit run streamlit_app.py)
pip install -e '.[ui]' && python -m safety_eval.desktop

safety-eval parse  --fiche path/to/fiche.pdf     # preview parsed crashes
safety-eval doctor                               # which OCR/PDF backends are available
```

The **assignment** is a small YAML you transcribe once from the assignment /
assumptions email — it is the auditable record of study scope. See
[`examples/example_assignment.yaml`](examples/example_assignment.yaml).

## Finishing a deliverable (AADT, map block, print, bind, QA, assistant)

The steps that used to be done by hand on a completed package are commands
and app pages now. Each one keeps the docs/06 rules: XML level edits on a
copy, every other zip member byte for byte, drawings verified.

```bash
# Leg AADT table with the black/red convention. Legs take a station id
# (NCDOT 2025 AADT Stations layer), a manual year:aadt list, or =legN to
# assume a leg equal to another. Minor legs round to the nearest hundred,
# 2020 is never representative, the representative year is the last year in
# each period with a published value on any leg.
safety-eval aadt-table --leg1 0900000008 --leg2 0900000575 --leg4 0900000621 --leg3 =leg4 \
  --before-end 2020 --workbook Evaluation.xlsx

# Map/Satellite Views block in the team format (aerial, inset in the corner
# no leg crosses, a box per leg, north arrow, credit), embedded at H41:K56.
safety-eval map-block --aerial nearmap.png --inset location_map.png --spec legs.json \
  --output block.png --workbook Evaluation.xlsx

# Results page printed with LibreOffice at the Excel print's geometry
# (needs Carlito + Liberation Serif), then bound into the two deliverables.
safety-eval print-results --workbook Evaluation.xlsx --output page1.pdf \
  --disclaimer disclaimer.pdf --appendix BEFORE.pdf --appendix AFTER.pdf \
  --complete "Complete Evaluation.pdf" --web Web.pdf

# Deterministic QA: workbook structure and drawings gate, results text style
# (no em or en dashes), fiche Type vs T code, AADT colours, PDF assembly.
safety-eval qa --workbook Evaluation.xlsx --reference original.xlsx \
  --complete "Complete Evaluation.pdf" --web Web.pdf --diff

# Assistant (drafts and checks only; needs ANTHROPIC_API_KEY)
safety-eval chat "Run the QA checks on Evaluation.xlsx and summarize"

# Multi-agent QA sweep: six reviewers (workbook, fiche chain, calculations,
# report text, TEAAS cross-check, PDF assembly) and three refuters over the
# whole package folder, findings CONFIRMED / PARTIAL / REFUTED by verifier
# agreement. Claude Opus 5, structured output, cached package context.
safety-eval qa-sweep --package "WO-41000076160 10-18-223 (TIP #W-5710AM)" --output "Notes/QA sweep.md"

# Crash report redaction with independent verification: the output is OCRed
# and searched for the original's names, DOB, phone, licence numbers and
# street addresses (masked in the report; exit 2 on any hit).
safety-eval redact --input 600504376.tif --output 600504376_REDACTED.pdf --verify

# Strip collision diagram (fan-out callouts, leaders to the true milepost)
safety-eval collision-diagram --crashes crashes.csv --title "Collision Diagram - 41000079307" \
  --mp-start 1.31 --mp-end 1.80 --feature "1.45:SR 1321" --output diagram

# One pass to ship: redact + verify crash reports, embed the map block, print,
# bind, QA checks, QA log in Notes, zip with 'TIP #' dropped from names.
safety-eval finish --package "WO-41000076160 10-18-223 (TIP #W-5710AM)" --map-block block.png
```

The Streamlit app (`streamlit run streamlit_app.py`) groups its pages in
the sidebar in workflow order. For an Evaluation, the Deliverables group has
a page for each step above (AADT and Set-up, Map Block with an Esri World
Imagery fallback, Strip Collision Diagram, Print and Assemble, QA Checks with
the multi-agent sweep, Finish Package, which loads the WO zip) and a chat
assistant with tools over the loaded package; Redact Crash Reports and the
Review Queue serve every study type. `safety-eval doctor`
reports whether LibreOffice, the fonts, pikepdf, Streamlit and the Anthropic
SDK are present. Install extras with `pip install -e '.[deliverables,ui,llm]'`
and, on Debian/Ubuntu, `apt install fonts-crosextra-carlito fonts-liberation
libreoffice-calc poppler-utils`.

## Inputs

| Input | Formats | Notes |
|---|---|---|
| Fiche | `.csv`, TEAAS `.txt`, `.pdf` | PDF path runs the pluggable OCR front-end (`safety_eval/ocr.py`) |
| Assignment | `.yaml` | route, section MPs, dates, countermeasure, target crash types, AADTs |
| Config (optional) | `.yaml` | overrides any value in `config/ncdot_defaults.yaml` |

## Outputs

- **`*_Evaluation.xlsx`** — Summary, Before-After, By Target Type, Crash List,
  Assumptions sheets.
- **`*_Report.md`** — narrative before/after report with severity and
  target-type tables.

## How it works

| Stage | Module | What it does |
|---|---|---|
| Parse | `fiche_parser.py` | CSV + TEAAS-text/PDF → `Crash` records |
| TEAAS exports and imports | `teaas.py` | 5-column Crash ID List parser (numeric SVRTY → KABCO); milepost import reader and writer (`crash_id\|<tab>milepost`, CRLF), byte-verified by rebuilding the real `Before_Import.txt` / `After_Import.txt` of 04-15-39049 from that evaluation's workbook. In-study crashes with no milepost go to a HELD list rather than into an import; a crash ID carrying two different mileposts is refused |
| OCR | `ocr.py` | Lazy, pluggable PDF→text (pdfplumber → pypdf → tesseract) |
| Classify | `classify.py` | In-study (by milepost), study period, target crash types |
| Periods | `periods.py` | Date Range Calculator (before / construction / after) |
| AADT | `aadt.py` | Length-weighted corridor AADT by sub-section |
| Analysis | `analysis.py` | Counts by severity/target, crash rates, effectiveness |
| Report | `report.py` | Standalone summary workbook + Markdown |
| Template writer | `xlsx_patch.py` | docs/06-compliant XML patching, LibreOffice recalc (cache transplant), byte-identical integrity gate |
| Workbook populate | `eval_workbook.py` | Fills Before/After columns A-M of the real template; formulas untouched |
| Set-up sheet | `setup_sheet.py` | Date Range Calculator + AADT tables (label-detected cells, both variants), representative years, sample-data clearing |
| Results sheet | `results_sheet.py` | 1-page results manual cells: identity block, countermeasure/criteria/target text, Additional Information rows (n/a fill), Items for Discussion; enforces the docs/05 no-em-dash rule |
| Binned Crashes | `binned_sheet.py` | Bins every fiche crash under exactly one period banner (prior/before/construction/after/NIS) with bulk row writing; header created to match the completed-workbook layout |
| AADT lookup | `aadt_arcgis.py` | Queries the feature services behind the NCDOT AADT web map (stations + segments); schema-drift tolerant; CSV export |
| PII redaction | `redact.py` | Blacks out names, addresses, DOB, phone, DL numbers, VINs and plates on uploaded crash reports; keeps ZIPs and crash IDs; image-only output so no text layer can leak |
| Binder index | `binder.py` | OCR page index of scanned DMV-349 binders (crash-ID header box, tesseract psm 6, top-right crop); continuation pages group under the preceding report; per-crash retrieval is redacted before anyone sees it |
| Email parsing | `assignment_email.py` | Assignment/assumptions email thread (.msg via olefile property streams, .eml via stdlib) to draft assumptions + assignment YAMLs; newest copy of each Assignment #N block wins; notes/questions verbatim |
| CL/R ledger | `ledger.py` | Lane departure ledger (docs/03): Centerline/Right calls with the first-harmful-event rule, per-treatment correctability (dual = either line), standing exemptions, side-street run-through exclusion; any change propagates to every sheet the value appears on (Filtered Fiche, Before/After, Binned Crashes) in one template-preserving patch |
| QC recounts | `qc.py` | Pre-delivery recount: Filtered Fiche vs Binned Crashes vs Before/After crash-ID reconciliation, ledger cross-sheet consistency, and "N crashes" text quotes checked against computed tallies; mismatches block export |
| Review queue | `review_queue.py` | Fiche review workflow (docs/07 Phase 3): header-detected Filtered Fiche read-back, pre-screen ordering by DetailedFiche coordinates (supplied with the Original Fiche; never taken from the reports, which is what the review checks) or milepost distance, docs/03 status + comment validation (RE rejected for intersections, RE requires New MP), animal-crash skip, JSONL audit trail, per-cell template-preserving write-back |

### Crash-report PII redaction

Uploaded DMV-349 scans are redacted before review: OCR (tesseract) locates PII
by form labels (Name/Address/DOB/Phone/License/VIN/Plate captions, including
common OCR garblings and values printed left of a surviving caption),
street-address patterns, VIN patterns, and city/state/ZIP continuation lines.
Words are clustered into visual rows by position, so sparse OCR that splits a
caption from its boxed value cannot separate a name from its label. ZIP codes
and 9-digit crash IDs are always kept. The output PDF is rasterized with the boxes burned in, so
there is no hidden text layer to extract. The audit report lists counts and
trigger reasons only, never the PII itself. OCR can miss handwriting or poor
scans; the engineer does a final visual pass (engineer-in-the-loop, docs/07).
Requires `tesseract-ocr` and `poppler-utils`.

### Template-preserving writes (docs/06)

`fill-template` never resaves the template with openpyxl. It rewrites only the
targeted worksheet XML inside a copy of the zip, copies every other member
byte-for-byte, and verifies drawings/media are byte-identical afterward. The
`--recalc` pass is a LibreOffice headless round-trip with recalc-on-load forced
(`OOXMLRecalcMode=0`); only the recalculated formula caches are transplanted
back, so drawings stay untouched. Validated on the SS-6002AD example: the
populated template's own KABCO block computes Severity Index 4.70, matching the
TEAAS Intersection Analysis Report for that study.

**Effectiveness methodology** (naive before/after, adjusted for time & traffic):

```
expected_after   = before × (after_years / before_years) × (aadt_after / aadt_before)
reduction_%      = (expected_after − observed_after) / expected_after × 100
```

## Assumptions to verify

Domain rules live in [`safety_eval/config/ncdot_defaults.yaml`](safety_eval/config/ncdot_defaults.yaml)
so they can be corrected without touching code. Confirmed from the context pack:
T-code table (docs/09), EPDO weights 76.8/8.4/1.0 (docs/04), frontal-impact and
lane-departure sets (docs/03, docs/08). Still `[VERIFY]` (the pack does not
define these):

- **Fiche columns `C` / `F` / `L`.** docs/09 confirms `T` = crash type and
  `S` = severity but leaves `C`, `F`, `L` undefined. The road-surface (wet =
  codes 2-6) and light (night = codes 4-6) roles are a best guess used only for
  secondary "Additional Information" cuts, never for the primary crash-type
  targets. Confirm which letters they are (or that they live only in the 43-col
  detailed export).

Override example:

```bash
safety-eval run --fiche f.csv --assignment a.yaml --config my_overrides.yaml
```

```yaml
# my_overrides.yaml - only the keys you want to change
column_roles: {road_surface: C}
```

## Relationship to the full spec

`docs/07-app-spec.md` describes the complete tool: a Streamlit UI over pandas /
pydantic / SQLite, template-preserving Excel writes (XML-level patching +
LibreOffice recalc + integrity verification per `docs/06`), 2021 HSIP warrant
screening, DMV-349 OCR page-indexing, fiche review workflow, field-investigation
files, PPTX decks, and an engineer-in-the-loop LLM draft layer.

This `safety_eval/` package is a correct-but-partial slice of **Phase 1** (fiche
parsing, EPDO/SI, crash rates, before/after) as a testable CLI engine. It does
**not yet** implement: the Streamlit UI, SQLite store, pydantic `CrashRecord`,
template-preserving XML workbook writes (it builds a *new* summary workbook, it
does not populate the real NCDOT template), warrant screening, or the review /
field-investigation / PPTX / LLM phases. Next step is to align to the `src/`
layout and methodology in `docs/07`.

## Develop

```bash
pip install -e '.[dev]'
pytest -q
```

## Ground truth in this repo

- `templates/` — pristine 2023-12-04 Intersection and Section Evaluation
  Workbook templates plus the Split Time Periods variants and the atypical
  one-page report templates (authoritative for cell addresses, CLAUDE.md
  rule 8).
- `examples/SS-6002AD/` — a completed intersection evaluation (NC 91 at SR
  1225/SR 1303, Greene County) with its raw TEAAS before/after exports.
- `examples/04-15-39049/` — a completed SECTION evaluation (SR 1003,
  Johnston County) with the full working set: original fiche, before/after
  crash ID lists, and milepost import files. The test suite regenerates the
  Before/After sheets from these raw inputs and matches the completed
  deliverable row for row, and the recalculated KABCO/SI blocks match exactly
  (Before SI 6.3286, After SI 3.6118).

## Roadmap

- [x] Populate the official NCDOT Intersection Evaluation Workbook template in
      place (columns A-M, integrity-verified, LibreOffice recalc).
- [x] Section Evaluation Workbook population (header-detected layout, Final MP
      column, fiche C/F/L enrichment, milepost import files).
- [x] Evaluation Set-up sheet population (TEAAS date, construction period,
      representative years, intersection leg / section sub-section AADT
      tables) with NCDOT AADT ArcGIS lookup (`safety-eval aadt`).
- [x] 1-page results sheet manual cells (identity block, countermeasure and
      target text, Additional Information, Items for Discussion) with the
      docs/05 style gate.
- [x] Crash-report PII redaction on upload (`safety-eval redact`).
- [x] Binned Crashes sheet (every fiche crash under exactly one period
      banner; whole-month period math mirroring the Date Range Calculator).
- [x] Filtered Fiche generation (`--filtered`): pre-screened review sheet with
      IN STUDY / REVIEW CANDIDATES / NOT IN STUDY groups; statuses prefilled
      only for already-determined ID-list crashes (RE derived when the import
      milepost corrects the coded one, section analyses only); all other
      determinations left blank for the engineer.
- [x] Streamlit app (`streamlit run streamlit_app.py`): pages grouped in
      workflow order (Overview, Fiche Workbook, Redact Crash Reports,
      Review Queue, then the study type's own HSIP Warrants or Evaluation
      Workbook + Assumptions Email pages), with an environment check and
      per-session AI assist settings.
- [x] Fiche review queue with redacted DMV-349 page retrieval (docs/07
      Phase 3): binder OCR page index (`safety-eval binder-index` /
      `binder-get`), queue ordered by GPS or milepost distance, quick
      status entry with docs/03 validation and comment conventions,
      animal-crash skip, JSONL audit trail, template-preserving
      write-back of determinations. Statuses accept the `-2` section
      suffix used by split-section evaluations (seen on SS-6002M).
- [x] Lane departure CL/R ledger (docs/07 item 13) with cross-sheet
      propagation, and QC recount checks (item 14) via `safety-eval
      ledger` / `safety-eval qc`. Validated on the completed SS-6002M
      workbook: recount reconciles exactly (549 in-study = 237 before +
      43 construction + 269 after; ledger consistent across all four
      sheets), completing the docs/07 Phase 3 review-assistance scope.
- [ ] EB before/after; warrant screening.
- [x] Parse the assignment/assumptions email (`.msg`/`.eml`) directly
      (`safety-eval parse-email`): one Order ID/Project ID/location/GPS/
      periods/targets/notes block per assignment, newest copy in the
      thread wins, notes and questions carried through verbatim.
      Validated on the real SS-6002M/SS-6002AS thread.
- [x] Assumptions draft generation from the NCDOT Master Evaluation
      Spreadsheet (`safety-eval assumptions --master ... --order-id ...`):
      DB-sourced fields validated field-for-field against a real archived
      draft; target crashes and periods left for the engineer. The .msg
      thread with NCDOT feedback remains the authoritative record.
- [x] docs/10-evaluation-archive.md: how to structure the past-evaluation
      archive (layout, manifest, PII rules, 50/50 train/verify split)
      for the future report-drafting layer.
- [ ] Empirical-Bayes (EB) before/after in addition to the naive method.
- [ ] 2021 HSIP warrant screening; Streamlit shell per docs/07.
- [ ] Optional Google Drive read/write integration.
