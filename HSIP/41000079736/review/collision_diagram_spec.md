# Drawing specification - Intersection collision diagram, TEAAS study 41000079736

NC 180/NC 226 (S Post Rd) at SR 1103 (Pleasant Dr / Pleasant Hill Church Rd), Cleveland County, Division 12.
Study period 9/1/2016 - 8/31/2026 (10.00 yr), 29 crashes, 58 unit rows, rural, two-way stop on SR 1103, 45 mph on NC 180.

Input file: `data/41000079736_CollisionDiagramData.csv` (TEAAS "Collision Diagram Data File", 22 columns, one row per unit).
Supplementary (notes only): `data/41000079736_CrashAnalysis10yr_29crashes.csv` (object struck U1_obj, person-injury counts, vehicle type).
Output: `maps/5_collision_diagram_NCDOT.pdf` (vector, page 1 = diagram, page 2 = numbered crash listing) and `maps/5_collision_diagram_NCDOT.png` at 300 dpi.
Implementation target: matplotlib, one figure 17 x 11 in, one page axes in inches (0..17, 0..11); everything below is in page inches unless stated.

This spec supersedes `maps/3_collision_diagram.png` (make_maps.py) and revises `collision_diagram.py`. Where the existing draft already matches a rule, keep its code.

---

## 0. Governing decisions (reconciliation of the four research inputs)

| Question | Decision | Why |
|---|---|---|
| Symbol set | NCDOT Traffic Safety Unit cells exactly (TSU "Collision Diagrams" deck 2013, legend wording of W-5706A 2017) | This is an HSIP/TEAAS product; the HSM/ITE, TxDOT, CTPS, Crash Magic sets are not used. |
| Injury levels | 2017 three-level: hollow red circle = non-severe (B, C), half-filled = severe (A), filled = fatality (K). PDO = no circle | W-5706A is the current TSU sheet; 2013 sheets had only two levels. |
| Per-crash text | None. Date, time, severity, conditions are encoded in the symbol; a numbered crash listing accompanies the diagram (PDF page 2) | Every NCDOT sheet; HSM-style text labels are generic practice and lose. |
| Crash numbering | 1-29 in date order = "Acc No" of the TEAAS 10-yr Intersection Analysis Report (the CSV is already in that order) | TSU: "Intersection Crash IDs should be ordered by date". |
| Speed dots | From SPD_EST_NBR (estimated original speed), not SPD_AT_IMPCT_NBR | SPD_EST is the "Speed" printed on the TEAAS listing, so a reviewer's cross-check ties out. |
| At-fault unit | The unit with VIOLATION != 0; if several, the lowest UNT_NBR gets the number circle and all charged units get an asterisk; if none, unit 1 gets the circle and no asterisk | TSU: number circle on the at-fault vehicle as a secondary fault indicator; data quirks on 108502945 (both charged) and 108564225 (unit 2 charged). |
| Path shape | MANEUVER shapes each unit's path (straight / left arc / right arc / stopped); ACC_TYP chooses the special cell (rear-end bar, ran-off-road zigzag) and the target-crash marking | Lets crash 1 (coded Angle, unit 1 making a left turn) draw truthfully; TSU allows correcting miscoded cells. |
| Skew | Draw the true geometry: NC 180 and SR 1103 cross at 49 deg / 131 deg, NC 180 vertical on the page | TSU: "lane configurations and skew angles should be as close as possible to actual"; the skew is the engineering story (EB driver on Pleasant Dr looks back 131 deg over the right shoulder for SB traffic; 9 of 12 EB-at-fault frontal crashes involve a SB vehicle). |
| Orientation | NC 180 runs up the page (page up = bearing 22 deg); north arrow rotated 22 deg counter-clockwise from page up | Keeps the two open 131-deg wedges on the left and right of the sheet for the Order block, legend and title block; NCDOT allows rotating the north needle instead of the drawing (SS 05-05-208, 05-06-228 both do). |
| Scale | Not to scale, no scale bar; pavement widths are exaggerated so 29 cells fit | TSU: "Collision Diagrams are not to scale"; no NCDOT sheet carries a scale. |
| Placement | Cells sit in the conflict zone where the two units' lanes cross, stacked in diagonal "ladders" back along both approaches (the Currituck SS 01-07-200 pattern); rear ends and ran-off-road cells sit in the approach lane | Matches the real sheets; avoids the false "crash 300 ft up the leg" reading of the current grid layout. |
| Insets | None required on 17 x 11 at the sizes below; an inset rule is given as the fallback if the clearance check fails | TSU: insets only "if there is a large pattern that can't be fit into the diagram at a readable size". |
| Statistics block | A small crash-summary text in the Notes box (crash-based counts). No table of crashes on the sheet | NCDOT sheets carry no statistics; the task requires a summary, so it is kept small and subordinate. |
| Colour | Black line work; colour only on the standard attribute marks (blue dots, magenta asterisk, green letter, red injury/target circles, red STOP). Must survive greyscale | TSU printing note: crash cells in colour, background black/white, no yellow. |

---

## 1. Sheet

- Figure 17 x 11 in landscape (`plt.figure(figsize=(17, 11))`), white background. Page axes `px` spanning 0..17 x 0..11 in, aspect equal, axis off. Draw everything on `px` in inches (base map, cells, furniture) - no separate feet axes.
- Neatline: rectangle (0.5, 0.5) to (16.5, 10.5), black, 1.2 pt. Nothing is drawn outside it except the figure number.
- Furniture boxes (legend, title block, target key, notes) are white-filled and drawn above the base map (zorder 20+), so legs that run under them are hidden; legs otherwise run to the neatline.
- Fonts: `DejaVu Sans` for all drawing text (NCDOT's stroke font is not available); `DejaVu Serif` bold italic for the title block only. Minimum 7 pt for anything printed.
- Line weights: pavement edge lines 1.0 pt; centre lines 0.6 pt dashed (8, 6); stop bars 5 pt; cell line work 0.8 pt (TSU "line weight 0" = thin); arrowhead outline 0.8 pt; number circle 1.0 pt; injury circle 1.0 pt.
- Outputs: `fig.savefig(pdf)` via `PdfPages` with two pages (diagram, listing); PNG at `dpi=300`. Also write `review/collision_diagram_placement.txt` (one line per cell: numbers, type, ladder, page x/y) for QA.

Page coordinate convention. The intersection centre is **C = (7.6, 5.3)**. A compass bearing b maps to the page unit vector

```
pv(b) = (sin(b - 22 deg), cos(b - 22 deg))          # page up = bearing 22 = NC 180 toward the north leg
uN  = pv(22)  = ( 0.000,  1.000)   NB travel / toward the N leg
uS  = pv(202) = ( 0.000, -1.000)   SB travel / toward the S leg
uNW = pv(333) = (-0.755,  0.656)   WB/NW-bound travel / toward the Pleasant Dr (NW) leg
uSE = pv(153) = ( 0.755, -0.656)   EB/SE-bound travel / toward the Pleasant Hill Church Rd (SE) leg
right(d) = (d.y, -d.x)             driver's right-hand side of travel direction d
add(p, d, s) = p + s*d
```

DIRECT -> travel vector: N, NE -> uN; S, SW -> uS; E, SE -> uSE; W, NW -> uNW (only N, S, E, W, SE, NW occur).

---

## 2. Base map (schematic, true skew)

Both roads are two-lane, two-way, undivided (RD_CONFIG 2 on every row), one lane per direction, no turn lanes. Before coding, open the cached Esri tile `maps/.tiles` z18 covering 35.2463, -81.5094 and confirm NC 180 has no left-turn lanes at SR 1103; if it has, add a 0.8 in wide lane line for that lane and note it here. (Crash 19, SB left-turner struck from behind by a SB through vehicle, is consistent with no SB left-turn lane.)

Half-widths (page inches, exaggerated about 9 ft/in): **HM = 1.3** for NC 180 (pavement 2.6 in), **HS = 1.1** for SR 1103 (pavement 2.2 in). Lane centre of travel direction d: `add(C, right(d), H/2)` where H is that road's half-width.

Edge lines. For each of the four legs, two straight edge lines offset +-H from the centreline, from the fillet tangent point to the neatline (or under furniture). Corner fillets between adjacent legs, tangent to both edge lines:

| Corner | Legs | Interior angle | Fillet radius |
|---|---|---|---|
| North (acute) | N leg / NW leg | 49 deg | 1.5 in |
| West (obtuse) | NW leg / S leg | 131 deg | 0.9 in |
| South (acute) | S leg / SE leg | 49 deg | 1.5 in |
| East (obtuse) | SE leg / N leg | 131 deg | 0.9 in |

Fillet construction (already in `collision_diagram.py::base_map`): corner point = intersection of the two offset edge lines; centre = corner + bisector * R / sin(half-angle); tangent points = centre - R * edge normal; arc between them, straight edges outward from the tangent points. Keep that code, change the constants.

Centre lines: NC 180 continuous dashed black line through the intersection (the real double yellow is drawn black per TSU). SR 1103 dashed black on each leg, stopping at the NC 180 edge line. No lane-use arrows (none exist; if the aerial shows turn lanes, draw NCDOT-style solid black pavement arrows in them).

Stop bars (both SR 1103 approaches, NCDOT style heavy black bar): perpendicular to the SR 1103 centreline, from the centreline to the approach lane's right-hand edge line, 5 pt, placed where the approach lane's right edge meets the NC 180 edge line. For the NW leg (EB approach, right side = `right(uSE)` = lower-left side of the centreline) that is at t = 0.8 in along uNW from C: bar from (7.00, 5.82) to (6.28, 4.99). For the SE leg (WB approach, right side = `right(uNW)` = upper-right side) symmetric: t = 0.8 in along uSE: bar from (8.20, 4.78) to (8.92, 5.61). Compute, do not hard-code: `t = (HM - H_side*|right(d).x|) / |d.x|` solved for the right-edge point reaching x = C.x -+ HM.

STOP signs: red (#ff0000) regular octagon, 0.32 in across flats, 0.5 pt black outline, white bold "STOP" 5 pt (sign faces are the one place below 7 pt, matching the examples), centred 0.45 in outside the approach lane's right edge line and 0.35 in upstream of the stop bar, i.e. on the driver's right before the bar. Legend row "STOP SIGN" uses the same octagon at 0.16 in.

Leg labels (rotated to read along the leg; 9 pt; NCDOT format). **Superseded 10/9/2026:** the AADT shown is now the
middle-year (2021) value per leg - 11,000 / 10,500 / 1,400 (estimate) / 1,200 - from `41000079736_AADT.xlsx`, and the
labels are horizontal, in the VHB sheet format (see README). The rows below record the first draft only.

Original draft:

| Leg | Lines | Anchor (in), rotation | Side |
|---|---|---|---|
| N (NC 180/NC 226 north) | `NC 180/NC 226 (S Post Rd)` / `AADT (Year)` / `10,500 (2025)` / `45 MPH` / `to NC 226 (Earl Rd) / Shelby` | (9.45, 9.1), rot 90 | right of the pavement edge (x > 8.9), left of the legend |
| S (NC 180/NC 226 south) | `NC 180/NC 226 (S Post Rd)` / `AADT (Year)` / `10,000 (2025)` / `45 MPH` / `to SR 1236 (Idlewild Rd)` | (9.3, 1.4), rot 90 | right of the pavement edge; nudge until clear of the SE leg's lower edge line |
| NW (SR 1103 Pleasant Dr) | `SR 1103 (Pleasant Dr)` / `AADT (Year)` / `1,500 (2024)` / `SIDE_SPEED` / `to SR 2384` | (2.4, 7.4), rot -41 | lower-left side of the leg |
| SE (SR 1103 Pleasant Hill Church Rd) | `SR 1103 (Pleasant Hill Church Rd)` / `AADT (Year)` / `1,200 (2025)` / `SIDE_SPEED` / `to SR 2205` | (11.5, 4.3), rot -41 | upper-right side of the leg, below the north arrow |

AADT values and stations come from `aadt.json` (0230000187, 0230000152, 0230000045, 0230000531). `SIDE_SPEED` is a module constant; **the SR 1103 posted speed is unverified** (unit rows carry 45 on most SR 1103 units, 35 on 107915535 and 108431889 unit 1). Default `SIDE_SPEED = None` prints no speed line on the SR 1103 legs; set it to "45 MPH" (or the ordinance value) once checked against the TEAAS ordinance database or a field photo. Do not derive any leg speed from SPD_LMT_NBR.

Y-line: not drawn (it is on the area map). Driveways: none drawn.

---

## 3. Crash data -> drawing attributes

Read the CSV, group rows by CRSH_ID preserving file order, sort units by UNT_NBR, number crashes 1..29 in ACDNT_DT_TM order (equals file order; assert it). Crash-level fields are taken from the unit-1 row.

| Field | Rule |
|---|---|
| ACC_TYP | Cell family: 30 angle; 23/24 left turn; 25/26 right turn; 21 rear end; 19 ran off road (fixed object). Target crash if ACC_TYP in {23, 24, 25, 26, 27, 30} -> red number circle (22 crashes). |
| MANEUVER (per unit) | 4 going straight -> straight path to the impact point. 8 making left turn -> left arc. 7 making right turn -> right arc. 1 stopped in travel lane -> stopped-vehicle symbol (bar at its tail, short arrow, no dots). 11 slowing or stopping (106893683 U2) -> straight path, speed dots as coded. |
| DIRECT (per unit) | Travel vector per section 1; for a turning unit it is the approach heading (the arc starts on this heading). |
| VIOLATION (per unit) | != 0 -> magenta asterisk on that unit; number circle at the tail of the lowest-numbered charged unit. All zero -> circle on unit 1, no asterisk (crash 8 only). |
| SPD_EST_NBR (per unit) | Blue dots: n = min(speed // 10, 6) for speed < 70 (0 dots for 0-9); 70+ -> triple-line shaft; blank/None -> blue "x" on the shaft. Values here are 0-55, so 0-5 dots. |
| LT_COND (crash) | 4, 5, 6 -> filled (night) arrowheads on every unit of the crash (9 crashes). 1, 2, 3 -> hollow (crash 5, dusk, is hollow). |
| RD_COND (crash) | Green letter beside the number circle: 1 -> D; 2, 3 -> W; 4, 5, 6 -> I; 7, 8, 9 -> O; 10 -> O. Here 25 D, 4 W. |
| SVRTY_CD (crash) | 1 K -> filled red circle at the impact point; 2 A -> half-filled; 3 B / 4 C -> hollow red circle; 5 PDO -> nothing. |
| NBR_UNT_CNT | 3 -> draw all three units (crashes 5 and 19), add the note "3 units". 1 -> single zigzag path. |
| DSTNC_MILE_FRM_RD_QTY, DRCTN_FRM_RD_CD, RD_ON_CD, MLPST_NBR | 0 -> at the intersection. Crash 12 (0.009 mi S on NC 180) -> just past the intersection on the S leg. Crash 8 (SR 1103 MP 3.019, 0.1 mi W of SR 2205) -> drawn on the SE leg approach with a sheet note. Crash 21 (MP 999.999, "SR 1103 at SR 1103") -> at the intersection with a sheet note. |
| TRFC_CTRL, RD_CONFIG, SPD_LMT_NBR, SPD_AT_IMPCT_NBR, CNTY_NBR, FRM_RD_CD | Not drawn. |

Stacking signature (TSU "stacking numbers" rule): `(ACC_TYP, at-fault index, tuple per unit of (DIRECT, MANEUVER, speed bin = min(est//10, 7)), night flag, road letter, severity class)`. Identical crashes share one cell with their number circles in a row behind the tail (0.20 in apart, earliest nearest the shaft). In this data exactly one stack occurs: **crashes 22 and 25** (angle, E straight 10-19 mph at fault vs S straight 40-49, day, dry, C). Assert `len(cells) == 28`.

---

## 4. Cell primitives (page inches)

All cells are built from these primitives; `P` is the impact point.

- **Shaft**: black polyline, 0.8 pt, round caps. Straight unit length **Ls = 0.50** (tail to tip).
- **Arrowhead**: isosceles triangle at the tip, length 0.12, half-width 0.05, 0.8 pt black outline; fill white for day, black for night. The tip is exactly at the end point of the path.
- **Speed dots**: blue (#0000ff) filled circles diameter 0.045 (ms 3.2 pt at 72 dpi), centred on the shaft, the first 0.10 in from the tail, then every 0.06 in, measured along the path (resample the polyline). Triple line (70+): two extra parallel lines 0.025 in either side of the shaft over its first 0.30 in. Unknown: blue "x" 4.5 pt at 0.15 in from the tail.
- **Number circle**: white disc radius **0.09** (0.18 dia), outline 1.0 pt, centre 0.11 in behind the tail along the reversed travel vector; number 7.5 pt (6.5 pt for two digits) in the outline colour: **red (#ff0000) for target crashes, black otherwise**. For a stack, additional circles continue backward at 0.20 in spacing.
- **Fault asterisk**: magenta (#ff00ff) 8-point asterisk glyph "∗" (U+2217) 13 pt bold, centred 0.09 in to the **driver's left** of the shaft, 0.06 in ahead of the tail (above a rightward arrow, as in the TSU component slide).
- **Road letter**: green (#008000) 8.5 pt capital, centred 0.09 in to the **driver's right** of the shaft, 0.06 in ahead of the tail (below a rightward arrow).
- **Injury circle**: radius 0.045 centred on P, red 1.0 pt outline; hollow (white fill) for B/C; A = white fill plus a red half-disc (`Wedge(P, r, 0, 180)`, the upper half in page terms); K = red fill. Drawn above the arrowheads (zorder 8).
- **Impact bar** (rear end / stopped vehicle): black line 0.8 pt, 0.16 in long, centred on the point, perpendicular to the lead vehicle's travel vector.
- **Turn arc**: straight approach segment 0.25 in, then a quarter circle of radius **0.25** turning 90 deg left or right, ending at P heading in the turned direction; the tip (arrowhead) is at P. Tail = start of the straight segment. Build with the existing `draw_crash` arc code (start = P - R*t - R*out, tail = start - Ls_turn*t with Ls_turn = 0.25).
- **Zigzag (ran off road)**: from the tail, straight 0.20; then peaks at (+0.06, +0.08 right), (+0.14, -0.08), (+0.20, +0.05), (+0.24, 0) along the travel direction; then a straight 0.28 in segment rotated 35 deg toward the departure side, ending in an arrowhead. Note text 7 pt beside the end point, offset 0.15 in further along the departure direction, white bbox pad 0.5.
- **Stopped vehicle** (MANEUVER 1): impact bar at the vehicle's tail point, a 0.25 in shaft forward from it, arrowhead (day/night per crash), no dots. No circle or letter unless it is the at-fault unit (never the case here).

Sizes are chosen so a complete two-unit cell with circle, asterisk and letter fits in about 0.6 x 0.6 in.

---

## 5. Cell drawing rules by crash type present

For every cell: each unit's path ends (tip) at the impact point P unless the rule says otherwise. The number circle, asterisk and road letter attach to the at-fault unit's tail. The injury circle sits on P.

1. **Angle (30)** - crashes 5, 22/25, 23, 26, 28, 29 (and 1, see below). Two straight units, tips meeting at P at the true skew (49 deg between an SR 1103 path and an NC 180 path, drawn as they are: EB/WB along uSE/uNW, NB/SB along uN/uS). Crash 1 is coded Angle but unit 1 was making a left turn (MANEUVER 8): draw unit 1 as a left arc (left-turn-different-roadways geometry) and flag it in the listing ("coded Angle; unit 1 turning left"). Crash 5 has a third, stopped unit: see 3-unit rules.
2. **Left turn, different roadways (24)** - crashes 3, 6, 9, 10, 13, 14, 16, 19, 21. The turning unit (MANEUVER 8) is drawn as a left arc from its approach heading into the crossing road's lane, tip at P; the through unit is a straight path with tip at P. Geometry per TSU "Left Turn - Different Roadway" (curved arrow from the side street or the mainline sweeping 90 deg into the straight arrow). The arc turns 90 deg on the page even though the real turn is 49 or 131 deg - the cell is a symbol, not a track.
3. **Left turn, same roadway (23)** - crashes 24, 27. Crash 24: both units turning left from opposite NC 180 approaches (N LT at fault vs S LT); draw two left arcs whose tips meet at P (both end headings point toward each other's side streets), circle on the NB tail. Crash 27: EB left turn (at fault) vs WB right turn, both bound for the N leg; draw the EB left arc ending at P heading uN and the WB right arc ending at P heading uN from the other side; do not let the arcs form a closed arch - keep their tails on opposite legs and their tips 0.02 in apart on P.
4. **Right turn, different roadways (26)** - crashes 4, 7. Right arc from the NW leg into the SB lane, tip at P; SB straight unit tip at P. (TSU "Right Turn - Different Roadway".)
5. **Right turn, same roadway (25)** - crash 17. Coded same roadway, but unit 1 (NW-bound) turned right onto NC 180 and was struck by a NB through vehicle: draw the right arc from the SE leg into the NB lane with the NB straight unit's tip at P (the different-roadway geometry); flag "coded Right Turn Same Roadway" in the listing.
6. **Rear end, slow or stop (21)** - crashes 2, 8, 15, 18, 20. Both units collinear on the lead unit's travel vector. Impact bar at P perpendicular to travel. Following unit (unit 1, at fault except crash 8): straight shaft ending with its arrowhead tip 0.01 in behind the bar, dots per its speed, circle/asterisk/letter at its tail. Lead unit (MANEUVER 1 stopped, speed 0): shaft from the bar forward 0.30 in, arrowhead, no dots. Injury circle (none here) would go 0.10 in ahead of the bar on the lead shaft.
7. **Fixed object (19)** - crashes 11, 12. Single unit, zigzag cell ("RAN OFF ROAD"), tip at the roadside, note with the object struck from U1_obj in the 29-crash CSV (107037107 -> "embankment", 107067627 -> "ditch"). Departure side: driver's right unless the DMV-349 says otherwise. Crash 11 (NB, making a right turn, 22:43, inattention): path = NB approach in the NB lane, right arc into the SE-bound lane of the SE leg, then the zigzag and the departure segment leaving the pavement on the driver's right (outside the south acute corner). Crash 12 (SB, straight, 0.009 mi S, overcorrected): zigzag in the SB lane just south of the intersection, departure to the driver's right (page left, west side).
8. **Three-unit crashes**. Crash 5 (W straight at fault, est 0 mph; S straight 45; E stopped): WB and SB straight units with tips at P; unit 3 as a stopped-vehicle symbol placed in the EB approach lane at the NW-leg stop bar (bar at its tail just upstream of the stop bar, short arrow pointing uSE). Crash 19 (S left turn at fault, est 0; S straight 45; N straight 45): unit 1 left arc from the SB lane into the SE leg with tip at P in the NB lane; unit 2 (SB through) straight shaft ending at an impact bar placed at unit 1's tail (it struck the waiting turner from behind); unit 3 (NB) straight with tip at P. Both get the note "3 units" (7 pt) 0.12 in beside the number circle on the side away from the asterisk.
9. **Both drivers charged** - crash 28 (S straight v26 at fault, E straight v19): circle at the SB tail, asterisk on both units.
10. **Unit 2 charged** - crash 29 (N straight v0, E straight v19): circle, asterisk and letter at the EB tail.
11. **Nobody charged** - crash 8: circle at unit 1 (following vehicle) tail, no asterisk.

---

## 6. Placement

Conflict-zone anchors (intersections of lane centrelines; `lane(d, H) = (add(C, right(d), H/2), d)`):

| Zone | Definition | Page point |
|---|---|---|
| Z1 | EB lane x SB lane | (6.95, 5.14) |
| Z2 | EB lane x NB lane | (8.25, 4.01) |
| Z3 | WB lane x SB lane | (6.95, 6.59) |
| Z4 | WB lane x NB lane | (8.25, 5.46) |
| Z5 | SR 1103 centreline x SB lane (NB left-turn crossing) | (6.95, 5.87) |
| Z6 | SR 1103 centreline x NB lane (SB left-turn crossing) | (8.25, 4.73) |

Ladders. Cell k (k = 0, 1, ...) of a ladder has impact point `P_k = anchor + k * step`. Members are listed in crash-number order; the earliest crash sits at the anchor (closest to the true impact point) and later crashes step back along both approaches, as on SS 01-07-200.

| Ladder | Anchor | Step (in) | Members (cells) | Reading |
|---|---|---|---|---|
| L1 EB at fault x SB lane | Z1 = (6.95, 5.14) | (-0.23, +0.50) | 1, 4, 6, 7, 10, 21, 22/25, 28 | climbs the acute north wedge between the SB lane and the EB approach |
| L2 EB at fault x NB lane | Z2 = (8.25, 4.01) | (-0.23, +0.50) | 9, 23, 29, 27 | parallel to L1, 1.3 in to the right |
| L3 WB at fault x SB lane | Z3 = (6.95, 6.59) | (+0.55, +0.25) | 5, 26 | into the open east wedge |
| L4 WB at fault x NB lane | Z4 = (8.25, 5.46) | (+0.50, +0.30) | 16, 17 | east wedge, below L3 |
| L5 NB left turn x SB lane | Z5 + (-0.80, -0.35) = (6.15, 5.52) | (-0.60, -0.20) | 3, 13, 24 | into the open west wedge |
| L6 SB left turn x NB lane | Z6 + (+0.60, -0.13) = (8.85, 4.60) | (+0.60, -0.15) | 14, 19 | east wedge toward the SE leg |

Approach-lane cells (not in ladders):

| Cell | Location rule | Page point of the impact bar / arc end |
|---|---|---|
| 2 (EB rear end, SR 1103 at NC 180) | EB approach lane of the NW leg, bar 2.8 in from C along uNW | (5.13, 6.72) |
| 20 (WB rear end, SR 1103 at NC 180) | WB approach lane of the SE leg, bar 2.8 in from C along uSE | (10.07, 3.88) |
| 8 (WB rear end, MP 3.019) | WB approach lane of the SE leg, bar 4.1 in from C along uSE; sheet note | (11.06, 3.03) |
| 18 (SE-bound rear end) | SE-bound (departing) lane of the SE leg, bar 3.4 in from C along uSE | (9.81, 2.65) |
| 15 (NB rear end) | NB approach lane of the S leg, bar 3.2 in from C along uS | (8.25, 2.10) |
| 12 (SB ran off road, 0.009 mi S) | SB lane of the S leg, zigzag start 2.1 in from C along uS, departure to page left | (6.95, 3.20) |
| 11 (NB right turn, ran off road) | tail in the NB lane 2.0 in below C; arc into the SE-bound lane; zigzag; departure segment ends at `C + 0.4*uS + 1.6*uSE + 0.9*right(uSE)` | (8.22, 3.17) |

Clearance check (run after placement, before saving): collect every number circle, stacked circle, asterisk and injury circle centre; for any pair belonging to different cells closer than **0.20 in**, move the later-numbered cell one more `step` along its ladder (or 0.4 in further along the leg for approach cells) and re-check; stop after 5 passes and print the remaining pairs. With the table above the minimum cell-centre spacing is 0.58 in (crashes 3 and 4), so no moves are expected.

Inset fallback (only if the check cannot be satisfied or a ladder would run under furniture): move the whole ladder into a boxed inset 3.0 x 2.4 in in the nearest free corner, labelled with a letter in a 0.2 in circle (A, B, ...) at the top-left of the box; draw the same letter in a red circle at the ladder's anchor with a red leader line to the box; cells inside the inset keep their orientation and sizes and sit on a pale grey (#bbbbbb, 0.6 pt) copy of the nearby edge lines (TSU insets slide; SS 05-06-228).

---

## 7. Per-crash drawing table (authoritative; derived from the CSV)

Dots = speed dots from SPD_EST_NBR. Head = arrowhead fill (hollow day / filled night). Circle colour: R = red target, K = black. Inj = injury circle.

| No | Crash ID | Date / time | ACC_TYP | Cell | At-fault unit | Unit paths (dir, maneuver, est mph -> dots) | Head | Letter | Inj | Circle | Place |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 104908181 | 11/08/16 19:02 | 30 | LT-D geometry (coded angle) | U1 * | U1 E LT 10 -> 1; U2 S str 45 -> 4 | filled | D | - | R | L1 k=0 |
| 2 | 105162557 | 07/16/17 13:53 | 21 | rear end | U1 * | U1 E str 5 -> 0; U2 E stopped 0 -> 0 | hollow | D | - | K | NW approach |
| 3 | 106032499 | 10/14/19 07:59 | 24 | LT-D | U1 * | U1 N LT 10 -> 1; U2 S str 35 -> 3 | hollow | D | - | R | L5 k=0 |
| 4 | 106234219 | 05/23/20 21:31 | 26 | RT-D | U1 * | U1 E RT 10 -> 1; U2 S str 45 -> 4 | filled | D | B hollow | R | L1 k=1 |
| 5 | 106423994 | 12/01/20 17:41 | 30 | angle, 3 units | U1 * | U1 W str 0 -> 0; U2 S str 45 -> 4; U3 E stopped 0 -> 0 | hollow (dusk) | D | B hollow | R | L3 k=0 |
| 6 | 106442060 | 12/19/20 17:44 | 24 | LT-D | U1 * | U1 E LT 15 -> 1; U2 S str 45 -> 4 | filled | D | - | R | L1 k=2 |
| 7 | 106691473 | 08/24/21 15:45 | 26 | RT-D | U1 * | U1 SE RT 10 -> 1; U2 S str 45 -> 4 | hollow | D | - | R | L1 k=3 |
| 8 | 106808749 | 12/17/21 15:17 | 21 | rear end | U1 (no *) | U1 W str 10 -> 1; U2 W stopped 0 -> 0 | hollow | D | - | K | SE approach, 4.1 in; note |
| 9 | 106839126 | 01/20/22 07:57 | 24 | LT-D | U1 * | U1 E LT 0 -> 0; U2 N str 45 -> 4 | hollow | W | - | R | L2 k=0 |
| 10 | 106893683 | 03/15/22 11:33 | 24 | LT-D | U1 * | U1 E LT 35 -> 3; U2 S slowing 45 -> 4 | hollow | D | - | R | L1 k=4 |
| 11 | 107037107 | 08/03/22 22:43 | 19 | ran off road (right turn) | U1 * | U1 N RT 45 -> 4 | filled | D | - | K | S leg -> SE corner; note "embankment" |
| 12 | 107067627 | 08/28/22 00:08 | 19 | ran off road | U1 * | U1 S str 45 -> 4 | filled | D | - | K | S leg SB lane; note "ditch" |
| 13 | 107086689 | 09/13/22 17:28 | 24 | LT-D | U1 * | U1 N LT 10 -> 1; U2 S str 45 -> 4 | hollow | D | B hollow | R | L5 k=1 |
| 14 | 107127945 | 10/24/22 20:40 | 24 | LT-D | U1 * | U1 S LT 25 -> 2; U2 N str 55 -> 5 | filled | D | - | R | L6 k=0 |
| 15 | 107162484 | 11/28/22 16:16 | 21 | rear end | U1 * | U1 N str 45 -> 4; U2 N stopped 0 -> 0 | hollow | D | - | K | S approach NB lane |
| 16 | 107171393 | 12/05/22 15:11 | 24 | LT-D | U1 * | U1 W LT 5 -> 0; U2 N str 45 -> 4 | hollow | W | - | R | L4 k=0 |
| 17 | 107473530 | 09/26/23 17:58 | 25 | RT (drawn different-roadway) | U1 * | U1 NW RT 10 -> 1; U2 N str 45 -> 4 | hollow | D | - | R | L4 k=1 |
| 18 | 107503115 | 10/24/23 17:25 | 21 | rear end | U1 * | U1 SE str 45 -> 4; U2 SE stopped 0 -> 0 | hollow | D | - | K | SE leg departing lane |
| 19 | 107790631 | 07/16/24 17:09 | 24 | LT-D, 3 units | U1 * | U1 S LT 0 -> 0; U2 S str 45 -> 4 (bar at U1 tail); U3 N str 45 -> 4 | hollow | W | C hollow | R | L6 k=1 |
| 20 | 107915535 | 11/08/24 16:26 | 21 | rear end | U1 * | U1 W str 5 -> 0; U2 W stopped 0 -> 0 | hollow | D | - | K | SE approach WB lane |
| 21 | 107960640 | 12/15/24 17:52 | 24 | LT-D | U1 * | U1 E LT 10 -> 1; U2 S str 45 -> 4 | filled | W | - | R | L1 k=5; note |
| 22 | 108045557 | 03/07/25 14:25 | 30 | angle (stacked with 25) | U1 * | U1 E str 15 -> 1; U2 S str 45 -> 4 | hollow | D | C hollow | R | L1 k=6 |
| 23 | 108120512 | 05/19/25 18:55 | 30 | angle | U1 * | U1 E str 15 -> 1; U2 N str 45 -> 4 | hollow | D | A half | R | L2 k=1 |
| 24 | 108353439 | 12/16/25 21:12 | 23 | LT-S (two left arcs) | U1 * | U1 N LT 45 -> 4; U2 S LT 25 -> 2 | filled | D | A half | R | L5 k=2 |
| 25 | 108387988 | 01/22/26 15:02 | 30 | angle (stacked with 22) | U1 * | U1 E str 10 -> 1; U2 S str 45 -> 4 | hollow | D | C hollow | R | L1 k=6 |
| 26 | 108431889 | 03/14/26 21:30 | 30 | angle | U1 * | U1 W str 35 -> 3; U2 S str 45 -> 4 | filled | D | - | R | L3 k=1 |
| 27 | 108453977 | 03/23/26 07:38 | 23 | LT-S (EB left vs WB right) | U1 * | U1 E LT 15 -> 1; U2 W RT 5 -> 0 | hollow | D | - | R | L2 k=3 |
| 28 | 108502945 | 05/15/26 15:00 | 30 | angle | U1 *, U2 * | U1 S str 35 -> 3; U2 E str 10 -> 1 | hollow | D | - | R | L1 k=7 |
| 29 | 108564225 | 07/08/26 08:58 | 30 | angle | U2 * | U1 N str 45 -> 4; U2 E str 15 -> 1 | hollow | D | B hollow | R | L2 k=2 |

Checks the code must assert: 22 red circles, 7 black; 9 crashes with filled heads (1, 4, 6, 11, 12, 14, 21, 24, 26); 4 W letters (9, 16, 19, 21); injury circles on 9 crashes (A: 23, 24; B: 4, 5, 13, 29; C: 19, 22, 25); 28 cells.

---

## 8. Labels, notes and the crash listing

- No date, time, crash ID or severity text on any cell. The only text on a cell is the number in the circle, the road letter, and a 7 pt note where section 5 calls for one ("3 units", "embankment", "ditch").
- Notes are 7 pt black, placed 0.12 in from the cell element they describe, with a white bbox (pad 0.5) so they never overprint line work; if a note would touch another cell's circle, draw a 0.5 pt leader and move the note 0.4 in outward along the leg.
- Sheet notes box (lower left, see section 10) carries the location-basis notes for crashes 8 and 21, the fiche note and the numbering note.
- **Crash listing, PDF page 2** (17 x 11, same border, heading "Crash listing - Order# 41000079736, 9/1/16 - 8/31/26"): one row per crash, 8 pt monospace or a matplotlib table: `No | Crash ID | Date | Time | Crash type (ACC_TYP label) | Severity (K/A/B/C/PDO) | Light (LT_COND label) | Road (RD_COND label) | Units (dir/maneuver/est mph per unit) | Note`. Notes column: crash 1 "coded Angle; unit 1 turning left"; 5 "3 units; dusk"; 8 "referenced SR 1103 MP 3.019 (0.1 mi W of SR 2205), included after fiche review"; 17 "coded Right Turn Same Roadway; drawn from side street"; 19 "3 units"; 21 "unmileposted (SR 1103 at SR 1103); located by DMV-349 coordinates 170 ft from the intersection"; 28 "both drivers charged"; 29 "unit 2 charged". Also write the same table to `review/collision_diagram_listing.csv`.

---

## 9. Legend (box top right)

Box at (10.2, 7.9), width 6.2, height 2.3, white, 0.8 pt border. Title "LEGEND" 12 pt italic, centred, underlined with a 0.6 pt rule. Four columns of 6 pt caps labels (NCDOT wording, verbatim), each row's symbol drawn with the section 4 primitives at 0.7 scale:

Column 1 (x = box + 0.15): `MOVING VEHICLE` (hollow arrow) / `PARKED VEHICLE` (rectangle with X) / `PARKING VEHICLE` (X-rectangle with a small arrow leaving) / `MOVABLE OBJECT` (arrow into a dashed-outline square) / `HEAD ON` (two arrows tip to tip at a bar) / `REAR END` (arrow into bar, second arrow onward) / `RAN OFF ROAD` (zigzag arrow) / `DAYLIGHT CRASH` (hollow head) / `NIGHT CRASH` (filled head).

Column 2 (x = box + 2.0): `ANGLE` (vertical arrow down onto a horizontal arrow) / `TURNING` (straight arrow struck by a curving arrow) / `BACKING` (double-headed shaft into a bar) / `SIDESWIPE` (two parallel arrows, lower one jogging up) / `NON-SEVERE INJURY` (arrow, hollow red circle at tip) / `SEVERE INJURY` (half-filled red circle) / `FATALITY` (filled red circle).

Column 3 (x = box + 3.85): `9 MPH OR LESS` / `10 MPH TO 19` / `20 MPH TO 29` / `30 MPH TO 39` / `40 MPH TO 49` / `50 MPH TO 59` / `60 MPH TO 69` (arrows with 0-6 blue dots) / `70 AND UP` (triple-line shaft) / `SPEED UNKNOWN` (blue x on the shaft).

Column 4 (x = box + 5.15): red octagon `STOP SIGN` / blue `A` `ANIMAL` / blue `P` `PEDESTRIAN` / blue `B` `BICYCLE` / blue `T` `TRAIN` / magenta `∗` `DRIVER AT FAULT` / green `D` `DRY` / green `W` `WET` / green `I` `ICY OR SNOWY` / green `O` `OTHER`.

(The 2017 sheet replaces the P and B letters with a magenta and a blue filled arrow; letters are kept here because no non-motorist crashes occur. The STOP SIGN row comes from the two-way-stop sheets SS 05-05-208 and 01-07-200.)

Target-crash key: box (13.1, 2.75) w 2.5 h 0.45: red circle radius 0.11 containing a red `#`, then red 7 pt text `Frontal Impact` / `Target Crashes` on two lines.

---

## 10. Sheet furniture

- **Order block** (upper-left is occupied by the NW leg, so it goes in the open west wedge): left-aligned text at x = 0.8, first baseline y = 5.4, 13 pt, line spacing 1.35: `PH# ________` / `Order# 41000079736` / `NC 180/NC 226 (S Post Rd) at` / `SR 1103 (Pleasant Dr / Pleasant Hill Church Rd)` / `Cleveland County` / `9/1/16 - 8/31/26`. `PH_NO` is a constant, blank until assigned.
- **Figure number**: `FIGURE 3` 10 pt italic, right-aligned at (16.4, 10.33) (above the legend; the package numbers figures 1 location, 2 area, 3 collision diagram, 4 crash locations). Constant `FIGURE_NO`.
- **North arrow**: NCDOT style - circle radius 0.45 centred (15.7, 6.9), 0.8 pt outline, inside it a slender needle 0.7 in long with its right half filled black and left half white, pointing along true north = `pv(0)` = (-0.375, 0.927) on the page (22 deg counter-clockwise from page up); letter `N` 8 pt at the needle's base. No other orientation note is needed.
- **Title block** (lower right): box (13.1, 0.6) w 3.3 h 2.0, rules at 62 %, 42 %, 24 % of its height and a vertical rule splitting the 24-42 % band. Text in DejaVu Serif bold italic, centred: `N.C. DEPARTMENT of TRANSPORTATION` 8.5 pt / `DIVISION of HIGHWAYS` 8.5 pt / `TRANSPORTATION MOBILITY and` + `SAFETY DIVISION` 7.5 pt / `TRAFFIC SAFETY UNIT` 12 pt / `Date: m/d/yyyy` and `Prepared By: <name>` 7 pt in the split band / bottom band empty (consultant logo and "Prepared For:" if a consultant issues the sheet). Constants `DATE`, `PREPARED_BY`.
- **Notes box** (lower left): box (0.8, 0.6) w 5.2 h 2.3, 7 pt, title `NOTES` 8 pt bold:
  1. `Crash numbers correspond to the Acc No. in the TEAAS Intersection Analysis Report, study 41000079736, 9/1/2016 - 8/31/2026. Not to scale.`
  2. `Crash 8 is referenced on SR 1103 at MP 3.019 (0.1 mi W of SR 2205) and was included after the fiche review; drawn on the Pleasant Hill Church Rd approach.`
  3. `Crash 21 is unmileposted ("SR 1103 at SR 1103"); located by DMV-349 coordinates 170 ft from the intersection.`
  4. `Seven fiche crashes (3 animal, 2 fixed object, 1 sideswipe, 1 left turn; all PDO) were excluded in the fiche review and are not shown.`
  5. Summary line: `29 crashes: 0 K, 2 A, 4 B, 3 C, 20 PDO. Frontal impact 22 (76%); night 9 (31%); wet 4 (14%); 13 (45%) in the last 3 yr; 2 three-unit crashes. Entering ADT 12,300 vpd; SI 8.01; EPDO 232.4; 64.6 crashes/100 MEV.` (crash-based counts; values from `review/warrant_check_10yr.txt` and the TEAAS report; recompute from the CSV and assert they match.)
- No scale bar, no crash table, no signal face diagram (unsignalised).

---

## 11. Colour and greyscale policy

| Element | Colour | Greyscale fallback |
|---|---|---|
| Edge lines, centre lines, stop bars, cell shafts, arrowheads, bars, zigzags, number circles (non-target) | black | - |
| Target number circle and number | red #ff0000 | reads as a mid-grey circle; the frontal-impact status is still recoverable from the cell shape |
| Injury circle | red #ff0000 outline/fill | hollow / half / filled still distinguishable |
| Speed dots, triple line, unknown x | blue #0000ff | dark grey dots on a black shaft - keep dots 0.045 in so they stay visible |
| Fault asterisk | magenta #ff00ff | mid grey, shape-distinct |
| Road letter | green #008000 | dark grey letter |
| STOP sign | red fill, white text, black outline | grey octagon with "STOP" |
| Everything else (text, furniture) | black | - |

No yellow anywhere; no colour-by-severity arrows; no filled grey road surfaces (white pavement, black edge lines as on every NCDOT sheet).

---

## 12. Code-to-label tables (verified; DMV-349 code sheets and HSIS NC dictionary; only codes marked * occur in this file)

**SVRTY_CD** (crash worst injury): 1 K Killed / fatal; 2* A Suspected serious injury; 3* B Suspected minor injury; 4* C Possible injury; 5* O No injury (PDO). Drawing: 1 filled red circle; 2 half-filled; 3, 4 hollow; 5 none.

**ACC_TYP** (first harmful event / crash type; the TEAAS Index sheet in `data/41000079736_FicheFirst5.xlsx` and the DMV-349 code sheet "First Harmful Event" column use the same numbering): 0 Unknown; 1 Ran off road - right; 2 Ran off road - left; 3 Ran off road - straight; 4 Jackknife; 5 Overturn/rollover; 6-12 other non-collision events (not listed in the TEAAS Index; take labels from the DMV-349 sheet if they ever appear); 13 Other non-collision; 14 Pedestrian; 15 Pedalcyclist; 16 RR train, engine; 17 Animal; 18 Movable object; 19* Fixed object; 20 Parked motor vehicle; 21* Rear end, slow or stop; 22 Rear end, turn; 23* Left turn, same roadway; 24* Left turn, different roadways; 25* Right turn, same roadway; 26* Right turn, different roadways; 27 Head on; 28 Sideswipe, same direction; 29 Sideswipe, opposite direction; 30* Angle; 31 Backing up; 32 Other collision with vehicle. Only 19, 21, 23-26, 30 occur. Target (frontal impact) = 23, 24, 25, 26, 27, 30. Listing-page spelling for the seven present codes: "Fixed Object", "Rear End, Slow or Stop", "Left Turn, Same Roadway", "Left Turn, Different Roadways", "Right Turn, Same Roadway", "Right Turn, Different Roadways", "Angle".

**LT_COND**: 1* Daylight; 2* Dusk; 3 Dawn; 4* Dark - lighted roadway; 5* Dark - roadway not lighted; 6 Dark - unknown lighting; 7 Other; 8 Unknown. Night (filled head, I-4 warrant) = 4, 5, 6.

**RD_COND**: 1* Dry -> D; 2* Wet -> W; 3 Water (standing/moving) -> W; 4 Ice -> I; 5 Snow -> I; 6 Slush -> I; 7 Sand/mud/dirt/gravel -> O; 8 Fuel/oil -> O; 9 Other -> O; 10 Unknown -> O.

**TRFC_CTRL**: 0 No control present; 1* Stop sign; 2 Yield sign; 3 Stop and go signal; 4 Flashing signal with stop sign; 5 Flashing signal without stop sign; 6 RR gate and flasher; 7 RR flasher; 8 RR crossbucks only; 9 Human control; 10 Warning sign; 11 School zone signs; 12 Flashing stop and go signal; 13* Double yellow line, no passing zone; 14 Other. Not drawn; the sheet's stop control comes from the field/ordinance, not from these codes (13 appears on crashes 5, 11, 12, 15).

**MANEUVER**: 1* Stopped in travel lane; 2 Parked out of travel lanes; 3 Parked in travel lanes; 4* Going straight ahead; 5 Changing lanes or merging; 6 Passing; 7* Making right turn; 8* Making left turn; 9 Making U turn; 10 Backing; 11* Slowing or stopping; 12 Starting in roadway; 13 Parking; 14 Leaving parked position; 15 Avoiding object in road; 16 Other.

**VIOLATION** (contributing circumstance, driver #1): verified for this file - 0* None indicated; 2* Disregarded stop sign; 8* Failure to reduce speed; 14* Overcorrected/oversteered; 19* Failed to yield right of way; 20* Inattention; 26* Operated vehicle in erratic, reckless, careless, negligent or aggressive manner. The remaining codes, read from the DMV-349 code sheet (items 14-19, Contributing Circumstances - Driver), for the listing-page lookup only: 1 Disregarded yield sign; 3 Disregarded other traffic signs; 4 Disregarded traffic signals; 5 Disregarded road markings; 6 Exceeded authorized speed limit; 7 Exceeded safe speed for conditions; 9 Improper turn; 10 Right turn on red; 11 Crossed centerline/going wrong way; 12 Improper lane change; 13 Use of improper lane; 15 Passed stopped school bus; 16 Passed on hill; 17 Passed on curve; 18 Other improper passing; 21 Improper backing; 22 Improper parking; 23 (not captured in the text extract - check the PDF); 24 Improper or no signal; 25 Followed too closely; 27 Swerved or avoided due to wind, slippery surface, vehicle, object, non-motorist; 28 Visibility obstructed; 29 Operated defective equipment; 30 Alcohol use; 31 Drug use; 32 Other; 33 Unable to determine; 34 Unknown; 35-38 Driver distracted (electronic communication device / other electronic device / other inside the vehicle / external distraction). Any non-zero value = driver at fault for the asterisk.

**DIRECT**: N* Northbound (uN); NE Northeast-bound (uN); E* Eastbound (uSE); SE* Southeast-bound (uSE); S* Southbound (uS); SW Southwest-bound (uS); W* Westbound (uNW); NW* Northwest-bound (uNW). At this site N/S are NC 180/NC 226, E/SE are Pleasant Dr -> Pleasant Hill Church Rd, W/NW the reverse.

**NBR_UNT_CNT**: 1*, 2*, 3* units. **UNT_NBR**: 1-3.

---

## 13. QA checklist before issue

1. `assert` counts in section 7 and the summary line in section 10.
2. Clearance check (section 6) reports no pairs under 0.20 in.
3. Every cell's tip set lies inside the neatline and outside all furniture boxes.
4. Print at 11 x 17 and at letter (65 %): number circles and speed dots legible; letters >= 7 pt on the full sheet.
5. Compare with SS 01-07-200 p. 8 side by side: same cell anatomy (circle - asterisk - letter at the tail, dots on the shaft, hollow/filled head, red circle at the tip), same ladder pattern, same legend wording.
6. Fill `PH_NO`, `PREPARED_BY`, `DATE`, `SIDE_SPEED`; confirm lane configuration from the aerial.

---

## 14. Examples reviewed

- NCDOT Traffic Safety Unit, "Collision Diagrams" instruction deck, 1/18/2013 (`reference/collision_diagram_examples/NCDOT_TSU_Collision_Diagram_Instructions_2013.pdf`): slide 24 "Breakdown of Plotted Crash Components" (number circle, fault asterisk, road letter, speed dots, day/night head, injury indicator), slide 25 road/injury/speed key, slide 26 crash-type cells, slides 27-37 plotting rules (ordering by date, miscoded types, sideswipe convention, stacking numbers, insets/blow-up, not to scale, notes, printing), slides 39-41 completed examples.
- Spot Safety evaluation SS 01-07-200, US 158 at SR 1147 (Indiantown Rd), Currituck County, 55 mph two-way-stop crossroads, before diagram p. 8 (`SS_01-07-200_US158_SR1147_Currituck_TWSC_crossroads_2013.pdf`): the layout analog - 23 crashes as two diagonal ladders inside the box, rear ends and fixed object on the approaches, STOP octagons and stop bars, red target circles, "Frontal Impact Target Crashes" key, HMM/TSU title block, ADT and speed per leg.
- SS 05-05-208, US 501 at SR 1601/SR 1468, Durham County, two-way stop with a skewed leg, before/after pp. 8-9 (`SS_05-05-208_US501_SR1601_Durham_TWSC_before_after_2013.pdf`): skew drawn true, north needle rotated, opposing-left-turn cells laid side by side, fixed-object cell into a square on the approach, 2013 two-level injury legend with STOP SIGN row.
- SS 05-06-228, US 401 at SR 1100, Franklin County, skewed two-way stop with islands (`SS_05-06-228_US401_SR1100_Franklin_TWSC_skew_2013.pdf`): lettered insets A/B for dense clusters, Stantec needle north arrow.
- SS 12-06-203, I-40 WB ramp at SR 1007, Catawba County (`SS_12-06-203_I40WB_SR1007_Catawba_insets_2013.pdf`): insets A-D with leaders.
- SS 11-07-204, Surry County (scratch render `se_11-07-204-8.png`): inset box in the lower-left corner with a red leader; AADT labels along skewed legs.
- HSIP collision diagram W-5706A, Order # 41000048689, SR 1400 (Cliffdale Rd), Fayetteville, Figures 1 and 2, AECOM for NCDOT TSU, 10-10-2017 (`W-5706A_Cliffdale_Rd_Collision_Diagram_Figure_1_2017.pdf`, `_Figure_2_2017.pdf`): current legend wording with NON-SEVERE / SEVERE INJURY / FATALITY, "Prepared For" consultant title block, Order#/road/city/county/period block, FIGURE numbering, note boxes, aerial base with 34 x 22 sheet (not adopted here).
- NCDOT 2023 HSIP Overview and TEAAS Chapter 11 Intersection Studies (process references: package contents, 150 ft Y-line, the 22-column Collision Diagram Data File).
- Non-NCDOT sets consulted and not adopted (generic practice; NCDOT wins): AASHTO HSM Ch. 5 Exhibits 5-4/5-5 (ITE MTES), FHWA Road Safety 365 Module 5, FHWA-HRT-04-091 Fig. 49, FDOT Form 750-020-05i, TxDOT TSP 10.3.5.2 Fig. 10-11, Seattle DOT legend, Boston MPO/CTPS, Region of Peel, KYTC D5/D10, SCDOT, Crash Magic, Berkeley TIMS.
- Project drafts: `maps/3_collision_diagram.png` (rejected: 90-deg cross, grid placement, colour-by-severity, text boxes, crash table) and `maps/5_collision_diagram_NCDOT.png` / `collision_diagram.py` (kept as the code base: skew, fillets, STOP/stop bars, legend, title block, cell primitives; replace its layout(), speed_of(), note sizes and add the target key, figure number, notes box, listing page and clearance check).
