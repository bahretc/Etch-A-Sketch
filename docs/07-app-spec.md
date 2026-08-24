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

The report PDF (`safety_eval/report_pdf.py`, CLI `report-pdf`): the
delivered "{project} Web.pdf" is the '1 page results' sheet printed over
the sheet's own saved print area, followed by the standard 2020-data
disclaimer page shipped at templates/Disclaimer_2020_Data.pdf. The
WORKBOOK carries the look: `results_sheet.format_results_sheet` (run by
fill-template --results) reproduces the engineer's manual formatting.

The rule that governs the text blocks, read off his five completed
workbooks: **row heights are never touched** (rows 58-66 are 15.0pt and
row 57 is 18.0pt in every one of them), and **the blank row above 'Data
Prepared For:' is never taken**. What changes instead is the FONT SIZE,
on a 0.5pt grid: Items for Discussion at 11.0, 10.0 and 9.5pt across the
archive, the narrower Countermeasure(s) and Target Crashes blocks down to
8.0pt. `safety_eval/text_fit.py` measures a block with the real font
metrics (Times New Roman; Liberation Serif is metric-identical) against
the merged cell computed from the sheet's own column widths and row
heights, and picks the largest size that fits. The model reproduces his
own choice on every archive workbook, including SS-6003Z where 10.5pt
overflows the native cell by 0.8pt and he used 10.0pt.

When even the smallest size will not fit, the code does what he does in
SS-6202A and SS-6010O: `plan_items_growth` INSERTS whole rows under the
Items cell (`xlsx_patch.insert_rows`), extends the merge into them,
carries the box border down, and shifts the footer, the spacer row and
the saved print area with them. Rows are added only while the print
scale stays at his 64; if the text still does not fit, the build fails
loudly rather than printing a silently clipped cell. Insertion refuses
outright if the shifted region holds a formula, which is why only this
block (nothing below row 55 has one) can grow.

The print itself goes through the UNO bridge in memory (python3-uno +
libreoffice-calc; the file on disk is never modified) at the workbook's
saved scale, which must be re-applied through the page style because
LibreOffice drops a saved xlsx print scale on import; ONLY the
print-range selection is exported, since the `--convert-to pdf` path
ignores print areas and prints hidden sheets. **Fonts must be the real
msttcorefonts faces**: with only the metric-compatible clones installed
the PDF embeds Liberation Serif and Carlito, which reflows nothing but
looks visibly different from the engineer's own Print-To-PDF output
(which embeds TimesNewRomanPSMT and TimesNewRomanPS-BoldMT). Install
Times New Roman and Arial from the corefonts archive before exporting.
An annotated aerial (--map, built per site the way
examples/41000076160/build_aerial.py records) drops into the
Map/Satellite Views box, whose location is measured off the print itself
each time. "Complete Evaluation.pdf" is the same assembly with the two
TEAAS Intersection Analysis Reports appended (--append); those are TEAAS
output the engineer supplies.

`safety-eval teaas-currency` reads the NCDOT Connect TEAAS page and
reports the most recent month of loaded crash data ("TEAAS crash data
is now available through {Month Year}"). Run it before starting any new
analysis so the study periods do not run past the loaded data.
