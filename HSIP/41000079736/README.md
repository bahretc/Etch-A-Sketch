# HSIP Fiche Review - TEAAS Study 41000079736

**Location:** NC 180/NC 226 (Post Rd) at SR 1103 (Pleasant Dr / Pleasant Hill Church Rd), Cleveland County, Division 12
**Intersection:** 35.246324, -81.509409 (NC 180 MP 4.601; SR 1103 MP 3.644, per the Features Reports)
**Study period:** 9/1/2021 - 8/31/2026 (5.00 yr), Y-line 150 ft, ADT 15,200

The Intersection Analysis Report (initial study) captured **23 crashes** inside the 150 ft Y-line.
The fiche pulled **1,783 crashes** on the fiche roads for the same period. This folder screens the
fiche for crashes that may belong at the intersection but fell outside the Y-line or were mis-referenced.

## Result: 14 crash IDs to review

Tier 1 - within ~350 ft by cleaned geocode or by milepost (likely intersection-related):

| Crash ID | Date | Sev | Type | Why |
|---|---|---|---|---|
| 107960640 | 2024-12-15 | PDO | Left turn, diff. roadways | Geocoded 170 ft away. Coded "SR 1103 at SR 1103", no milepost - probably NC 180 at SR 1103 |
| 108465156 | 2026-04-07 | PDO | Left turn, same roadway | Geocoded 262 ft away; "NC 180 0.1 mi N of SR 1103" |
| 107608647 | 2024-01-30 | PDO | Animal | Geocoded 288 ft away; "NC 226 0.052 mi N of SR 1103" (MP 4.653) |
| 108314990 | 2025-11-19 | PDO | Backing up | SR 1103 MP 3.578, 348 ft east; coordinates (3 decimals) disagree, trust the DMV-349 |
| 107967581 | 2024-12-09 | PDO | Sideswipe, opp. dir. | NC 180 MP 4.557, 232 ft south; raw 2-decimal coordinates disagree |
| 108561772 | 2026-07-16 | PDO | Fixed object | NC 180 MP 4.584, 90 ft south; raw 2-decimal coordinates disagree |

Tier 2 - referenced about 0.1 mi (~530 ft) from the intersection, outside the Y-line; judge from the narrative:

| Crash ID | Date | Sev | Type | Why |
|---|---|---|---|---|
| 107563341 | 2023-12-13 | PDO | Animal | Geocoded 528 ft away, NC 180 0.2 mi NE of SR 1103 |
| 107786994 | 2024-07-15 | PDO | Sideswipe, same dir. | NC 180 0.1 mi S of SR 1103 (MP 4.501) |
| 106781021 | 2021-11-25 | PDO | Animal | NC 180 0.1 mi S of SR 1103 (MP 4.501) |
| 107363522 | 2023-06-07 | B inj | Rear end, slow/stop | NC 180 0.1 mi N of SR 1103 (MP 4.701) |
| 107101290 | 2022-10-05 | PDO | Animal | NC 180 0.2 mi S of SR 2329 (MP 4.704) |
| 107921837 | 2024-11-12 | PDO | Sideswipe, opp. dir. | SR 1103 0.1 mi W of NC 180 (MP 3.744) |
| 107110946 | 2022-10-11 | PDO | Sideswipe, opp. dir. | SR 1103 0.1 mi W of NC 180 (MP 3.744) |
| 106966564 | 2022-05-23 | C inj | Fixed object | SR 1103 0.1 mi E of NC 180 (MP 3.544) |

All IDs: `107960640, 108465156, 107608647, 108314990, 107967581, 108561772, 107563341, 107786994, 106781021, 107363522, 107101290, 107921837, 107110946, 106966564`

## Crash analysis (22 crashes) and HSIP warrant check

`data/41000079736_CrashAnalysis.pdf` is the TEAAS analysis after the fiche review (crashes 106808749 and 107960640
added; 108204170, 107468199 and 107921860 excluded). Against the NCDOT HSIP intersection warrants (2024 and 2026):

| Warrant | Threshold | This study | Result |
|---|---|---|---|
| **I-1u Frontal Impact Urban, 5 yr** | 25% of crashes in last 2 yr; and 12+ frontal impact crashes with 60% (2026) / 55% (2024) frontal share | 10 of 22 (45%) in 9/2024-8/2026; 16 frontal (73%) | **MET** |
| I-2u Last Year Increase Urban | 25+ crashes, 40% in last year | 22 crashes | not met |
| I-3u Frequency with Severity Index Urban | 25+ crashes, SI 6.5, 40% in last 2 yr | 22 crashes (SI 9.57) | not met |
| I-3 Fatal and Severe Injury | 3+ K or A frontal impact crashes | 2 (both A, both frontal) | not met |
| I-4u Night Location Urban | 12+ night crashes and 45% | 6 (27%) | not met |

TEAAS lists the location as rural. On this 5-yr data the rural 10-yr warrants I-1r (9+ frontal, 60%, 20% in last 3 yr)
and I-3r (20+ crashes, SI 9.0, 30% in last 3 yr) are also satisfied; a rural submission would use a 10-yr study.

### 10-year rural study (9/1/2016 - 8/31/2026, 29 crashes)

`data/41000079736_CrashAnalysis10yr.pdf` with the reviewed fiche workbooks `data/41000079736_FicheFirst5.xlsx`
(2016-2021) and `data/41000079736_Fiche.xlsx` (2021-2026). `warrants.py` checks the rural warrants three ways
(output in `review/warrant_check_10yr.txt`):

| Scenario | Crashes | Frontal | SI | I-1r | I-2r | I-3r | I-3 | I-4r |
|---|---|---|---|---|---|---|---|---|
| A. As submitted | 29 | 22 (76%) | 8.01 | **MET** | no (21% last yr) | no (SI < 9.0) | no (2 K/A) | no (9 night, 31%) |
| B. All 7 deleted crashes added back | 36 | 23 (64%) | 6.65 | **MET** | no | no | no | no (15 night, 42%) |
| C. Only deleted fixed-object crashes added back (no rear ends were deleted) | 31 | 22 (71%) | 7.56 | **MET** | no | no | no | no (11 night, 35%) |
| D. Deleted non-frontal crashes added back (3 animal, 2 fixed object, 1 sideswipe) | 35 | 22 (63%) | 6.81 | **MET** | no | no | no | no (14 night, 40%) |

All seven deleted crashes are PDO (3 animal, 2 fixed object, 1 sideswipe, 1 left turn), so adding any of them back
only lowers the severity index and the frontal share; I-1r holds in every case.

## AADT

Intersection entering AADT = (sum of the AADT on every leg) / 2, using each NCDOT Traffic Survey Group station's count
for the **middle year of the study period** (10-yr study 9/1/2016-8/31/2026 -> 2021). A leg with no count for that
year gets a straight-line estimate between its nearest earlier and later counts, rounded as NCDOT publishes, and is
labelled "(estimate)" on the collision diagram. Station histories are in `aadt.json`; the calculation, with live
formulas, is `41000079736_AADT.xlsx` (sheet "10-yr study"; "5-yr study" is a check; "Stations" holds the counts).

| Leg | Station | 2021 AADT | Basis |
|---|---|---|---|
| NC 180/NC 226 (S Post Rd) north | 0230000187 | 11,000 | count |
| NC 180/NC 226 (S Post Rd) south | 0230000152 | 10,500 | count |
| SR 1103 (Pleasant Dr) northwest | 0230000045 | 1,400 | estimate (2018: 1,600, 2022: 1,300 -> 1,375 -> 1,400) |
| SR 1103 (Pleasant Hill Church Rd) southeast | 0230000531 | 1,200 | count |

Sum 24,100 / 2 = **12,050 vpd entering**; 10-yr exposure 12,050 x 365 x 10 / 1,000,000 = **43.98 MEV**;
29 crashes / 43.98 = 0.66 crashes per MEV. The 5-yr check (middle year 2024) gives 12,100 vpd and 22.08 MEV.
The earlier mean-of-counts figures (11,600 latest; 12,000 5-yr; 12,300 10-yr) are superseded and kept only in
`maps/aadt_calculation.txt` for the record.

`41000079736_CalculatedAADT.xls` / `.xlsx` (`make_calculated_aadt.py`) is the package "CalculatedAADT" template
(4-LEG INTERSECTION ADT sheet, copied from the 41000077748 package) filled with the four 2021 leg ADTs: total ADT
12,050 against the 12,300 "Annual ADT" on the TEAAS 10-yr report is a 2.0 % difference, so the template's rule
("keep ADT used in the study" unless the difference exceeds 5 %) keeps 12,300 as the study ADT.

## Maps (`maps/`)

Package-format maps (`make_vhb_maps.py`), laid out like the Location Map / Area Map PDFs in the Training/Checking
packages (41000077748, 41000077751): letter landscape, NC county inset with Cleveland County in red, north arrow and
scale box, red ring at the study intersection, footer with WO Number, PH Number, NCDOT Division, Study Area, Lat/Long
the data-source line and the VHB logo (taken from the package maps, `data/vhb_logo.png`).

1. `41000079736_LocationMap.pdf` / `.png` - county-scale street map in grey (OpenStreetMap)
2. `41000079736_AreaMap.pdf` / `.png` - aerial (Esri World Imagery) with the crash-location callout, NC 180/NC 226
   shields and street names
3. `41000079736_ADTMap.pdf` / `.png` - ADT map in the format of the package `_ADTMap.pdf` files: the NCDOT AADT Mapping
   Application view (Esri topographic basemap, every station in view as a dot coloured by route class with the
   application's legend), a popup for each of the four study stations listing LocationID, COUNTY, RTE_CLS, ROUTE,
   LOCATION and AADT_2002 to AADT_2025 with the year used (2021) boxed in red (the SR 1103 Pleasant Dr station has the
   2018 and 2022 counts boxed and an "Estimated 2021 AADT: 1,400 vpd" callout), the "Crash Location" callout and red
   ring. Station records come from the NCDOT Traffic Survey Group station services (`fetch_ncdot_stations.py`,
   cached in `data/ncdot_aadt_stations.json`).

The footer of every package map shows "Lat, Long" with the coordinates on one line (one-step copy).

Working maps (`make_maps.py`): `1_location_map.png`, `2_area_map.png` (150 ft Y-line and the AADT stations),
`6_aadt_map.png` (stations with the 2021 AADT and the entering-AADT calculation) and `41000079736_maps.pdf`.
`3_collision_diagram.png` and `4_crash_location_map.png` are earlier drafts kept for reference.

## Intersection collision diagram (`maps/5_collision_diagram_NCDOT.pdf` / `.png`)

`collision_diagram.py` draws the 29-crash, 10-year diagram from the TEAAS collision diagram export
(`data/41000079736_CollisionDiagramData.csv`, parsed to `data/collision_diagram_crashes.json`) in the NCDOT Traffic
Safety Unit style used in the Training/Checking example packages and the TSU "Collision Diagrams" instructions:

- 17 x 11 in sheet, legend top right, NCDOT/TSU title block bottom right, PH#/Order#/County/location/period text, north needle.
- Base map traced at the true 49-degree skew (NC 180/NC 226 bearing 22 deg, SR 1103 bearing 333/153 deg), STOP bars and
  octagons on the SR 1103 approaches, leg labels with AADT and posted speed.
- Each crash: numbered circle (TEAAS report order, by date) at the tail of the at-fault vehicle's path, magenta asterisk
  (driver at fault = unit with a contributing circumstance, unit 1 if several), green D/W/I/O road-surface letter, blue
  dots = impact speed in tens (SPD_AT_IMPCT_NBR; estimated speed only when impact is blank), hollow arrowhead = day/dusk/dawn,
  filled = dark, red circle at the impact point for injury crashes (hollow B/C, half-filled A, filled K), red number
  circle = target (frontal impact) crash. Rear ends show the bar at the rear of the stopped vehicle; fixed-object crashes
  use the ran-off-road zigzag with a note of the object struck; crashes with identical details are stacked on one glyph.
- Glyphs sit beside the approach the at-fault vehicle came from (single-vehicle run-off-road crashes referenced past the
  intersection sit on the departure leg), stacked back from the intersection in columns off the pavement
  (`review/collision_diagram_placement.txt` lists the assignment and a clearance check). Short notes beside a glyph are
  placed automatically where they touch nothing; the full wording is in the sheet notes box.
- Page 2 of the PDF is the crash listing (number, ID, date, type, severity, light, road, units) that the numbers refer to;
  the same table is `review/collision_diagram_listing.csv`. `review/collision_diagram_spec.md` records the symbology
  taken from the example packages.

Fill in `PH_NO` and `PREPARED_BY` at the top of the script before issuing. The posted speed on SR 1103 (shown as 45 mph)
should be confirmed against the field review.

### MicroStation sheet, enlarged (`maps/41000079736_CollisionDiagram_labeled.pdf`)

`relabel_collision_diagram.py` takes the MicroStation collision diagram as exported with the author's leg labels
(`data/41000079736_CollisionDiagram_VHB.pdf`: route, street, `AADT (Year)` for the middle study year 2021 - 11,000 /
10,500 / 1,400 (2021 Estimate) / 1,200 - and posted speed), keeps the border, title text, legend and title block
exactly where they were, enlarges the drawing (roads, crashes, insets A and B, STOP signs) uniformly by 1.20 and
centres it between the border lines. The original page is embedded as a form XObject and drawn under clips, so no
line or crash symbol is redrawn. The four leg labels and the four land-use labels are drawn at their original size,
each moved to a spot beside the enlarged roads. Requires `pikepdf`.

## Fiche setup finding

The NC 180 Features Report names the side street at MP 4.601 **PLEASANT HILL, road code 50024407**.
The fiche was run with PLEASANT (50024421) and PLEASANT HILL CHURCH (50038004) but **not 50024407**.
Any crash coded only to that street name would be missing from both the initial study and this fiche.
Re-run the fiche in TEAAS with 50024407 added, then re-run `fiche_review.py`.

Other checks that came back clean:

- The Fiche Report (`41000079736_Fiche.csv`) and the Detailed Fiche export contain the same 1,783 crash IDs.
- All 23 initial-study crashes are present in the fiche.
- Intersection mileposts derived from the initial-study crashes (NC 180 4.601, SR 1103 3.644) match the Features Reports.
- NC 226 is concurrent with NC 180 from NC 180 MP 3.558 to 5.130; crashes mileposted on NC 226's own
  inventory near MP 4.6 are 2+ miles south and were correctly excluded. No NC 226-mileposted crash
  falls near the intersection's NC 226 milepost (~7.1-7.2).
- Driveway (PVA ... S POST RD) crashes: the closest geocoded one is 876 ft away; none are candidates.

## Files

```
data/      raw inputs as exported from TEAAS (fiche report, detailed fiche + parameters,
           initial study report + ID list, Features Reports for NC 180 and SR 1103,
           final 22-crash analysis PDF and its parsed CSV, 10-yr analysis, collision diagram export,
           41000079736_CollisionDiagram_VHB.pdf = the MicroStation sheet as exported, the author's own layout,
           both TEAAS fiche workbooks, CalculatedAADT_template_41000077748.xls from the package examples)
maps/      location map, area map, collision diagram, crash location map, combined PDF,
           5_collision_diagram_NCDOT.pdf/.png (TSU-style sheet + listing), 5b_collision_diagram_listing.png
aadt.json  NCDOT AADT station values used for the entering-volume calculation
41000079736_AADT.xlsx   AADT workbook: station counts, middle-year AADT per leg (count or estimate), entering AADT, MEV, crash rate
make_aadt_workbook.py   builds the workbook (openpyxl); recalculate after editing inputs
review/    review_ids.txt            the list above, plain text
           review_candidates.csv     candidates with reasons, tier, coordinates
           fiche_screened.csv        all 1,783 fiche crashes with distance, MP offset, initial-study flag
           41000079736_FicheReview.xlsx   workbook: Summary, Review List, Initial Study (23), Fiche (all)
           collision_diagram_spec.md / _placement.txt / _listing.csv   collision diagram symbology, layout QA, listing
41000079736_Fiche10yr.xlsx   both TEAAS fiche workbooks (9/2016-8/2021 and 9/2021-8/2026) combined: 3,423 crashes,
           in-study rows first (27 IS, 2 ADD, 7 DEL), ID and Index sheets merged (make_fiche10yr.py)
41000079736_CalculatedAADT.xls/.xlsx   package AADT template filled for this study (make_calculated_aadt.py)
fiche_review.py   reproducible screen (python3, openpyxl optional for the workbook)
make_vhb_maps.py  package-format Location Map and Area Map
make_maps.py      builds the maps (python3, matplotlib, pillow; fetches basemap tiles)
collision_diagram.py   NCDOT TSU-style collision diagram from the unit-level export
relabel_collision_diagram.py   enlarges and centres the MicroStation sheet, re-places its labels (pikepdf)
```

## Method

For every fiche crash not in the initial study, three signals are tested:

1. Haversine distance from the intersection coordinates (threshold 600 ft).
2. Milepost offset on NC 180 / SR 1103 from the intersection milepost (threshold 600 ft).
3. Narrative referencing: on a mainline route within 0.12 mi of a side-street reference, or vice versa.

Tier 1 = within 350 ft by cleaned geocode (3+ decimals) or by milepost. Raw DMV-349 coordinates rounded
to 2 decimals (~3,500 ft) are noted but not used to exclude a crash whose milepost and narrative agree.
Crash type codes 17-30 were verified against the Initial Study report; the rest follow the DMV-349 list.

Run: `python3 fiche_review.py`
