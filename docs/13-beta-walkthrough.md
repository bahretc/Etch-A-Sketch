# 13 - Beta walkthrough: a fatal slip start to finish

This is the two-page version for a coworker trying the tool for the first
time. It runs the 260307016EA fatal crash analysis (US 311, Forsyth County)
the way the engineer runs it, on the CLI, and says where the same step sits in
the Streamlit app. Nothing here needs crash data that is not already in the
study's TEAAS exports.

## 0. Install (once per machine)

If you have not installed a Python tool before, use INSTALL.md at the top of
the folder instead: double click one file and it does everything below.

Python 3.11 or newer. From the unpacked source zip or the repo:

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e '.[pdf,ocr,ui,deliverables,maps,llm]'
playwright install chromium                       # Chromium for the map PDFs
safety-eval doctor --network                      # what is available, what is reachable
```

The `llm` extra installs the Anthropic SDK, which the AI assist, the QA sweep,
the chat tab and the results drafting all need. Leave it out and everything
else still runs; those four report that they are not ready. They also need a
key: set `ANTHROPIC_API_KEY` in the environment, or paste one into the app's
AI assist settings, where it stays in the app process and is never written to
disk.

`doctor` reports the optional pieces. Two matter for a strip package:

* **LibreOffice with Calc** is used for workbook recalculation and print
  (`print-results`, the recalc tests). On a machine without the Calc filters
  those steps report "source file could not be loaded"; everything else runs.
* **Playwright + Chromium** print the three package maps to PDF. Without them
  `package-maps` still writes the HTML pages, which open in any browser.

`--network` probes the public services the maps and checks use: NCDOT AADT
stations and traffic segments, Census TIGERweb roads, the Census geocoder,
USGS 3DEP elevation and Esri imagery. An office proxy that blocks one of them
shows up here rather than mid-run.

## 1. Inputs from TEAAS and Crashweb

Put the study's exports in one folder, named with the work order:

| File | From |
|---|---|
| `<WO>_FatalSlip.pdf` | Crashweb Fatal Crash Notification |
| `<WO>_CrashReport.pdf` | the fatal crash DMV-349 |
| `<WO>_Fiche.csv`, `<WO>_DetailedFiche.csv` | TEAAS fiche exports (the detailed one carries coordinates) |
| `<WO>_InitialStudy.csv`, `<WO>_InitialID.txt` | TEAAS strip analysis and ID export |
| `<WO>_FeaturesReport_<route>.pdf` | TEAAS features report for the route |

App: on the **Overview** page type the study number, click **Create**, and
drop the whole folder on **Drop your files here**. Each file is recognised
from its content, not its name (the TEAAS banner, the header row, the PDF's
first page, a workbook's sheet names), and the page says what it took each
one for before you click **Add to study**. A file it cannot place is skipped
unless you pick a role for it. The chips under the zone say what the study
has; the pages below fill in from those files.

## 2. Fiche workbook and screen

```bash
safety-eval fiche-workbook --study 260307016EA --study-type fatal \
  --fiche 260307016EA_Fiche.csv --initial-study 260307016EA_InitialStudy.csv \
  --initial-ids 260307016EA_InitialID.txt --detailed 260307016EA_DetailedFiche.csv \
  --features 260307016EA_FeaturesReport_US311.pdf --route "US 311" \
  --lo 10.438 --hi 11.604 --off-lrs-nis
```

The screen colours the From / Toward cells and sets IS for the initial study
crashes, `?` for reports worth pulling and NIS for the rest (docs/03). On a
route with a concurrent freeway section, `--off-lrs-nis` sends rows mileposted
on that other linear reference (US 311 on "I 74 WB COUPLET") to NIS without a
review; leave it off if the engineer wants every unresolved row kept as `?`.

App: **Fiche Workbook** page.

## 3. Report review

Pull the DMV-349s for the `?` rows plus every initial study crash. Index the
binder and extract each report redacted:

```bash
safety-eval binder-index --binder reports.tif --out binder_index.json
safety-eval binder-get --index binder_index.json --crash 107699256 --out 107699256_redacted.pdf
```

Before deciding, run the location check. It compares every crash's coded
milepost with the milepost of its report coordinates on the route centerline,
and geocodes any property address on the reports (mailboxes, yard damage,
driveways, bus stops) to a milepost:

```bash
safety-eval locate-check --route-id 20000311034 \
  --detailed 260307016EA_DetailedFiche.csv --initial-ids 260307016EA_InitialID.txt \
  --addresses addresses.txt --out 260307016EA_locate.csv
```

`addresses.txt` is `<crash id>|<address>` per line. The RouteID is the TEAAS
road code plus the three-digit county code (20000311 + 034). On 260307016EA
this check moved nine of 22 crashes; the coded distances were the weak link.

Record determinations as JSONL (`crash_id`, `status`, `new_mp`, `comment`)
and apply them:

```bash
safety-eval apply-review --workbook 260307016EA_Fiche.xlsx \
  --determinations 260307016EA_review.jsonl --initial-ids 260307016EA_InitialID.txt \
  --out 260307016EA_Fiche_reviewed.xlsx
safety-eval import-list ...      # RE and ADD lines for TEAAS
```

Rules that bit on the first pass, now enforced or documented (docs/03):

* a crash with no report in hand is never IS; it stays `?`;
* an initial study crash TEAAS pulled from a road outside the fiche roads is
  added to the fiche sheet as its own row and reviewed like the rest, its
  comment opening `in initial study, not fiche;`;
* comments state evidence and the resulting milepost, never a verdict on
  the source;
* every evidence-backed RE and ADD goes on the import list, however long.

App: **Review Queue** page; the location check sits on the fatal tab.

## 4. Route features for TEAAS

```bash
safety-eval route-features --route-id 20000311034 --lo 10.438 --hi 11.604 \
  --sight-at 11.11 --out 260307016EA_FeatureList.txt
```

Horizontal curves (PC, PI, PT, radius, deflection) come from the NCDOT route
centerline; crests and sags with grades from the USGS 3DEP 1 m bare-earth
profile; the sight distance at a milepost is a rough line-of-sight walk over
that profile. The feature list uses the same `<text>|<milepost>` format as the
team's 41000079305 features file and was verified on a live TEAAS import
in September 2026 (docs/09).

## 5. Package maps and the AADT workbook

Describe the study in a small YAML (example:
`examples/260307016EA/260307016EA_maps.yaml`) and build:

```bash
safety-eval package-maps --spec 260307016EA_maps.yaml --pdf
safety-eval calc-aadt --spec 260307016EA_aadt.yaml --out 260307016EA_CalculatedAADT.xlsx
```

`package-maps` writes the Location, Area and AADT maps in the VHB figure
format: bordered frame, footer with WO, PH (when given), Division, Study Area
and Coordinates, county locator, Begin and End Study markers, the crash
circled with its text box, the governing station panels with the median year
boxed. Public data is cached under `mapdata/` beside the outputs, so a rerun
after editing the YAML is quick. `calc-aadt` writes the strip CalculatedAADT
sheet with live formulas from the sections you list.

App: the **Fatal Crash** tab, "Package figures and checks".

### Intersection sites and HSIP analyses

The same command draws an intersection site: set `site: intersection`, give
the cross route and the intersection's coordinates, and leave the milepost
limits out. The location map marks the Study Intersection and names both
roads on each side of it; the AADT map traces both routes and carries up to
four station panels, the nearest on each route inside the frame, with the
last eight years so they fit the corners. An HSIP package analysis of either
kind sets `ph` for the footer and leaves the crash fields out. Example:
`examples/260307016EA/intersection_demo_maps.yaml`.

```yaml
site: intersection
route: US 311
route_id: "20000311034"
cross_route: SR 1979
cross_road_label: Grubb Road
cross_route_id: "40001979034"
center_lat: 36.22315
center_lon: -80.16879
ph: "77S00141"
```

App: the **HSIP Warrants** page carries the same section.

## 6. Field Investigation File and memo

```bash
safety-eval fatal-checklist --slip 260307016EA_FatalSlip.pdf \
  --fiche 260307016EA_Fiche_reviewed.xlsx --route "US 311" --lo 10.438 --hi 11.604 \
  --initial-study 260307016EA_InitialStudy.csv --out 260307016EA_FieldInvestigation.xlsx
```

App: the Field Investigation page is parked for now (the CLI above still
builds the file); set `SAFETY_EVAL_FIELD_INVESTIGATION=1` before starting
the app to bring the page back. The maps, route features, location check
and CalculatedAADT live on the **Maps and Checks** page for fatal and HSIP
studies.

## 7. What goes back to TEAAS by hand

TEAAS exports come only from TEAAS (CLAUDE.md rule 9). After the review, enter
the study criteria, upload the import list and the feature list, delete the
DEL crashes, and rerun. The rerun's ID export and strip analysis (CSV and PDF)
are the deliverables; the tool never fabricates them.

## Known limits in this beta

* Route features and the location check are strip tools; intersection
  sites get the package maps, the crash map and the collision diagram.
* Map road names and geometry come from Census TIGER, which is coarser than
  OpenStreetMap; check names near the site against the aerial.
* Curves and crests are estimates from public geometry (limits to about
  50 ft; crest heights from a 1 m DEM). They are for the strip diagram and
  the memo, not for design.
* The Census geocoder resolves addresses to the parcel front; a mailbox
  across the road from its house lands on the wrong side, same milepost.
* Recalculation and print need LibreOffice with Calc; Windows installs of
  LibreOffice include it, the container used for development did not.
