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

```bash
pip install -e .            # core (PyYAML + openpyxl)
pip install -e '.[pdf]'     # + PDF text extraction (pdfplumber / pypdf)
pip install -e '.[ocr]'     # + OCR for scanned fiche (pytesseract / pdf2image)
```

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

# the app: upload -> redact -> review -> build, in a browser
pip install -e '.[ui]' && streamlit run safety_eval/app.py

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
```

The Streamlit app (`streamlit run safety_eval/app.py`) has a tab for each of
these plus a chat page over the session's workspace. `safety-eval doctor`
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
| TEAAS exports | `teaas.py` | 5-column Crash ID List parser (numeric SVRTY → KABCO) |
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
| PII redaction | `redact.py` | Blacks out names, addresses, DOB, phone, DL numbers on uploaded crash reports; keeps ZIPs and crash IDs; image-only output so no text layer can leak |

### Crash-report PII redaction

Uploaded DMV-349 scans are redacted before review: OCR (tesseract) locates PII
by form labels (Name/Address/DOB/Phone/License captions), street-address
patterns, and city/state/ZIP continuation lines. ZIP codes and 9-digit crash
IDs are always kept. The output PDF is rasterized with the boxes burned in, so
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
- [x] Streamlit app shell (`streamlit run safety_eval/app.py`): Build
      Evaluation, Redact Crash Reports (PII removed on upload), Review
      Filtered Fiche tabs.
- [ ] Fiche review queue with redacted DMV-349 page retrieval (GPS
      pre-screen, one-keystroke statuses per docs/07 Phase 3).
- [ ] Assumptions email generator (docs/05); EB before/after; warrant
      screening.
- [ ] Parse the assignment/assumptions email (`.msg`/`.eml`) directly.
- [ ] Empirical-Bayes (EB) before/after in addition to the naive method.
- [ ] 2021 HSIP warrant screening; Streamlit shell per docs/07.
- [ ] Optional Google Drive read/write integration.
