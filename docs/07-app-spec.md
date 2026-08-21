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

## The shipped app (2026-08)

`streamlit run streamlit_app.py` (the repo-root launcher; the package app
cannot run as a bare script). The sidebar's study type governs the tabs:
every type gets Fiche Workbook, Redact Crash Reports and Review Queue; an
Evaluation adds Evaluation Workbook; an HSIP Package Analysis adds HSIP
Warrants (section or intersection). Tabs a study type must not use are not
rendered (docs/12). Theme: Okabe-Ito primary, no state carried by colour
alone; verdicts are words.

Collision diagrams: `safety-eval tsu-diagram --data <WO>_CollisionDiagramData.txt
--layout layout.json --out sheet.html` renders the MicroStation-style 11x17
TSU sheet. The layout's `"kind"` selects it: `"intersection"` draws the
junction north up at its legs' true bearings so every unit arrow reads at
its coded compass direction (validated against the delivered 41000077750
sheet; example layout in `examples/41000077750/diagram_layout.json`);
anything else draws the section sheet. The intersection sheet is also on
the HSIP Warrants page (intersection branch). Bike/Ped diagrams are a
distinct format and are NOT covered yet (docs/12).

The HSIP flow in CLI form, end to end on a reviewed fiche workbook:

    safety-eval fiche-workbook --study N --fiche F.csv --initial-ids I.txt \
        --study-type hsip --features FR.pdf --lo 12.8 --hi 13.815 --route "US 74"
    safety-eval check-branches --workbook N_Fiche.xlsx --sheet N_Fiche --initial-ids I.txt
    safety-eval warrants --workbook N_Fiche.xlsx --facility freeway \
        --lo 12.8 --hi 13.815 --override 107591377:l=5 \
        --initial-ids I.txt --import-out N_Import.txt
    safety-eval apply-review --workbook N_Fiche.xlsx --determinations dets.jsonl \
        --initial-ids I.txt          # the reviewed layout, branch-checked
    safety-eval import-list / feature-list / assist-score
    safety-eval warrants ... --report-out N_Warrants.txt   # docs/05 report text

`safety_eval/hsip.py` is the seam: it reads the ENGINEER'S determinations off
the reviewed working sheet (typed Type cells beat the T-code lookup), applies
recorded overrides (yellow on the Warrant sheet, original kept on the fiche),
joins crash times off the ID sheet for the daylight QC, and refuses to run
warrants for a study type that does not have them.
