# 12 - HSIP warrants (2024 HSIP Overview, May 2024)

## The three study types

NCDOT crash work splits into **Fatal Crash Analyses**, **HSIP Package
Analyses**, and **Evaluations**. The fiche/crash-analysis core is the same for
all three; the app should ask which one at set-up. Only HSIP packages ask
whether a location *warrants* a project, which is `safety_eval/warrants.py`.

## Section warrants

Two tests in series. First the location has to clear BOTH minimums over the
5-year analysis period:

| Facility Type | Min Total Crashes | Min Crashes/Mile |
|---|---|---|
| All Freeway Sections | 30 | 30 |
| US Non-Freeway Route | 20 | 40 |
| NC Non-Freeway Route | 15 | 30 |
| SR Non-Freeway Route | 12 | 24 |
| City Non-Freeway Street | 20 | 40 |

Then a pattern has to dominate:

| | | threshold |
|---|---|---|
| F-1 | Run Off Road during Wet Road Conditions | 48% |
| F-2 | Run Off Road | 80% |
| F-3 | Wet Road Condition | 55% |
| F-4 | Night Location (dark) | 52% |
| N-1 | Run Off Road during Wet (non-freeway) | 35% |
| N-2 | Run Off Road (non-freeway) | 68% |
| N-3 | Wet Road Condition (non-freeway) | 48% |
| N-4 | Non-Intersection Night Location | 38% |

**ROR is eight crash types**, not six: Run Off Road right, left **and
straight**, Fixed Object, Overturn/Rollover, Sideswipe Opposite Direction,
**Parked Motor Vehicle**, Head On. ROR-T and PMV are the two most easily left
out by eye.

**Animal crashes leave the analysis entirely** - total, rate, and every
percentage. The Overview removes them because deer crashes on rural routes are
not something a countermeasure addresses.

**N-4 is the only warrant whose base is not the total**: it is ROR-in-the-dark
as a share of *non-intersection* crashes.

## Wet and dark, in fiche codes

There is no published C/L table in this pack. Taken from the engineer's own
conditional formatting on the working sheet: **C = 2 is wet** (rule: between
1.1 and 2.9) and **L = 4 or 5 is dark** (rule: between 3.1 and 5.9).

## The working sheet's conditional formatting

Three rules, and they exist to make the warrant inputs visible while reviewing:

- `C` column, `cellIs between 1.1 and 2.9` - wet
- `L` column, `cellIs between 3.1 and 5.9` - dark
- `Type` column, `containsText` for each ROR type

**Extent: row 2 through the last ADD row.** The warrant runs on IS + RE + ADD,
so the highlighting stops there. Running it through the DEL block (or into the
NIS block) highlights crashes that are not in the analysis and is a real source
of miscounting.


## Corrections from the warrants workbook (Fiche_HSIP_Warrants.xlsm)

The workbook is what NCDOT actually runs, and it differs from the Overview's
prose on four counts. The workbook wins.

- **Wet is C in {2, 3}**, not {2}. `COUNTIFS(C,">=2",C,"<=3")`.
- **Dark is L in {4, 5, 6}**, not {4, 5}. `COUNTIFS(L,">=4",L,"<=6")`.
  Both are WIDER than the working sheet's conditional formatting, so a cell
  can be unhighlighted and still count toward a warrant.
- **The minimums are strictly greater than**: `=IF(U6>min,...)`. Exactly 30
  crashes does not clear a minimum of 30. `strict=False` gives the `>=` reading
  the prose suggests.
- **SSSD is OFF by default.** The Overview's ROR list has Sideswipe
  **Opposite** Direction (SSOD), not Sideswipe Same. The workbook adds a row
  `Sideswipe Same* (use SSSD)` with the note `*multi-lane only` **and leaves
  its abbreviation cell AB9 blank**, inside the MATCH range `$AB$2:$AB$10`.
  A blank key matches nothing, so SSSD does not count until an engineer types
  it in. `multilane=True` is that opt-in and nothing else. On study
  41000079305 the difference is F-2 at 82.1% against 89.7%.
- **N-4's base is derived from crash TYPE**, not a flag: total minus Angle,
  LTDR, LTSR, RTDR, RTSR, U-Turn and the Y-line variant.

The workbook's ROR list omits **Overturn/Rollover**, which the Overview does
list. Kept, on the Overview's authority; worth confirming.

## Still to build: intersection warrants

The workbook carries them on sheets IU (urban) and IR (rural), keyed on EPDO
(K/A 76.8, B/C 8.4, PDO 1) and Frontal Impact types (Angle, LTDR, LTSR, RTDR,
RTSR, U-Turn, Head-on). Urban uses a 2-year recency window, rural a 3-year one:

| | urban | rural |
|---|---|---|
| I-1 | %2yr>=25% AND ((FI>=12 AND %FI>=55%) OR (Total>=35 AND %FI>=35% AND FI severity>=6)) | %3yr>=20% AND FI>=9 AND %FI>=60% |
| I-2 | Total>=25 AND %1yr>=38% | Total>=20 AND %1yr>=32% |
| I-3 | Total>=25 AND severity>=6 AND %2yr>=40% | Total>=20 AND severity>=9 AND %3yr>=30% |
| I-3 (both) | K and A frontal-impact crashes in last 5 years >= 3 | same |
| I-4 | %2yr>=25% AND night>=12 AND %night>=40% | %3yr>=20% AND night>=10 AND %night>=46% |

**These are the 2024 warrants. NCDOT has 2026 updates not yet in hand.**

## Shares are rounded to whole percents BEFORE the test

Every share in the workbook is `ROUND(count/total, 2)` and the `>=` comparison
runs on the rounded value: 16/31 = 51.6% rounds to 52% and MEETS a 52%
threshold. This is the test, not presentation, and it decides warrants at the
margin. The thresholds are published as whole percents, so testing at
whole-percent precision is the consistent reading. `WarrantResult.share` is
the tested (rounded) value; `exact_share` keeps the unrounded one for anyone
who wants to see the margin.

## Values still awaiting a source

| constant | value | status |
|---|---|---|
| every warrant threshold | 2024 Overview | swap when the 2026 values arrive |
| `MIN_SECTION_MI` | 0.10 mi | **placeholder, engineer's call.** Not from any NCDOT document. It exists to stop `scan_sections` returning a degenerate answer: ten crashes in 0.02 mi is 500 per mile and clears every rate minimum, which is arithmetic rather than engineering. Replace if NCDOT publishes a minimum section length. |
| `strict` (minimums are `>`, not `>=`) | True | from the workbook; the Overview's prose reads as `>=` |
| ROR includes Overturn/Rollover | yes | Overview lists it, the workbook omits it |
