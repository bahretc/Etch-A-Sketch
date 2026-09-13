# 07 - Application Spec (merged)

This merges the April 2026 TEAAS application spec with everything learned from the live evaluation work since. One integrated tool, Python + Excel, local.

## Architecture

- Python 3.11+, Streamlit UI, SQLite store, pandas, pydantic models, pytest.
- Excel I/O per docs/06: openpyxl reads, XML-level writes to templates, LibreOffice recalc, integrity verification.
- Optional LLM integration is a thin layer over local or API models; every LLM output is a draft the engineer reviews, never auto-final.

## Data ingestion

- TEAAS text exports: Crash ID List (5-column pipe-delimited) and Detailed Crash ID List (43-column pipe-delimited).
- Fiche workbooks (xlsx) with status/comment columns.
- Master Evaluation Spreadsheet (per-assignment project metadata feeding setup sheets and assumptions emails).
- Existing evaluation workbook templates (intersection and section) as both input (structure) and output (deliverable).
- Detailed fiche coordinate join: per-crash Latitude/Longitude from the TEAAS detailed export, joined by Crash ID, with computed distance-to-study-point feeding the Filtered Fiche screen columns.
- DMV-349 scanned binders (PDF/TIFF): page indexing by OCR of the crash ID header box (150-200 DPI, tesseract psm 6, top-right crop), then per-crash retrieval of front page (coords) and back page (narrative/diagram).
- Internal schema: pydantic CrashRecord covering ID, date/time, route/MP, coded T/C/F/L/S, severity, type text, direction, coordinates, status, bin, target flags, comments.

## Modules and build order

**Phase 1 - Core engine**
1. Parsers (TEAAS text formats, fiche xlsx), CrashRecord schema, crash type category mapping, SQLite persistence.
2. EPDO and Severity Index (76.8 / 8.4 / 1.0).
3. AADT calculations, intersection and strip (round side roads to nearest hundred).
4. Crash rates (MEV and 100 MVM) and critical crash rates.
5. Intersection analysis with frequency tables.
6. Streamlit shell: import, study setup.
7. Unit tests against the known examples: EPDO = 372.2, intersection AADT = 19,900, strip AADT = 1,700, plus fixtures rebuilt from TEAAS Ch. 15 and Ch. 8.

**Phase 2 - Full analysis**
8. Strip analysis with frequency tables; sliding scale; intersection-within-strip buffer sub-analysis.
9. Before/after module: bins (before/construction/after), symmetric-window helper, annualization, target flag handling, per-section splits for non-contiguous sections.
10. 2021 HSIP warrant screening, thresholds parsed from the source PDF.
11. Evaluation workbook generation: populate Before/After (columns A-M only, letting template formulas compute the KABCO/SI blocks), Binned banners, and Filtered Fiche in the real template via XML patching; live formulas for all derived numbers; never touch the EB/CMF tracking section.

**Phase 3 - Review assistance**
12. Fiche review workflow: GPS distance pre-screen first (join detailed fiche coordinates, compute Dist to Signal ft, sort and triage), then a queue of IS/REV/? rows with binder page retrieval per crash, side-by-side coded data vs report, one-keystroke status assignment with enforced comment conventions (docs/03), animal-crash skip, banner-section output (confirmed IS / review required / NIS reviewed / NIS not reviewed), and an audit trail. Never blanket-reclassify. Support non-inventoried study points (manual candidate identification per docs/03).
13. Lane departure CL/R ledger tool with first-harmful-event rule and side-street run-through exclusion propagation (updates every location a value appears).
14. QC recount checks: text tallies vs sheet tallies must match before export.

**Phase 4 - Outputs**
15. PPTX generation (python-pptx): 4-slide corridor deck pattern (summary, strip diagram, fatal/severe, justification), VHB navy/teal/white, conservative chart heights to avoid rotated-label bleed.
16. Collision diagram data export; charts in UI; strip diagram visualization.
17. Field Investigation File generation: Checklist population from slip data + TEAAS crash history, Photos sheet builder (TwoCellAnchor, borders, captions, print check), Sketch aerial pull (ESRI World Imagery export endpoint) with the hard lesson applied: geometry annotation only with engineer-confirmed pixel/coordinate anchors, otherwise embed the provided location map untouched.

**Phase 5 - LLM layer (drafts only)**
18. Items for Discussion and Additional Information draft generation per docs/05 patterns.
19. Pattern narrative and countermeasure recommendation drafts.
20. Assumptions email generation from the Master Evaluation Spreadsheet per the docs/05 template, with validation per docs/06.
21. Fiche comparison assistant (coded data vs narrative extraction).

**Phase 6 - Stretch**
22. DMV-349 structured parsing (fields beyond the ID box), batch multi-study processing, GIS/mapping, SVG collision diagrams.

## Implemented finishing layer (September 2026)

Built from the live 10-18-223 and 77S00141 sessions, each step a module, a
CLI command and an app tab, all tested:

- `aadt_table` + `aadt_arcgis` (NCDOT 2025 AADT Stations layer): leg table with the black/red convention, representative years, colours written by `workbook_cells`.
- `map_block`: team-format Map/Satellite Views composition and oneCellAnchor embedding; Esri World Imagery fallback.
- `print_results`: LibreOffice print matched to the Excel print (Carlito, column padding), pikepdf binding with metadata.
- `qa_checks`: deterministic QA (structure, docs/06 drawings gate, cached diff, AADT colours, text style, Type vs T code, PDF assembly).
- `qa_sweep`: six LLM reviewers plus three refuters over the package folder (Claude Opus 5, structured output, cached context); CONFIRMED / PARTIAL / REFUTED by verifier agreement.
- `redact` + `redact_verify`: PII redaction before review, then an OCR oracle check of the output (names, DOB, phone, licence, addresses), masked reporting.
- `collision_diagram`: strip diagram with fan-out callouts.
- `package`: discover a WO folder, finish it in one pass (redact, map, print, bind, QA log, zip with clean names).
- `chat`: assistant with strict tools over the loaded package (drafts and checks only).

## Non-negotiables carried from live work

- Combination-dependent (intersection) vs milepost-dependent (strip) crash identification implemented as separate, tested code paths.
- Every generated workbook passes verify_integrity against its template.
- Every number in generated report text traceable to a sheet formula.
- Engineer-in-the-loop on all classifications and all LLM drafts; the tool prepares, the PE decides and seals.

## Suggested first Claude Code command

```
Read CLAUDE.md and docs/. Start Phase 1: project structure, requirements.txt,
pydantic CrashRecord, crash type mapping, TEAAS text parsers (5-col and 43-col),
EPDO/SI, AADT (intersection + strip), crash rate and critical rate, unit tests
for the known examples (EPDO=372.2, AADT=19900, strip AADT=1700), and a
Streamlit shell with a data import page. SQLite via a database module.
```
