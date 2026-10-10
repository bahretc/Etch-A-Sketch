# Etch-A-Sketch - fatal crash analysis tooling (fca)

Tooling for NCDOT Traffic Safety Unit fatal crash analyses. It takes the TEAAS exports for a
study, screens the fiche against the study limits, writes the Fiche workbook in the TSU working
format, lists the crash IDs whose DMV-349 reports need to be read, and draws the study maps.

```
python -m fca build studies/260722124BA          # workbook, review list, figures (and the reviewed workbook when determinations exist)
python -m fca build studies/260722124BA --no-maps
python -m fca screen studies/260722124BA         # print the screening only
```

Requires Python 3.11+ and `pip install -r requirements.txt` (openpyxl, matplotlib, pillow);
`pdftotext` (poppler) reads the TEAAS Features Report PDF. Basemap tiles come from Esri World
Imagery / World Street Map and are cached in `~/.cache/fca-tiles` (override with `--tile-cache`).

## Study folder layout

```
studies/<study_id>/
  study.json          limits, features (with revised mileposts), centerline, fatal crash, screening thresholds, figure settings
  inputs/             TEAAS exports: <id>_Fiche.csv, DetailedFiche.csv (+ _parameters), InitialStudy.csv
                      (strip or intersection analysis), InitialID.txt (ID export), FeaturesReport_<route>.pdf,
                      boundaries.json (county / municipal outlines for the area map),
                      aadt.json (NCDOT AADT stations and 2025 traffic segments for the AADT map; optional)
  review/             determinations.jsonl - one line per DMV-349 report read (decision IS/ADD/DEL/NIS, report
                      location and milepost, facts, confidence, verification notes); when present the build writes
                      the reviewed workbook. pe_questions.md (optional) - the calls left to the engineer, appended
                      to the report review
  outputs/            <id>_Fiche.xlsx (screened) or <id>_Fiche_reviewed.xlsx (with the report decisions),
                      <id>_ReviewIDs.txt, <id>_screening.json, <id>_review_determinations.jsonl, <id>_ReportReview.md,
                      <id>_Figure1_AreaMap.png/.pdf, <id>_Figure2_LocationMap.png/.pdf,
                      <id>_Figure3_CrashMap.png/.pdf, <id>_Figure4_AADTMap.png/.pdf (report figures in the
                      TSU fatal-crash layout; Figure 4 only when inputs/aadt.json exists),
                      <id>_CrashMap.html (self-contained Leaflet map with embedded imagery)
```

Crash reports, fatal slips and e-mail are not kept in the repository (see `.gitignore`).

## Screening

Every fiche crash gets a flag in the workbook's `IS?` column:

| Flag | Meaning |
| --- | --- |
| `IS` | in the TEAAS initial study and its coding agrees with the section |
| `IS?` | in the initial study, but the milepost or Detailed Fiche coordinates need checking in the report |
| `?` | not in the initial study, but a trigger says it may belong in the section - read the report |
| `NIS` | not in the initial study and nothing points at the section |

Triggers (`Review IDs` sheet, `Trigger` column): **In study**, **IS-verify**, **Between** (the
from/toward/miles description implies a milepost inside or just outside the limits, using the
features report with the study's revised mileposts), **DMV** (Detailed Fiche coordinates project
onto the route inside the limits), **Combo** (MP 999.999 crash coded with section or route road
names), **Window** (mileposted on the route within 0.1 mi outside the limits). Each `?` crash
carries a screening call in its Reason: Likely ADD, Possible ADD, Window, At the intersection,
or Check (description and coordinates disagree). The Decision column (yellow) is for the
engineer's call after reading the report: ADD / DEL / IS / NIS.

## Report review

After the DMV-349 reports are read, each reviewed crash gets a line in `review/determinations.jsonl`.
The build then writes `<id>_Fiche_reviewed.xlsx`: the fiche in five sections (IN STUDY, ADDED TO STUDY,
DELETED FROM STUDY, NOT IN STUDY - REPORT REVIEWED, NOT IN STUDY - REPORT NOT REVIEWED), the Review IDs
sheet with the Decision column filled and the report location, milepost, facts and confidence beside the
screening reason, plus `<id>_ReportReview.md` (summary table, section crash summary, facts, independent
verification notes and the engineer's open decisions for the memo). Figure 3 is redrawn with the crashes at
their report locations, colored by decision. The crash reports themselves stay out of the repository.

## Figures

Figures 1 to 4 follow the Traffic Safety Unit fatal-crash figure layout (landscape letter, title strip with
the slip number, county thumbnail, crash coordinates, milepost and division). Figure 1 (Area Map) draws the
county and municipal boundaries from `inputs/boundaries.json` over the Esri street map; Figure 2 (Location
Map) and Figure 3 (Crash Map) use Esri imagery with the study limits, side streets and (Figure 3) the
numbered reviewed crashes; Figure 4 (AADT Map) colors the NCDOT 2025 traffic segments by AADT and numbers
the AADT stations, with their count history in a table. Label positions, shield positions, the crash callout
and the map extents are set per study under `figures` in `study.json`.

## Workbook sheets

`<id>_Fiche` (IN STUDY / NOT IN STUDY - REPORT REVIEWED / NOT IN STUDY - REPORT NOT REVIEWED,
with the Type, Dir, Latitude, Longitude, Unit 1 Dir, Unit 2 Dir and Movement formulas),
`Review IDs`, `ID` (fiche vs. initial study cross-check), `Index` (crash type codes),
`Initial Study` (the TEAAS report as exported) and `DetailedFiche`.

## Package

- `fca/teaas.py` parsers for the TEAAS CSV / TXT / PDF exports
- `fca/geo.py` distances, centerline projection, Web Mercator tiles
- `fca/screen.py` screening rules
- `fca/workbook.py` the Fiche workbook and the review list
- `fca/review.py` applies report determinations to the screened fiche
- `fca/figures.py` report figures: Area Map, Location Map, Crash Map (matplotlib over stitched tiles, PNG + PDF)
- `fca/maps.py` the Leaflet HTML map and the crash placement shared with the figures
- `fca/cli.py` command line
