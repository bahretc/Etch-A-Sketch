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
