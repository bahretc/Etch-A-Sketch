# Evaluation Set-up and Assumptions — 05-08-203 (TIP W-5601HP)

**Location:** SR 1375 (Lake Wheeler Road) at SR 1390 (Optimist Farm Road)/SR 1503 (Donnybrook Road), unincorporated Wake County near Fuquay-Varina (NCDOT Division 5). GPS 35.657816, -78.717261.
**Countermeasure:** Realign SR 1390 and SR 1503 to tie directly across from one another and install shoulder-mounted actuated ("Vehicle Entering When Flashing") flashers in both directions on SR 1375. The flashers were replaced by a 2-phase fully actuated traffic signal (05-1723) in 2022.
**Evaluation order:** 41000076575 (assignment #40, VHB, 2026 cycle). **Signal ID:** 05-1723.

The companion workbook `Accessible Intersection Evaluation Workbook - 05-08-203 (W-5601HP).xlsm` has the **Evaluation Set-up** and **Assumptions** tabs completed for this location (values, formulas, notes, station map and the Nearmap aerial/location map with alt text). The downstream tabs (Fiche Prep Tool, Initial Crash ID list, Parameters, Original/Filtered Fiche, Binned Crashes, Before, After, Trends, One Pager, NCDOT staff tabs) still hold the prior Moore County example and must be replaced after the TEAAS fiche is pulled. The workbook is set to recalculate fully when opened in Excel.

## Study periods (Evaluation Set-up tab)

| Period | Start | End | Length |
|---|---|---|---|
| Before (unequal, B14 checked, start in D14) | 1/1/2018 | 4/30/2021 | 3 yr 4 mo |
| Construction (D5 = 20 months, E10 = 12/31/2022) | 5/1/2021 | 12/31/2022 | 1 yr 8 mo |
| After | 1/1/2023 | 8/31/2026 | 3 yr 8 mo |

- Most recent TEAAS date (D4) assumed **8/31/2026** (same as the other 2026-cycle workbooks); update if newer crash data is available.
- Realignment and flashers: CON start 5/24/2021 and completion 7/2/2021 per the NCDOT tracking database (the HNTB compliance memo lists 7/2/2021 as both begin and completion), built under the R-2721A Complete 540 contract; RTE notified 9/16/2021; HNTB compliance review 6/7/2024 (substantial compliance). Because the 540 contractor was active beside the site from 2019, it is worth checking dated aerials (Google Earth history / Nearmap, 2020 to mid-2021) for any earlier grading of the SR 1390 relocation; if work is visible before May 2021, increase D5 so the construction start (D10) and before-period end (E9) move back accordingly.
- The **2022 signal** (05-1723 Sig. 1, plan sealed 2/25/2022, "remove existing VEHICLE ENTERING WHEN FLASHING signs and flashing beacons") is treated as part of an extended construction period, per the TSU assignment note ("Signal installed later, in 2022, so likely an extended construction period is necessary"). The exact turn-on date is not in the project files, so the construction period is carried through 12/31/2022. If the turn-on month is confirmed (Division 5 signal records, Street View imagery, or the first after-period crash reports coded "stop and go signal"), set E10 to the end of that month **and** D5 to the number of months from May 2021 through that month (June 2022 = 14) so that D10 stays 5/1/2021. The One Pager discussion must state that the after condition is the realigned, signalized intersection, because the One Pager shows the 7/2/2021 completion date next to a construction period ending 12/31/2022.
- The **before period starts 1/1/2018** (unequal time period) because the prior sight-distance project W-5205W / 05-13-6035 at this location was completed in 2017 (month not given in the files) and was never evaluated; the report should mention it. If W-5205W is confirmed complete by 8/31/2017, uncheck B14 to use equal 44-month periods (before = 9/1/2017-4/30/2021).
- Representative AADT years: **2021** (before; the last year in the before period with published counts, following the tool's instruction; 2020 excluded per the COVID guidance; the 2021 counts may have been taken during the 2021 construction) and **2025** (after). Representative intersection volumes: 11,700 vpd (2021) and 11,800 vpd (2025).

## Traffic volumes (AADT calculator)

Source: NCDOT 2025 AADT Stations / Traffic Segments (Traffic Survey Group). Counts are taken in odd years; even years are interpolated (red), 2020 = 0.85 x interpolated (COVID), 2026 = 2025 value carried forward.

| Leg | Road | Station | Location | 2017 | 2019 | 2021 | 2023 | 2025 |
|---|---|---|---|---|---|---|---|---|
| 1 (North) | SR 1375 Lake Wheeler Rd | 0920000868 | north of SR 1390 | 7,300 | 8,200 | 8,400 | 7,800 | 8,900 |
| 2 (South) | SR 1375 Lake Wheeler Rd | 0920000991 | south of SR 1503 | 5,100 | 6,100 | 6,100 | 6,000 | 7,400 |
| 3 (West) | SR 1390 Optimist Farm Rd | 0920001913 | west of SR 1404 Johnson Pond Rd (~1 mi west) | 5,400 | 5,500 | 5,600 | 4,800 | 4,800 |
| 4 (East) | SR 1503 Donny Brook Rd | 0920001914 | east of SR 1392 Ransdell Rd (~0.15 mi east) | 3,600 | 3,700 | 3,300 | 2,000 | 2,400 |

Notes: both minor-leg stations are off the intersection. The Leg 3 station is about 1 mi west, beyond SR 1404 (Johnson Pond Rd, 4,600 vpd), and the Leg 4 station is east of SR 1392 (Ransdell Rd, 2,300 vpd in 2025), so the Donnybrook leg at SR 1375 probably carries more than the station value (TSU inventory probe estimate about 4,200 vpd in 2021, about 1.28 x the station count). Both minor-leg series are used unadjusted and flagged "(est)" in the leg table, map labels and alt text (counted years stay in black; only interpolated years are red); the same stations serve both periods, so the before/after exposure ratio is unaffected. A probe-based SR 1503 series would raise the representative intersection volumes to roughly 12,100-12,300 vpd. The 2013 counts on SR 1375 (9,400 / 9,500) are an outlier outside the study period. Project-development ADT was 6,500 (2010) with 9,000 total entering vehicles per day.

## Assumptions tab

- **Project ID** 05-08-203 (TIP #W-5601HP); **countermeasure** kept to the database wording (realignment plus VEWF flashers), with the 2022 signal recorded as a confounder in the notes rather than as part of the evaluated countermeasure; **CMF group** Intersection Realignment; **estimated cost** $665,000 (project justification sheet; TMSD-approved total $861,000); **completion date** 7/2/2021 (database date; see the signal note above).
- **Y-line 350 ft** from the signalized intersection (SR 1375 MP 4.70): about 200 ft offset to the former SR 1390 junction (MP 4.66) plus the standard 150 ft, following the "Y-lines may need to be extended / analyze the entire area impacted by the realignment" guidance; it also covers the +/- 325 ft VEWF sign locations. Rear-end crashes on the north approach between the curve and the Y-line (about MP 4.56-4.63, the project-development strip) fall outside the Y-line and should be reviewed for the additional-information table. Suggested TEAAS pull: SR 1375 (40001375) from about MP 4.55 to 4.85 plus SR 1390, SR 1503, SR 1392 and the local route IDs 50078941092 (the realigned SR 1390 approach in the TSU intersection inventory) and 50016885 (LAKE WHEELER), then bin by distance with the Fiche Prep Tool; confirm in TEAAS whether the SR 1390 feature on SR 1375 was moved from MP 4.66 to 4.70. The tracking row cites TEAAS study 41000030524 while the project package contains strip analysis 41000039223 (1/29/2016).
- **Target 1:** frontal impact crashes in the intersection. **Target 2:** rear end crashes on SR 1375 approaching the intersection. Use the 2-target One Pager (unequal time periods).
- **Statement of problem** (from the project justification sheet): limited sight distance on SR 1375 and the offset condition of SR 1390 with SR 1503 contributing to angle and rear-end crashes; 35 crashes 1/1/2011-12/31/2015 (0 K, 0 A, 2 B, 7 C, 26 PDO), 14 correctable.
- **Speed limits:** SR 1375 45 mph posted (both signal plans; crash reports list 45 mph; NCDOT speed-limit GIS layer shows 55 mph statutory); SR 1390 35 mph (2022 plan and GIS; 45 mph on the 2019 plan); SR 1503 45 mph (both plans and TSU inventory; GIS layer shows 35 mph). The single "Minor" speed cell (O7) is 35 mph for SR 1390, the realigned leg. Verify postings in the field or Street View.
- **Confounders:** Complete 540 (NC 540, R-2721A/B) was under construction beside the site from 2019 (NCDOT Complete 540 project page; the realignment itself was built under the R-2721A contract) and opened 9/24/2024 (NCDOT news release), crossing SR 1375 about 0.3 mi north with no interchange there. NCDOT HL-0008Q (signal and turn lanes at SR 1390/SR 1386 Bells Lake Rd, west of the site; contract DE00396) was in the 4/8/2026 Division 5 letting and will affect SR 1390 traffic after the study period.
- **Map/satellite views:** the supplied Nearmap aerial (2/13/2026) and location map are embedded with alt text; the leg labels read SR 1375 45 mph 8,900 / 7,400, SR 1390 35 mph 4,800 (est), SR 1503 45 mph 2,400 (est), all 2025 AADT. The Evaluation Set-up tab carries a station map (`aadt_station_map_05-08-203.png`) drawn from the NCDOT 2025 traffic segments.

## Still to do by the analyst

1. Confirm the 2022 signal turn-on month and adjust E10 and D5 if needed; check dated aerials for grading before May 2021.
2. Confirm the W-5205W completion month (equal periods become possible if it finished by August 2017).
3. Pull the TEAAS detailed fiche and Initial Crash ID list for 1/1/2018-8/31/2026 using the Y-line above; paste into Original Fiche / Initial Crash ID list / Parameters and run the Fiche Prep macro.
4. Replace the Moore County data in Before/After/Trends/One Pager (set the One Pager to 2 targets and unequal time periods, state the signal replacement in the discussion) and the CRF row on the staff email tab.
5. Confirm the posted speed limits and the TEAAS data date.

## Sources used

Project files in the shared Drive folder (project justification sheet, B/C worksheet, funding estimate, 2016 roadway plan, TEAAS strip study 41000039223, HNTB compliance memo of 6/24/2024, signal plans 05-1723 dated 4/17/2019 and 2/25/2022, Master Evaluation Spreadsheet row), NCDOT GIS services (2025 AADT stations and traffic segments, TSU intersection inventory, traffic signal inventory, speed-limit layer), NCDOT Complete 540 news releases. The `scripts/` folder holds the Python used to patch the workbook XML (preserving the VBA project, checkbox cells and data validations) and to draw the station map.
