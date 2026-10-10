# 12 - HSIP warrants (2026 HSIP Warrants, March 2026)

The thresholds in this file and in `safety_eval/warrants.py` are NCDOT's
**2026 HSIP Warrants** (Traffic Safety Systems Section, March 2026;
`connect.ncdot.gov/resources/safety/HSIP Library/2026 HSIP-Warrants.pdf`),
the edition the app runs. The **2024 HSIP Overview** (May 2024) stays
reachable as edition `2024` (`warrants --edition 2024` on the CLI, the
Edition picker on the HSIP Warrants page) so a study screened under it can
be reproduced; the two editions differ in four urban intersection thresholds
and nothing else (the table "What changed from 2024" below). The 2026 text
runs its 5-year warrants on crashes from 2021 through 2025 and its 10-year
warrants on 2016 through 2025. Every screen, the Warrant sheet summary and
the report text name the edition they ran.

## The three study types

NCDOT crash work splits into **Fatal Crash Analyses**, **HSIP Package
Analyses**, and **Evaluations**. The fiche/crash-analysis core is the same for
all three; the app asks which one at set-up. Only HSIP packages ask
whether a location *warrants* a project, which is `safety_eval/warrants.py`.

Each study also has an **analysis**, asked at the same time and carried on
the study's manifest beside its type (`safety_eval/study_type.py`,
`ANALYSES`): a Fatal Crash Analysis or an Evaluation looks at an
**intersection** or a **section**; an HSIP Package Analysis looks at an
intersection, a section, or a **bike/ped intersection** (below). The pages
that ask section-or-intersection (the warrant screen, the package maps'
site, the review queue's status vocabulary, the Evaluation Workbook
template, the collision diagram sheet) start from that answer. Older study
folders that carry no analysis read as their package-maps site, else the
type's default, and record the first pick.

## Section warrants

Unchanged from 2024 to 2026. Two tests in series. First the location has to
clear BOTH minimums over the 5-year analysis period:

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
out by eye. The 2026 text lists the same six families as the 2024 Overview.

**Animal crashes leave the analysis entirely** - total, rate, and every
percentage. The text removes them because deer crashes on rural routes are
not something a countermeasure addresses.

**N-4 is the only warrant whose base is not the total**: it is ROR-in-the-dark
as a share of *non-intersection* crashes. The 2026 text words it the same
way ("38% of the total non-intersection crashes were run off road crashes
occurring during dark lighting conditions"), and the code tests exactly that.

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

The workbook is what NCDOT actually runs, and it differs from the published
prose on four counts. The workbook wins. **The workbook in hand is the 2024
edition's**; the section arithmetic it carries did not change in 2026, and
its intersection sheets differ from the 2026 text only in the four urban
thresholds listed under "What changed from 2024".

- **Wet is C in {2, 3}**, not {2}. `COUNTIFS(C,">=2",C,"<=3")`.
- **Dark is L in {4, 5, 6}**, not {4, 5}. `COUNTIFS(L,">=4",L,"<=6")`.
  Both are WIDER than the working sheet's conditional formatting, so a cell
  can be unhighlighted and still count toward a warrant.
- **The minimums are strictly greater than**: `=IF(U6>min,...)`. Exactly 30
  crashes does not clear a minimum of 30. `strict=False` gives the `>=` reading
  the prose suggests.
- **SSSD is OFF by default.** The published ROR list has Sideswipe
  **Opposite** Direction (SSOD), not Sideswipe Same. The workbook adds a row
  `Sideswipe Same* (use SSSD)` with the note `*multi-lane only` **and leaves
  its abbreviation cell AB9 blank**, inside the MATCH range `$AB$2:$AB$10`.
  A blank key matches nothing, so SSSD does not count until an engineer types
  it in. `multilane=True` is that opt-in and nothing else. On study
  41000079305 the difference is F-2 at 82.1% against 89.7%.
- **N-4's base is derived from crash TYPE**, not a flag: total minus Angle,
  LTDR, LTSR, RTDR, RTSR, U-Turn and the Y-line variant.

The workbook's ROR list omits **Overturn/Rollover**, which both the 2024
Overview and the 2026 text do list. Kept, on the text's authority.

## Intersection warrants

The workbook carries them on sheets IU (urban) and IR (rural), keyed on EPDO
(K/A 76.8, B/C 8.4, PDO 1) and Frontal Impact types. **Frontal impact in the
2026 text is four families**: Angle, Left Turn (same or different roads),
Right Turn (same or different roads), Head On. The code's `FI_TYPES` holds
the workbook's decoded types as the match keys (Angle, LTDR, LTSR, RTDR,
RTSR, Head-on) and also the workbook's U-Turn and `LTDR, Y-line`, which are
kept. Urban uses a 2-year recency window, rural a 3-year one. The 2026
values (`INTERSECTION_THRESHOLDS["2026"]`):

| | urban (5-year pull) | rural (10-year pull) |
|---|---|---|
| I-1 | %2yr>=25% AND ((FI>=12 AND %FI>=60%) OR (Total>=35 AND %FI>=35% AND FI severity>=6.0)) | %3yr>=20% AND FI>=9 AND %FI>=60% |
| I-2 | Total>=25 AND %1yr>=40% | Total>=20 AND %1yr>=32% |
| I-3 | Total>=25 AND severity>=6.5 AND %2yr>=40% | Total>=20 AND severity>=9.0 AND %3yr>=30% |
| I-3 (both) | K and A frontal-impact crashes in last 5 years >= 3 | same |
| I-4 | %2yr>=25% AND night>=12 AND %night>=45% | %3yr>=20% AND night>=10 AND %night>=46% |

The thresholds live in one table per edition (`INTERSECTION_THRESHOLDS`) and
`screen_intersection(crashes, context, end_date, edition)` reads the table;
there is one copy of the logic. `IntersectionScreen.edition` records which
table ran and `format_intersection` names it.

## What changed from 2024

Four urban thresholds. Everything else, I-1u path (b), the 25% recency
share, the four rural warrants, I-3, the section warrants, the facility
minimums and the ROR list, is the same in both editions.

| warrant | 2024 HSIP Overview | 2026 HSIP Warrants |
|---|---|---|
| I-1u path (a) | 12 or more frontal impacts AND 55% of all crashes frontal | 60% |
| I-2u | 25 or more crashes AND 38% in the last year | 40% |
| I-3u | 25 or more crashes AND severity index 6.0 AND 40% in the last 2 years | severity index 6.5 |
| I-4u | 25% in the last 2 years AND 12 or more night crashes AND 40% night | 45% |

## Non-motorist intersection warrant BP-1 (new in 2026)

**BP-1, Chronic Location**, either path:

- (a) at least 4 crashes involving non-motorists in the last 10 years AND at
  least 50% of those in the last 5 years;
- (b) at least 3 crashes involving non-motorists in the last 5 years.

Non-motorist crashes are the decoded pedestrian and cyclist types, T 14 and
T 15 in `fiche_workbook.T_CODES` (`NONMOTORIST_TYPES`). The two windows
count back from the analysis end date, or from the most recent crash when
none is given, exactly as the intersection screen does; path (a)'s share is
rounded to a whole percent before the test like every other share here.
`screen_nonmotorist_intersection` / `format_nonmotorist`. The HSIP Warrants
page runs it for a **Bike/Ped Intersection** analysis off the same reviewed
rows as the intersection screen, under that screen's result.

## Non-motorist midblock warrant MB-1 (new in 2026)

**MB-1, Chronic Location**: at least 4 non-intersection related crashes
involving non-motorists in the last 10 years.

"Non-intersection related" is the `Crash.at_intersection` flag and nothing
else. The code never derives it: a pedestrian or cyclist crash type says
nothing about where the crash happened, so N-4's type-based base cannot
serve. **The caller sets the flag from the fiche F code (Roadway Feature) or
from the report review.** No F code table is in this pack, so the HSIP
Warrants page and `warrants --midblock` take the F codes the review treats
as intersection related (`--intersection-f 8,9,13`, the "Intersection
related F codes" box); with none named every non-motorist crash reads as
midblock, the count is an upper bound, and the output says so. The screen
reports how many non-motorist crashes it left out on the flag.
`screen_nonmotorist_midblock` / `format_nonmotorist`; offered as an unchecked
extra test on a section run.

## Bridge warrant B-1 (new in 2026)

**B-1, Chronic Location**: at least 5 run off road crashes in the last 10
years AND at least 50% of all crashes run off road. **2-lane roadways only.**
Animal crashes are excluded from the study. ROR is the same list as the
section warrants (`ROR_TYPES`).

`screen_bridge(crashes, two_lane, end_date)` refuses with a ValueError when
`two_lane` is False rather than screening a roadway the warrant does not
apply to. The count is tested over the last 10 years back from the end date
(or the most recent crash); the share is run off road crashes over all
crashes supplied. The warrant is written for a 10-year pull; on a 5-year
section pull both the count and the share are provisional, and the CLI and
the page say so. The share is rounded before the test: 50 of 101 is 49.5%,
reads as 50%, and meets. `format_bridge` names the edition. Offered as an
unchecked extra test on a section run (`--bridge`).

## Analysis periods and the HSIP GIS

Section analyses run on a 5-year period (the minimums table above is a
5-year table). Intersection analyses run on the period NCDOT pulls for the
location: **5 years for urban locations, 10 years for rural ones**. The
period, and the urban/rural call itself, come from the NCDOT HSIP GIS for
the time being:

<https://www.arcgis.com/apps/mapviewer/index.html?webmap=bb6dd277ce6247438fc096200141949a>

The layer `NC HSIP_INT_<year>` carries one point per ranked intersection
with Intersection ID (`TSUINT...`), Legacy PH, Location Description, Rank,
County, City, Routes, and the warrant flags behind the rank (FRONTAL
IMPACT, LAST YEAR INCREASE, SEVERITY INDEX, FATAL AND SEVERE INJURY, NIGHT
LOCATION, each split `- RURAL` / `- URBAN`). **The City field names the
municipality for an urban location and reads `RURAL` for a rural one**;
that is the same urban/rural call the IU/IR sheets and the recency windows
key on. Prior HSIP years are available as layers in the same map.

The longer rural pull does not stretch the recency sub-tests: the windows
(1 year, 2/3 years, and I-3's K/A frontal-impact in the last 5) always
count back from the analysis end date, whatever the pull length. The
non-motorist and bridge warrants' 5- and 10-year windows count back the
same way.

Worked example in hand: study **41000077750** (2025 HSIP; rural, Wayne
County, NC-581 at SR-1960) is GIS point TSUINT672620 / Legacy PH 95I00327,
and the completed study folder `41000077750 PH TSUINT672620` is in the team
Drive. The same location reappears in the 2026 layer at rank 431.

## Bike/Ped HSIP analyses

Alongside the intersection and section analyses, HSIP packages include
bicycle/pedestrian analyses. They are **always 10-year intersection
analyses with a 300 ft y-line** (against the usual 150 ft buffer;
verified on 59X00239: "*Bike/Ped Crashes Only*", 7/1/2011 to 6/30/2021),
their warrant is **BP-1** above, and their collision diagram has its own
format, distinct from the vehicle diagrams: an AERIAL EXHIBIT, not a
schematic. The delivered MECKLENBURG_HSIP_59X00239 sheet
(examples/59X00239, with its TEAAS data and the TransparentMap underlay) is
the reference: the crash cells sit small and pinned on a provided
semi-transparent aerial, street lighting is marked with orange dots and
pedestrian signal heads with orange squares, and four blue markers carry
the Bike/Ped findings (driver failure to yield, bike or ped at a
non-crosswalk location, bike or ped contributing action, lack of sidewalk
or bike lane). Leg labels carry AADT and speed, land uses are boxed, and a
Notes box records the infrastructure history over the 10 years; a vicinity
inset and imagery-access footnotes complete the sheet.

`collision_diagram.render_bikeped` (layout kind ``"bikeped"``) renders
this format; the engineer pins every cell from its report (`at`), the
same rule the Sketch sheet follows, and places the lighting, signal
heads and markers off the field/aerial evidence. Signage photos and
signal-face drawings remain hand-curated in the delivered sheets and are
not generated. The Drive's Bike_Ped Training folder carries NCDOT's
package training deck and the MicroStation seed
(Bike_Ped_Collision Diagram_Template.dgn).

## Shares are rounded to whole percents BEFORE the test

Every share in the workbook is `ROUND(count/total, 2)` and the `>=` comparison
runs on the rounded value: 16/31 = 51.6% rounds to 52% and MEETS a 52%
threshold. This is the test, not presentation, and it decides warrants at the
margin. The thresholds are published as whole percents, so testing at
whole-percent precision is the consistent reading. `WarrantResult.share` is
the tested (rounded) value; `exact_share` keeps the unrounded one for anyone
who wants to see the margin. The new BP-1 and B-1 shares are tested the same
way.

## Values still awaiting a source

Every warrant threshold now has its source: the 2026 HSIP Warrants text for
the 2026 edition, the 2024 HSIP Overview for the 2024 edition. What remains
is workbook-derived or the engineer's call:

| constant | value | status |
|---|---|---|
| `MIN_SECTION_MI` | 0.10 mi | **placeholder, engineer's call.** Not from any NCDOT document. It exists to stop `scan_sections` returning a degenerate answer: ten crashes in 0.02 mi is 500 per mile and clears every rate minimum, which is arithmetic rather than engineering. Replace if NCDOT publishes a minimum section length. |
| `strict` (minimums are `>`, not `>=`) | True | from the 2024 workbook; the prose of both editions reads as `>=` |
| ROR includes Overturn/Rollover | yes | both texts list it, the workbook omits it |
| `WET_CODES`, `DARK_CODES` | {2, 3}, {4, 5, 6} | from the 2024 workbook; neither text publishes a C/L table |
| MB-1's intersection flag | engineer's F codes | no Roadway Feature code table is in the pack; the caller names the codes |
