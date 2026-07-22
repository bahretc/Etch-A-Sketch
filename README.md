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

safety-eval parse  --fiche path/to/fiche.pdf     # preview parsed crashes
safety-eval doctor                               # which OCR/PDF backends are available
```

The **assignment** is a small YAML you transcribe once from the assignment /
assumptions email — it is the auditable record of study scope. See
[`examples/example_assignment.yaml`](examples/example_assignment.yaml).

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
| OCR | `ocr.py` | Lazy, pluggable PDF→text (pdfplumber → pypdf → tesseract) |
| Classify | `classify.py` | In-study (by milepost), study period, target crash types |
| Periods | `periods.py` | Date Range Calculator (before / construction / after) |
| AADT | `aadt.py` | Length-weighted corridor AADT by sub-section |
| Analysis | `analysis.py` | Counts by severity/target, crash rates, effectiveness |
| Report | `report.py` | Excel workbook + Markdown |

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

## Roadmap

- [ ] Parse the assignment/assumptions email (`.msg`/`.eml`) directly.
- [ ] Empirical-Bayes (EB) before/after in addition to the naive method.
- [ ] Populate the official NCDOT Section Evaluation Workbook template in place.
- [ ] Optional Google Drive read/write integration.
