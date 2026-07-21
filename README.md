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

> **Status:** working core engine (v0.1). The domain-specific rules were
> reverse-engineered from example fiches and Section Evaluation Workbooks and
> are all marked `[VERIFY]` in the config — confirm them before using results
> in a deliverable (see *Assumptions to verify* below).

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

All domain knowledge lives in [`safety_eval/config/ncdot_defaults.yaml`](safety_eval/config/ncdot_defaults.yaml)
so it can be corrected without touching code. Confirm the `[VERIFY]` items:

- **Column roles** — which fiche letter (`T C F L S`) is crash-type / units /
  road-surface / light / severity. Confirmed: `T`=crash type, `L`=light,
  `S`=severity. To confirm: which of `C`/`F` is the road-surface code.
- **Crash-type code groups** — the NCDOT crash-type code numbers for rear-end,
  lane-departure, angle, etc.
- **EPDO weights** and **truck code ranges**.

Override example:

```bash
safety-eval run --fiche f.csv --assignment a.yaml --config my_overrides.yaml
```

```yaml
# my_overrides.yaml — only the keys you want to change
column_roles: {road_surface: C}
crash_type_groups: {rear_end: [30, 31, 32, 33]}
```

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
