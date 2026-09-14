# 01 - Domain Context

## The program

NCDOT's Highway Safety Improvement Program (HSIP) funds safety countermeasures at high-crash locations. The Safety Evaluation Group evaluates completed projects with before/after crash analyses. VHB performs these evaluations under contract, along with fatal-crash field investigations and supporting crash studies.

## Data sources

- **TEAAS** (Traffic Engineering Accident Analysis System): NCDOT's crash database and analysis system. Produces intersection and strip study reports, crash ID lists, and detailed crash exports. The "TEAAS date" on an evaluation is the data currency date of the pull.
- **Fiche**: the crash listing pulled from TEAAS for a study location and date range. Lives in a fiche workbook where each crash gets an IS/NIS/ADD/? status (see docs/03).
- **DMV-349**: the NC crash report form. Scanned reports (TIFF or PDF binders, sometimes 700+ pages) are the ground truth for crash location, narrative, and diagram when the coded fiche data is ambiguous.
- **Master Evaluation Spreadsheet**: one row per assignment (Order ID, Project ID, location, GPS, county/division, countermeasure, cost, completion date). Source of record for evaluation setup and assumptions emails. Read with openpyxl data_only=True.
- **AADT**: from NCDOT count stations and TEAAS AADT chapters; interpolated/estimated where stations are missing. Side road estimates round to the nearest hundred.

## Study and deliverable types

1. **Intersection Evaluation Workbook** (before/after, one intersection). Project IDs like SS-6002AS, SS-6006AP, SS-6009U, SS-6010O, SS-6202A. File naming: `Intersection_Evaluation_Workbook_-_{order-id}__{project-id}_.xlsx` where order id looks like 02-20-62355.
2. **Section Evaluation Workbook** (before/after, a corridor section or non-contiguous sections). Examples: SS-6002M (US 13, Greene County, sinusoidal rumble strips + resurfacing, two non-contiguous sections), W-5206AA, SS-4913CX (.xlsm).
3. **Field Investigation File** (fatal crash slips): three working sheets (Checklist, Sketch, Photos) plus MUTCD reference sheets. Slip numbers like 260123049AA, M260119001.
4. **Crash studies / TEAAS-style analyses**: intersection and strip studies with EPDO, rates, warrant screening, sometimes delivered as PPTX (example: NC 41/NC 72 Lumberton corridor, 310 crashes, 2.056 mi).
5. **Assumptions emails**: short emails to NCDOT documenting evaluation setup decisions (periods, target definitions, AADT assumptions) before the analysis is finalized.

## Countermeasure types seen in evaluations

- AWSC conversion (TWSC to all-way stop): dual-indicated R1-1 with R1-3P plaques and flashing beacons, stop bars, W3-1a Stop Ahead with beacons, overhead flasher converted yellow to red, left-turn lane removal on the former free approaches.
- VEWF (vehicle-entering-when-flashing warning systems).
- Sinusoidal rumble strips + resurfacing (section projects).
- Signals, turn lanes, curve treatments (chevrons, brightstrips/BrightSider retroreflective strips), median treatments.

Known AWSC trade-off used in interpretation: frequency (especially rear-ends on former through approaches) often rises while severity falls. Overhead flasher literature: yellow/red at TWSC is the confusion-prone configuration; all-red at AWSC has favorable evidence (Srinivasan et al. 2008, Pant et al. 1992).

## Terminology

- Severity classes: K (fatal), A, B, C (injury), PDO/O (property damage only).
- Crash type abbreviations: LTSR, LTDR (left turn same road / different roads), RTSR, SSSD (sideswipe same direction), ROR (ran off road, left/right), RE (rear end), angle, head-on.
- Coded fields on fiche rows: T (crash type code), C, F, L, S (severity) numeric codes.
- IS / NIS / ADD / ?: in-study, not-in-study, add-to-study, unresolved (see docs/03).
- Target crash: the crash type(s) the countermeasure is expected to affect; defined per evaluation.
- VRU: vulnerable road users. MEV: million entering vehicles (intersection rates). 100 MVM: hundred million vehicle miles (strip/section rates).
- Slip number: fatal crash assignment identifier.
- Milepost (MP): linear reference along a route; strip/section crash identification is MP-range based.
