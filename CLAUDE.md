# NCDOT HSIP Safety Evaluation Application

## What this project is

An integrated local tool for NCDOT Highway Safety Improvement Program (HSIP) work performed by a licensed PE at VHB (Raleigh, NC). It combines:

1. A TEAAS-style crash analysis engine (intersection and strip studies, EPDO, crash rates, warrant screening)
2. Before/after safety evaluation automation (the NCDOT Intersection Evaluation Workbook and Section Evaluation Workbook deliverables)
3. Fiche review and crash classification assistance (IS/NIS/ADD determination against DMV-349 reports)
4. Field investigation workbook generation (fatal crash slips)
5. Report text generation (Items for Discussion, Additional Information tables, assumptions emails)

Target stack: Python 3.11+, working directly with the real NCDOT Excel templates. Streamlit for UI. pandas, openpyxl (read side), direct zipfile/XML editing (write side for templated workbooks), pydantic, pytest, SQLite.

## Read these before coding

- docs/01-domain-context.md - the NCDOT HSIP program, study types, terminology
- docs/02-workbook-structures.md - sheet and column layouts of every deliverable workbook
- docs/03-crash-review-rules.md - the classification methodology (this is the domain logic; do not improvise on it)
- docs/04-calculations.md - EPDO, rates, AADT, periods, annualization
- docs/05-report-writing.md - text output patterns and writing style rules
- docs/06-excel-handling.md - MANDATORY file handling rules for templated workbooks
- docs/07-app-spec.md - architecture, modules, and build order
- docs/08-target-crash-guidance.md - the official countermeasure to target-crash mapping table
- docs/09-teaas-code-tables.md - T-code lookup, route code prefixes, fiche field conventions

## Hard rules (do not violate)

1. **Match NCDOT methodology exactly.** Formulas and constants come from NCDOT TEPPL N-13, the TEAAS training chapters, and the 2021 HSIP Warrants. Do not substitute FHWA or AASHTO values.
2. **EPDO constants: K/A = 76.8, B/C = 8.4, PDO = 1.0.** These are the active NCDOT values.
3. **Never resave a workbook that contains drawings, charts, or images with openpyxl.** See docs/06-excel-handling.md. Templated deliverables are edited by direct XML manipulation inside the zip, followed by a single LibreOffice headless recalc, with byte-identical verification of drawings and media.
4. **Generated workbooks use live Excel formulas, not hardcoded values**, especially buffer-based intersection analyses with an adjustable buffer cell. Reviewers must be able to trace every number.
5. **Intersection studies are road-combination-dependent; strip studies are milepost-dependent.** This is the fundamental difference in crash identification logic and the most important thing to get right.
6. **Writing style for any generated report text:** plain and understated, no em dashes anywhere, no flourishes. See docs/05-report-writing.md.
7. **AADT estimates for minor/side roads are rounded to the nearest hundred.**
8. When a real template workbook is present in templates/, it is ground truth for cell addresses and structure. The docs describe known layouts, but template versions can drift; verify addresses against the actual file before writing code that depends on them.

## Repo layout

```
/
  CLAUDE.md
  docs/                  domain knowledge (this pack)
  templates/             real NCDOT template workbooks (add these; they are ground truth)
  examples/              completed sanitized deliverables for reference and tests
  src/                   application code
  tests/                 pytest suite, including the known-value tests in docs/04
```
