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
           initial study report + ID list, Features Reports for NC 180 and SR 1103)
review/    review_ids.txt            the list above, plain text
           review_candidates.csv     candidates with reasons, tier, coordinates
           fiche_screened.csv        all 1,783 fiche crashes with distance, MP offset, initial-study flag
           41000079736_FicheReview.xlsx   workbook: Summary, Review List, Initial Study (23), Fiche (all)
fiche_review.py   reproducible screen (python3, openpyxl optional for the workbook)
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
