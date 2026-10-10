# 05-08-203 (TIP W-5601HP), evaluation order 41000076575

SR 1375 (Lake Wheeler Road) at SR 1390 (Optimist Farm Road)/SR 1503 (Donnybrook
Road), Wake County, Division 5. Realigned SR 1390 and SR 1503 to tie directly
across from one another and installed shoulder-mounted actuated flashers on
SR 1375. Assignment 40, 2026 cycle.

`Accessible Intersection Evaluation Workbook - 05-08-203 (W-5601HP).xlsm` is
the office workbook with Step-by-Step Instructions steps 1 and 2 started: the
Assumptions sheet and the Evaluation Set-up sheet are filled, and the previous
project's data (the copy in the WO folder was the 08-17-5149 workbook renamed)
is cleared from the sheets the later steps fill, its map block and station
map pictures are removed, and the One Pager template path is blanked. Built by
`examples/41000076575/build_setup_workbook.py` from the WO folder copy; every
write is an XML-level cell edit, no row or column was deleted, and drawings,
media, the VBA project and the Power Query parts are byte-identical to the copy.

## What is filled

Assumptions: order, project and signal IDs, location, GPS, county, city,
countermeasure, CMF group (Intersection Realignment), cost, completion date
and notes, y-line, Target Crash 1 (frontal impacts) and 2 (rear ends on the
SR 1375 approaches), statement of problem, other notes, the project
development block (1/1/2011 to 12/31/2015: 35 crashes, 0 K, 0 A, 2 B, 7 C,
26 PDO), speed limits and the leg table (north and south SR 1375 at 45 mph,
west SR 1390 at 35 mph, east SR 1503 at 45 mph, 2025 AADTs from the Set-up).

Evaluation Set-up: TEAAS data through August 2026; construction the three
whole months May to July 2021 (let date May 24, 2021 and completion July 2,
2021 per the Master Evaluation Spreadsheet and the compliance memo, rounded
to whole months as the instructions say), so the periods are Before
4/1/2016 to 4/30/2021 and After 8/1/2021 to 8/31/2026, five years and one
month each; representative years 2019 and 2025. The AADT
table carries 2016 to 2026 for the four legs from NCDOT stations 0920000868
(Lake Wheeler north), 0920000991 (Lake Wheeler south), 0920001913 (Optimist
Farm, about a mile west) and 0920001914 (Donnybrook, east of Ransdell Road):
black cells read the counts, red cells are interpolated (2020 at 0.85, 2026
carried from 2025). The station block (rows 37 to 70) holds the station
identities and every count on record, with the leg notes in rows 72 and 73.

## Sources

Master Evaluation Spreadsheet row 41000076575 (Background Info); Project
Justification Sheet and the 1/29/2016 TEAAS strip analysis (05-08-203
Update.pdf); HNTB compliance memo of June 24, 2024; signal plans 05-1723
sealed 4/17/2019 (flashers) and 2/25/2022 (two-phase signal); NCDOT AADT
stations and 2025 traffic segments (ArcGIS); the TEAAS resource page for the
data month; the Typical Target Crash Types sheet for the target wording.

## For the engineer before the fiche steps

- Construction period: the signal 05-1723 replaced the flashers after the
  project (plan sealed 2/25/2022); its turn-on date is not in the files. The
  assignment comment expects an extended construction period to cover it.
  Confirm the date and, if so, change Set-up D5 and E10; everything else
  follows. The three-month window is the instructions' default and matches
  the let and completion dates on file.
- Map block: the previous project's aerial, location map, leg text boxes
  and station map were removed from the Assumptions and Set-up sheets.
  Compose this project's map block (the Map Block page) with the alt text
  from the Assumptions leg table before the review.
- One Pager I26 (template path) is blank: enter the WO folder path the
  one-pager macro reads the templates from.
- SR 1390 speed limit: 35 mph on the 2022 plan, 45 mph on the 2019 plan; the
  Assumptions carry 35 (minor road speed O7 and the west leg). Check in the
  field.
- Project cost: 665,000 is the Master Evaluation Spreadsheet total cost
  estimate; the TMSD approved total is 861,000.
- Y-line: the realignment moved the SR 1390 tie-in about 190 ft south; the
  target crash guidance says y-lines may need extending for realignments.
- The workbook copy links its drop-down lists (crash types, vehicle codes,
  at fault, One Pager picks) to a file in a Downloads folder and the CRF
  costs to the S: drive CRF sheet; both links are left as they were. Excel
  uses the cached lists when the files are absent.
- The staff email sheet's CRF row (row 3) is cleared: copy the row for this
  countermeasure from the NCDOT CRF sheet. The One Pager Additional
  Information picks (J5:J10) and counts are cleared for after the review.
- Three cells depend on an XLOOKUP (Division): their caches were set to 5
  for Wake. Every other formula LibreOffice cannot compute (XLOOKUP and
  REGEXEXTRACT dependents on the staff email sheet) has no cached value
  until Excel recalculates on open, which it does for every formula.

## reviewed-setup/ (later version, 2026-10-07)

`reviewed-setup/` holds the set-up workbook as it stood after the Excel review of
7 October 2026 (Est flags cleared, notes trimmed, wording edits), with its
`Evaluation-Setup-and-Assumptions_05-08-203_W-5601HP.md` write-up, the station map and
the scripts that patched the workbook XML. It differs from the workbook above on the
construction period: the review carries construction through 10/31/2022 (18 months, to
the certain bound of the 2022 signal turn-on) with equal 3 yr 10 mo before and after
periods, where the workbook above uses the instructions' three-month default. The
write-up records the evidence for each choice; the engineer picks the period.
