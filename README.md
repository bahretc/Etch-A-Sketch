# Etch-A-Sketch - fatal crash analysis tooling (fca)

Tooling for NCDOT Traffic Safety Unit fatal crash analyses. It takes the TEAAS exports for a
study, screens the fiche against the study limits, writes the Fiche workbook in the TSU working
format, lists the crash IDs whose DMV-349 reports need to be read, and draws the study maps.

```
python -m fca build studies/260722124BA          # workbook, review list, maps
python -m fca build studies/260722124BA --no-maps
python -m fca screen studies/260722124BA         # print the screening only
```

Requires Python 3.11+ and `pip install -r requirements.txt` (openpyxl, matplotlib, pillow);
`pdftotext` (poppler) reads the TEAAS Features Report PDF. Basemap tiles come from Esri World
Imagery / World Street Map and are cached in `~/.cache/fca-tiles` (override with `--tile-cache`).

## Study folder layout

```
studies/<study_id>/
  study.json          limits, features (with revised mileposts), centerline, fatal crash, screening thresholds
  inputs/             TEAAS exports: <id>_Fiche.csv, DetailedFiche.csv (+ _parameters), InitialStudy.csv
                      (strip or intersection analysis), InitialID.txt (ID export), FeaturesReport_<route>.pdf
  outputs/            <id>_Fiche.xlsx, <id>_ReviewIDs.txt, <id>_screening.json,
                      <id>_Map1_Location.png, <id>_Map2_StudySection.png, <id>_Map3_CrashMap.png,
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
- `fca/maps.py` PNG maps (matplotlib over stitched tiles) and the Leaflet HTML map
- `fca/cli.py` command line
