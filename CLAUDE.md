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
- docs/10-evaluation-archive.md - archive layout, manifest schema, the frozen train/verify split
- docs/11-review-assist.md - the LLM review assist: decide vs prepare, redaction dependency, measured behaviour
- docs/12-hsip-warrants.md - the three study types and the 2024 HSIP warrant thresholds
- docs/13-beta-walkthrough.md - install, the fatal slip start to finish on CLI and app, known limits

## Hard rules (do not violate)

1. **Match NCDOT methodology exactly.** Formulas and constants come from NCDOT TEPPL N-13, the TEAAS training chapters, and the 2021 HSIP Warrants. Do not substitute FHWA or AASHTO values.
2. **EPDO constants: K/A = 76.8, B/C = 8.4, PDO = 1.0.** These are the active NCDOT values.
3. **Never resave a workbook that contains drawings, charts, or images with openpyxl.** See docs/06-excel-handling.md. Templated deliverables are edited by direct XML manipulation inside the zip, followed by a single LibreOffice headless recalc, with byte-identical verification of drawings and media.
4. **Generated workbooks use live Excel formulas, not hardcoded values**, especially buffer-based intersection analyses with an adjustable buffer cell. Reviewers must be able to trace every number.
5. **Intersection studies are road-combination-dependent; strip studies are milepost-dependent.** This is the fundamental difference in crash identification logic and the most important thing to get right.
6. **Writing style for any generated report text:** plain and understated, no em dashes anywhere, no flourishes. See docs/05-report-writing.md. A roundabout or mini-roundabout is never called a "circle" or "traffic circle" in any text, comment or note; write roundabout.
7. **AADT estimates for minor/side roads are rounded to the nearest hundred.**
8. When a real template workbook is present in templates/, it is ground truth for cell addresses and structure. The docs describe known layouts, but template versions can drift; verify addresses against the actual file before writing code that depends on them.
9. **Never deliver stand-in or placeholder deliverables.** TEAAS exports (CrashID.txt, the strip or intersection analysis CSV and PDF, ID exports) come only from TEAAS. Do not fabricate, reconstruct or re-render them from other inputs and send them as if they were the deliverable. If a file can only come from TEAAS or another system the engineer runs, give the inputs to enter there (study criteria, import list, deletions) and stop.
10. **Start every evaluation from NCDOT's provided template workbook and follow its Step-by-Step Instructions tab to the letter** (VHB QC, Assignment 37, 2026-09). Do not rebuild or restructure template sheets (Trends, One Pager, lists, links) unless a fundamental error forces it; report prototype defects to the engineer instead. Paste the TEAAS fiche parameters export into the Parameters tab. Assumptions go to NCDOT inside the workbook (Assumptions sheet, Evaluation Set-up, map block with alt text), not as a separate email.
11. **One pager reports are public documents.** Never mention TEAAS, the workbook, the fiche or other internal tools in report text. Leave out exact crash times, and dates unless they matter, unless there is a time-of-day pattern. Spell out every crash-type acronym in the target crash text. Describe the countermeasure's specific components (pedestrian upgrades, signs, signal heads). Every image carries alt text. Export the PDF with Save As PDF (tagged, accessible), never Print to PDF. See docs/05.

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
