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

Intersection entering AADT = (sum of the AADT on every leg) / 2, NCDOT Traffic Survey Group stations (`aadt.json`):

| Leg | Station | Latest AADT |
|---|---|---|
| NC 180/NC 226 (S Post Rd) north leg | 0230000187 | 10,500 (2025) |
| NC 180/NC 226 (S Post Rd) south leg | 0230000152 | 10,000 (2025) |
| SR 1103 (Pleasant Dr) northwest leg | 0230000045 | 1,500 (2024) |
| SR 1103 (Pleasant Hill Church Rd) southeast leg | 0230000531 | 1,200 (2025) |

Sum 23,200 / 2 = **11,600 vpd entering** on the latest counts. For a study-period average (mean of each station's
published counts over the study years, then sum / 2; full histories and the calculation are in `aadt.json` and
`maps/aadt_calculation.txt`):

| Study period | Entering AADT | Exposure |
|---|---|---|
| Latest count per leg | 11,600 vpd | |
| 5-yr study, 9/2021-8/2026 mean (2021-2025 counts) | 12,000 vpd | 21.9 MEV |
| **10-yr study, 9/2016-8/2026 mean (2016-2025 counts)** | **12,300 vpd** | **44.9 MEV** |

The TEAAS analysis was run with ADT 15,200, which no nearby station supports.

## Maps (`maps/`, built by `make_maps.py`)

1. `1_location_map.png` - county-scale location map (OpenStreetMap)
2. `2_area_map.png` - aerial area map with the 150 ft Y-line, route labels and the four AADT stations
3. `3_collision_diagram.png` - schematic collision diagram of the 22 crashes with crash table
4. `4_crash_location_map.png` - aerial close-up with the 12 geocoded crashes plotted by severity
5. `41000079736_maps.pdf` - all four as one PDF

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
and the station-year AADT values on the leg labels should be confirmed against the field review.

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
           final 22-crash analysis PDF and its parsed CSV)
maps/      location map, area map, collision diagram, crash location map, combined PDF,
           5_collision_diagram_NCDOT.pdf/.png (TSU-style sheet + listing), 5b_collision_diagram_listing.png
aadt.json  NCDOT AADT station values used for the entering-volume calculation
review/    review_ids.txt            the list above, plain text
           review_candidates.csv     candidates with reasons, tier, coordinates
           fiche_screened.csv        all 1,783 fiche crashes with distance, MP offset, initial-study flag
           41000079736_FicheReview.xlsx   workbook: Summary, Review List, Initial Study (23), Fiche (all)
           collision_diagram_spec.md / _placement.txt / _listing.csv   collision diagram symbology, layout QA, listing
fiche_review.py   reproducible screen (python3, openpyxl optional for the workbook)
make_maps.py      builds the maps (python3, matplotlib, pillow; fetches basemap tiles)
collision_diagram.py   NCDOT TSU-style collision diagram from the unit-level export
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
