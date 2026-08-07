# 02 - Workbook Structures

Cell addresses and layouts below were observed on real project files, including a live evaluation workbook shared as a reference (SS-6002AS/SS-6002AD template with guidance sheets). Template versions drift; when a template is in templates/, verify against it before hardcoding.

## Intersection Evaluation Workbook

Typical sheets: Evaluation Set-up, Initial Study, Original Fiche, Filtered Fiche, Binned Crashes, Before, After, 1 page results - 1 Target, 1 page results - 2 Targets, Typical Target Crash Types, Step-by-Step.

### Evaluation Set-up

Two tools live here.

Date Range Calculator: most recent TEAAS date, construction period length in months (cells D5/D6), or construction start date directly in D10. Rules: works in WHOLE months only; construction start rounds up to the first of the month, construction end rounds down to month end; use a typical 3-month construction period unless specific information says otherwise (provided dates, satellite imagery). Outputs the Before/Construction/After start dates, end dates, years, and months that drive the results sheets.

AADT Calculator: yearly AADT rows (one per year across the study range) with Major Road Leg 1/Leg 2, Major average, Minor Leg 3/Leg 4, Minor average, Intersection AADT columns. Representative year selection cells (N5/N6): pick the last year in each period with ACTUAL collected volume data, never 2020 (COVID effects), even if 2020 is the last year with data. Font convention: black for actual collected values, red for calculated/interpolated/assumed values. Input AADTs for every year inside the study periods only. Intersections with 5 or more legs: compute whole-intersection yearly volumes manually into column R. One-way roads break the tool: enter the total entering volume directly into column O (major one-way) or column R (minor one-way).

### Original Fiche (TEAAS Fiche Report)

Header block: County, County Code, Division, Municipality, Municipality Code, Begin Date, End Date, Years, Y-Line Feet (150 typical). A LocationID appears for inventoried studies. Then a Road Name / Road Code table listing every road pulled. Route code prefixes and the T-code map are in docs/09.

Crash rows: Muni. Code | On Road | Miles | Dir From | From Road | Toward Road | Milepost Road | MP | MA | Crash ID | Date | T | C | F | L | S. MP 999.999 means not mileposted (crash referenced to an address or PVA driveway in On Road, e.g. "*LCL 1226 E DIXIE DR" or "PVA 737 W DIXIE DR"). Page footers ("Page 1 of 224") appear between blocks in raw pulls and must be stripped on ingest.

### Assembling the study fiche workbook (step 1 of a review)

Four TEAAS exports become one workbook before any determination is made.
`safety_eval/fiche_workbook.py`, or:

```
safety-eval fiche-workbook --study 41000079305 \
  --fiche OriginalFiche.csv --initial-study InitialStudy.csv \
  --initial-ids InitialID.txt --detailed DetailedFiche.csv
```

Order of operations:

1. Copy the Fiche Report CSV to `<study>_Fiche.csv`. The study number names
   everything downstream.
2. Convert it to `<study>_Fiche.xlsx`, sheet **`<study>_Fiche`**, formatted
   per the rules below.
3. Sheet **ID**: column A takes every fiche crash ID in fiche order; the
   pipe-delimited ID export is pasted at column H; column B repeats its crash
   IDs; column D flags whether each is in the fiche; column C (`IS?`) is left
   blank for the engineer.
4. Sheet **Initial Study**: the Strip (or Intersection) Analysis Report CSV.
5. Sheet **DetailedFiche**: the Detailed Fiche CSV, the only export carrying
   Latitude/Longitude/Source. It routinely covers fewer roads than the fiche;
   that is expected and not an error.
6. Sheet **Index**: the T-code map, which the Type column looks up against.

**Fiche formatting rules.** The `<study>_Fiche` sheet is the **working sheet**,
not a raw paste. The delivered *Original Fiche* sheets are verbatim pastes and
are a red herring; the sheet an engineer actually works is the **Filtered
Fiche**, and these rules come off it (`examples/SS-6002AD`):

- **Column setup.** The raw fiche row carries 16 fields under a 15-cell header,
  because "Miles / Dir From" is one header spanning two data columns. Split
  into `Miles` and `Dir From`, and insert `IS?` and `New MP` after `MP`, so the
  labels line up with the data.
- **Rows removed:** title block, County/Division header block, Road Name / Road
  Code table, every "Page 1 of 13" footer, every repeated `Muni. Code` header
  block, and the trailing legend. One row per crash, nothing else.
- **Sorted by milepost** ascending; MP 999.999 (never mileposted) lands at the
  end on its own value.
- **Type** = `VLOOKUP(T, Index!$A$1:$B$26, 2, FALSE)` against the T-code map,
  which ships as the `Index` sheet.
- **Dir** is the movement pair, built from the two vehicle directions the
  Initial Study records on the `Unit` lines under each crash: MATCH the crash ID
  in column B, step down one row for vehicle 1 and two for vehicle 2, read
  column K. The `NOT(ISNUMBER(...))` guard on vehicle 2 is what stops a
  single-vehicle crash from picking up the *next* crash's row. The pair is then
  shaped by type: RE is BT/BT, LTSR and LTDR are BL/BT, RTSR and RTDR are BR/BT.
  Helper columns Y/Z/AA hold vehicle 1, vehicle 2, and the assembled pair.
- **Latitude / Longitude** = INDEX/MATCH into the `DetailedFiche` sheet on crash
  ID.
- Every formula is `IFERROR`-wrapped. Most fiche crashes are not in the initial
  study, and a sheet of #N/A is not workable.
- Cells are typed as Excel types a paste: crash ID a number, milepost a float,
  date a date. The lookups depend on it. Identifiers with a leading zero
  (county code `075`) stay text.

**Screening: which reports to pull.** `safety_eval/fiche_screen.py`. Initial
Study crashes are `IS`. For the rest, each From/Toward cell resolves to a
milepost on the study route through the Features Report and is coloured: green
inside the limits, blue north/east, yellow south/west. Then:

- **a green cell**, or **two different colours** -> `?`, pull the report. Blue
  against yellow is the case worth naming: the roads sit on opposite sides, so
  whatever lies between them crosses the study.
- **the same colour on both sides** -> `NIS`.

Not filtered by the coded milepost, deliberately. The fiche also gives a
distance from the named road, but that distance is the officer's, and checking
it is exactly what the report review is for; a milepost derived from the number
under review cannot be used to skip the review.

Two traps. **US 74 has two mile-marker series** (marker 62 at MP 3.638, marker
162 at 9.696, because numbering restarts at the I 26 junction), so a loose
match moves a crash six miles. And **a crash on a cross street is placed where
that street meets the study route**, not by its own milepost: NC 9 crashes are
at US 74 MP 14.455, NC 108 crashes at 10.125.

**The ID sheet's column layout is a record of how the export was pasted.** The
header `CRASH ID|ON RD CD|SVRTY|DATE|TYPE|` was split on pipes **and spaces**,
so its 5 fields land in 8 header cells (H:O) over 6 data cells (H:M), the date
field having become a date cell and a time cell. Reproduced exactly.

### Filtered Fiche

The working review sheet. Same base columns plus: IS? | Type | Dir | Comment | Latitude | Longitude | Dist to Signal (ft), and a color key column at far right.

Rows are grouped under banner rows by status: "IN STUDY - CONFIRMED BY CRASH REPORT REVIEW (with the study location named)", "REPORT REVIEW REQUIRED - REMAINING CANDIDATES (2ND REPORT PULL NEEDED)" (status REV), "NOT IN STUDY - REPORT REVIEWED", and NIS without review where applicable. Type is the decoded crash type abbreviation; Dir is the movement pair (e.g. NBL/EBT for vehicle 1 / vehicle 2). Latitude/Longitude come from the detailed fiche joined by Crash ID; Dist to Signal (ft) is computed from those coordinates to the study point and is the screening starting point (workflow in docs/03).

### Binned Crashes

Single table with period banner rows: "Prior to the Before Period (before {date})", "Before Period ({dates})", "Construction Period ({dates})", "After Period ({dates})", then "NIS crashes - Reviewed crash reports" and "NIS crashes - Did not review crash reports". Every fiche crash lands under exactly one banner.

### Before and After

Header row 3, data from row 4 in the xlsx versions. Columns A through M are the ONLY manually edited columns: A Crash ID, B Date, C T, D C, E F, F L, G S, H-K Analyst's Notes Columns 1-4, L Target-1?, M Target-2? (literal "Y"; Target-2? blank when a single target is defined). Right of column M are auto-calculated blocks: Crash #, Crash Year, Severity Index, Target-1 SI and KABCO, Target-2 SI and KABCO, plus KABCO summary tables (K/A/B/C/O/Total/SI) for Total, Target-1, Target-2, and All Targets. Generated workbooks must write only A-M and let the formulas do the rest.

### 1 page results (1 Target and 2 Targets variants)

Blocks, top to bottom: Order ID, Project ID, Signal ID, Location, GPS Coordinates, County, City, Division; Treatment Information table (Total Crashes, Total Severity Index, Target Crashes, Target Crash Severity Index, Volume with the two representative years in the label, each with Before / After / Percent Reduction (-) Percent Increase (+)); Countermeasure(s); Estimated Project Cost; Completion Date; period dates table (automated from the Date Range Calculator); Analysis Criteria; Target Crashes definition; Project Development Comparison (crashes per year by Project Development / Before / After with severity rows and the period years, e.g. 10.00 vs 4.67 vs 4.67); Target Injury Crash Summary; Additional Information table (4 free rows for the user; unused rows keep "n/a" in the leftmost column); Items for Discussion (one large merged cell; ALT+ENTER line breaks); Map and Satellite Views; footer (Data Prepared For the Traffic Safety Unit / Data Prepared By / Principal Investigator / Work Group-Consultant / Date). The 2-Target variant splits into All Target, Target-1, and Target-2 rows.

Conventions: tan-shaded cells are manual inputs; when a computed percent increase is far above 100% and "100% +" reads better, the value is manually overridden to "100% +". Printing: highlight inside the green border, Print Selection, custom margins (0.25"/0.5" on the 1-Target sheet, 0.1"/0.3" on the 2-Target sheet), centered horizontally and vertically, Fit Sheet on One Page, Microsoft Print to PDF at 8.5x11.

### Typical Target Crash Types and Step-by-Step

Reference sheets carried from the template unchanged. Typical Target Crash Types is the authoritative per-project source for target and correctability definitions; the general guidance table is transcribed in docs/08.

### EB / CMF tracking section

A protected block labeled for multi-treatment EB analysis and CMF tracking: DO NOT edit programmatically. It contains a single export row (Project ID, Intersection, County, GPS, Project Cost, Countermeasure Description, Countermeasure Grouping, Major/Minor Speed Limit, Install Year, Intersection Type such as R2-3ST/R2-4ST, then Before Yr 1-3 and After Yr 1-3 blocks of Total Crashes / Frontal Impacts / Rear Ends / KABC / Major AADT / Minor AADT) that NCDOT staff copy values-only into their internal SS/HE tracking workbook, plus months-in-period matrices marking each calendar month Before or After.

## Section Evaluation Workbook

Same concept over MP ranges. Observed sheets on SS-6002M (15 sheets, 8 drawings, 6 media images): ID, Original fiche, Filtered Fiche, Binned Crashes (sometimes split per section, e.g. "Binned Crashes (Up to MP 8.398)"), Before, After, results sheets, Evaluation Set-up.

- Before/After: column A Crash ID, B Date, H Milepost.
- Binned sheets: data from row 3; column B on-road, J final MP, L Crash ID.
- Non-contiguous sections are common; every crash count is reported per section and combined (e.g. Total Crashes 237/269 means before/after).
- Correctable-direction ledgers (lane departure CL vs R splits) live alongside target flags for rumble strip projects.

Analysis sheets built for these (W-5206AA pattern) use live COUNTIFS formulas keyed to the Before/After sheets:

```
Period years:  =(EndDate-StartDate)/365.25
Count in MP range: =COUNTIFS(Before!$H:$H,">="&MP_Start,Before!$H:$H,"<="&MP_End)
Type counts:   =COUNTIFS(...,"*rear*") etc.
Intersection sub-analysis within a strip: buffer cell (e.g. N2) with
  Buffer Start =Milepost-$N$2, Buffer End =Milepost+$N$2, COUNTIFS against the buffer
Change: =After-Before, % Change: =(After-Before)/Before
```

The adjustable buffer cell must remain a cell reference so the whole workbook recalculates when it changes.

## Standalone fiche workbooks (crash review outside an evaluation)

One row per fiche crash with a status column (IS/NIS/ADD/?) and comment column; conventions in docs/03. Some carry a page index built by OCR of the crash ID box on DMV-349 front pages (top-right header, 150-200 DPI, tesseract psm 6, crop approximately `rect.x1*0.75, rect.y0, rect.x1, rect.y0 + rect.height*0.08`).

## Field Investigation File

Sheets: Checklist, Sketch, Photos, plus MUTCD reference sheets (MUTCD Curves, MUTCD Intersections, MUTCD STOP) deleted from the deliverable when not relevant.

Checklist observed cells: D5 Location, D7 Slip #, D9 Division, D11 County, D16 Speed Limit, D20 Ball Bank readings, D24 Signing, D31 Roadside development, lane/shoulder width entries around A32/B32, D45-D48 Crash History (TEAAS pull: counts, ADT, rate, fatal narrative), D50-D51 Remarks, D56-D58 Recommendations, H3 investigation date, J3 time. Narrative cells use Cambria 9.

Photos sheet: repeating photo blocks; caption rows at 37, 75, 113, 151, 189, 227, 265, 303, 341 (38-row spacing), block headers 2 rows above the next block. Images are TwoCellAnchor, enlarged, centered, thin black border, centered captions, and must print correctly.

Sketch sheet: embedded aerial (Nearmap or ESRI World Imagery export REST endpoint works without a key) with annotation overlay. Caution: OSM node geometry and slip coordinates can both be wrong; a provided location map beats generated annotation when geometry is uncertain.

## PPTX outputs

Corridor crash analysis decks (Lumberton pattern): 4 slides (summary, crash density strip diagram, fatal/severe crashes, project justification), navy/teal/white VHB-style palette. Watch rotated text label bounding boxes bleeding into adjacent zones; keep chart heights conservative.
