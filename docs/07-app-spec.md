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
- `strip_diagram`: strip diagram with fan-out callouts (CLI `collision-diagram`). `collision_diagram` is the TSU-sheet diagram of the HSIP Warrants page and the `tsu-diagram` subcommand.
- `package`: discover a WO folder, finish it in one pass (redact, map, print, bind, QA log, zip with clean names).
- `chat`: assistant with strict tools over the loaded package (drafts and checks only).

## Consolidation notes (September 2026)

The finishing layer above was built on a branch that had diverged from the crash analyses app (st.Page navigation, per-study workspace, TSU collision diagrams, fatal Field Investigation File, report drafting, archive verification). The two were merged as follows.

- The finishing modules (`aadt_table`, `certificate`, `chat`, `map_block`, `package`, `print_results`, `qa_checks`, `qa_sweep`, `redact_verify`, `workbook_cells`) and their CLI subcommands (`aadt-table`, `map-block`, `print-results`, `qa`, `chat`, `collision-diagram`, `qa-sweep`, `finish`) came across as they were, alongside the crash analyses subcommands.
- The fan-out strip diagram module is `strip_diagram` (its subcommand is still `collision-diagram`); `collision_diagram` is the TSU-sheet diagram.
- `redact` keeps the form-geometry pipeline (front-page registration, identity zones, per-report name harvest, the study-road address keep, the convergence and output-probe passes, `residual_pii`) and adds the finishing branch's layers on top: caption-anchored bands, the name row above a First/Middle sub-caption, the section-32 table, token patterns (phones, DL and policy digit runs, ZIP+4, dates older than the report era), band-harvested names scrubbed across the report, the 10x/60x crash-id rule, a second page-mode OCR pass at a zero confidence floor, and bilevel output for bilevel scans. The ZIP and study-road keeps are carved out of the bands as well, and only a confident read (conf >= 40) may open a keep hole. `safety-eval redact --verify` runs the `redact_verify` OCR oracle after the redactor's own probe passes.
- In the app the finishing steps are pages under Deliverables for the Evaluation study type: AADT and Set-up, Map Block, Strip Collision Diagram, Print and Assemble, QA Checks (with the multi-agent sweep), Finish Package (loads the WO zip, runs `package.finish_package`, offers the QA log and certificate) and Assistant. Each is a thin view over its module; they share a per-session scratch folder, and workbook inputs default to the open study's Evaluation Workbook. The old Build Evaluation and Review Filtered Fiche tabs were not ported: the Evaluation Workbook and Review Queue pages cover them.
- The Redact Crash Reports page gained the finishing branch's verify option (the `redact_verify` OCR oracle after the redactor's own probe passes), the same as `safety-eval redact --verify`.
- Left to the CLI: the package headline metrics of the old Home tab (`package.workbook_summary`). The finishing pages are not offered for HSIP and fatal studies, which do not produce an Evaluation package; every finishing step is a subcommand for those.

## Strip site package layer (September 2026, beta 0.2.0b1)

Folded in from the 260307016EA fatal analysis, where they ran as scripts:

- `route_geometry` - the NCDOT AADT traffic segments chained into a
  milepost-calibrated centerline (`Centerline.mp_to_ll`, `snap`), horizontal
  curves by heading change with a circle-fit radius, the USGS 3DEP profile
  with crests, sags, grades and a line-of-sight estimate, and the
  `(text, milepost)` rows for the TEAAS feature import. CLI `route-features`.
- `location_check` - report coordinates and Census-geocoded property
  addresses snapped to the centerline and compared with the coded milepost;
  a report only, never a determination. CLI `locate-check`.
- `package_maps` - the Location, Area and AADT maps from a study YAML
  (`MapSpec`), TIGERweb roads, places and hydro, Esri tiles, NCDOT stations,
  Playwright printing. CLI `package-maps`. Assets `vendor/nc_counties.json`
  and `vendor/vhb_logo.png`.
- `calc_aadt` - the strip CalculatedAADT workbook with live formulas.
  CLI `calc-aadt`.
- `fiche_screen.apply_hsip_review` adds a fiche row for an initial study
  crash that is not on the fiche (from the ID and Initial Study sheets);
  `screen_sheet(off_lrs_nis=True)` screens off-LRS rows NIS on strip studies.
- The Streamlit fatal tab carries all four under "Package figures and
  checks"; `doctor --network` probes the public services they use.

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

Fatal crash Field Investigation File (Phase 4 item 17): `safety-eval
fatal-checklist --slip <slip>.pdf --fiche <study>_Fiche.xlsx` parses the
NCDOT Fatal Crash Notification by label, prefills the Checklist with the
slip's facts (location from the coded roads, slip number, division,
county) plus the TEAAS crash history tallied at the site (road-stem
match against the area pull, since TEAAS truncates names), and writes
the workbook: Checklist on the docs/02 cells, Photos skeleton at the
documented caption spacing, Sketch page that embeds a PROVIDED location
map untouched. Field observations stay blank for the visit; the docs/05
style gate runs on every prefilled line. Same flow on the Field
Investigation page (Fatal study type). Validated against the completed
TSUINT596369 checklist and the M260408001 slip + fiche.

A section site (260307016EA, US 311, a mid-block fatal on a strip
section) narrows the tally by milepost instead of road name, because a
strip study is milepost-dependent (rule 5): `--route "US 311" --lo
10.438 --hi 11.604` keeps the rows mileposted on the route between the
study limits. `--initial-study <study>_InitialStudy.csv` adds the TEAAS
analysis report's Summary Statistics to the Crash History block, read by
label (counts, ADT, length, exposure, rates, severity index, EPDO index,
leading types); `--history-line` (repeatable) appends the engineer's own
lines, such as the fatal narrative stated from the DMV-349; and
`--speed-limit` writes the report's authorized speed limit, posted or
statutory being the visit's call. Rural slips carry a direction on the
offset ("1.4 miles N from SR 1980") and a "2 miles N of Walkertown"
line; both are parsed. The Field Investigation page reads the route,
milepost limits, analysis report and location map off the open study
and takes the engineer's lines in a text area. Workspace roles:
`crash_report` (the DMV-349 PDFs), `crash_map`, `analysis_memo`.

Report text drafting (Phase 5, drafts only): `safety-eval draft-results
--workbook Eval.xlsx --train train.jsonl` drafts the Items for Discussion
cell and the Additional Information rows of a NEW evaluation workbook, the
targets located by label (results_sheet.manual_text_targets, rule 8), with
train-half exemplars and the docs/05 style + numeric gates run before
anything is shown. The same flow is the Report Text page under
Deliverables. Nothing is ever written to the workbook: the engineer
reviews, edits and pastes.

Collision diagrams: `safety-eval tsu-diagram --data <WO>_CollisionDiagramData.txt
--layout layout.json --out sheet.html` renders the MicroStation-style 11x17
TSU sheet. The layout's `"kind"` selects it: `"intersection"` draws the
junction north up at its legs' true bearings so every unit arrow reads at
its coded compass direction (validated against the delivered 41000077750
sheet; example layout in `examples/41000077750/diagram_layout.json`);
anything else draws the section sheet. ``"kind": "bikeped"`` renders the
Bike/Ped aerial exhibit (docs/12; the delivered 59X00239 sheet is the
reference, example layout in `examples/59X00239/bp_diagram_layout.json`):
crash cells pinned on a provided TransparentMap underlay, orange
lighting and ped signal heads, the four blue Bike/Ped markers, and the
extended legend. The intersection and Bike/Ped sheets are also on the
HSIP Warrants page (intersection branch).

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
