# 03 - Crash Review Rules

This is the domain logic. Encode it exactly; do not improvise.

## Status vocabularies

Standalone fiche workbooks use IS / NIS / ADD / ?.

Evaluation Filtered Fiche sheets (corrected 2026-07, per the engineer; this supersedes an earlier note that described a REV status):

- **Intersection analyses**: IS / ADD / DEL / NIS, with NIS split into Reviewed and Not Reviewed sections.
- **Section analyses**: IS / RE / ADD / DEL / NIS (Reviewed and Not Reviewed). **RE = re-milepost**: the crash is in the study with a corrected milepost recorded in the New MP column (observed on 04-15-39049: every RE row carries a New MP).
- **DEL**: removed from the evaluation.

In-study statuses for binning purposes are IS, ADD, and RE. All determinations about which reports to review are made in the Filtered Fiche; the Binned Crashes sheet only sorts the evaluation's crashes into period bins using those determinations. The review standard below applies to all vocabularies.

## IS / NIS / ADD / ? determination (intersection studies)

- **IS** (in study): crash occurred at or within 150 feet of the study intersection. IS crashes marked for review must be confirmed against the DMV-349 report (diagram + narrative), not taken from the coded milepost alone.
- **NIS** (not in study): confirmed not at and not within 150 feet.
- **ADD**: coded elsewhere but the report shows it actually occurred at the study intersection; add it to the study.
- **?**: unresolved; requires report review. A "?" may only become NIS after the actual DMV-349 diagram and narrative confirm the coded location is right and the crash is outside the 150 ft buffer. Blanket reclassification without report review is not acceptable.
- **Animal crashes are ignored** in the IS/? review (no report review needed).
- Coded location can be deceptive: identical-looking cross streets exist (example: two US 17 / Deppe Loop junctions 1.3 miles apart). When a diagram superficially matches the study intersection, verify with the report's coordinates on the front page.

## Comment conventions (fiche status column)

- Brief; do not restate information already in the workbook (do not repeat a distance the row already shows unless it is wrong).
- Acceptable patterns: `no intersection in diagram`, `>150'`, `at [road]` for a different cross street, `at southern Deppe Loop/US 17 per coords` style when coordinates resolved it.

## Target crashes

- Defined per evaluation from the countermeasure; the definition is stated on the results sheet and in the assumptions email. The workbook's **Typical Target Crash Types** sheet is the authoritative source for definitions; read it before assuming.
- AWSC conversions: frontal impact set (Angle, LTSR, LTDR, RTSR, RTDR, Head-On).
- VEWF (vehicle-entering-when-flashing): only crashes involving vehicles from the treated approaches count (Angle, LTDR, RTDR). Same-roadway types (LTSR, RTSR, Head-On) are excluded because the flashers are not visible to vehicles traveling on the same roadway.
- Flag with "Y" in Target-1? on the Before/After sheets. Second target type uses Target-2?; blank when only one target is defined.
- Secondary-crash evaluations: consecutive crashes within 3 hours at the location count as the target.

## Correctability (rumble strip / resurfacing sections)

- The Typical Target Crash Types sheet carries per-treatment correctability definitions (observed at J17: centerline rumble strips, first event crossed the centerline; J18: edgeline rumble strips, first event crossed the edgeline).
- Dual centerline + edgeline treatment: a crash is correctable if the first event crossed either line, so right-side drift departures count. Applying only the centerline test on a dual-treatment project undercounts; this was a real correction on SS-6002M.
- Resurfacing component: wet-condition crashes are correctable; icy/snowy are not.
- Standing exemptions from correctable: mechanical failure, medical event, avoidance maneuver.

## Lane departure direction (section rumble strip evaluations)

- Classify each lane departure crash as **CL** (centerline: first-event path crosses the centerline into the opposing side) or **R** (ran off own/right side without crossing).
- **First harmful event rule**: when narrative and coded/stored values conflict, the stored value keyed to the first harmful event governs (multi-event sequences like right/overcorrect/cross still classify by the first event).
- **Side-street run-throughs are excluded from the lane departure target set**: a vehicle from a side road crossing the study route at a terminal intersection is not a study-route departure. Remove the Target flag and the departure classification everywhere it appears, keep the crash in Total Crashes as a non-target, and document the rationale in the comment field.
- Crashes with no report in the fiche batch stay as stored and are flagged unverifiable.

## Periods and binning

- Binned Crashes banners: Prior to the Before Period, Before, Construction, After, then NIS crashes with reviewed reports and NIS crashes without reviewed reports, kept as separate sections so the review coverage is auditable.
- Construction is excluded from before/after comparisons but its crashes are reviewed and mentioned in Items for Discussion.
- Prefer symmetric before/after windows (e.g. 3.58 years each around a mid-2022 completion).
- Period math: years = (end - start)/365.25.
- Every crash in the filtered fiche lands in exactly one bin or is excluded with a reason.

## QC habits

- Recount before delivering; tallies quoted in text must match the sheets exactly (a 13 vs 14 discrepancy is a real defect).
- When correcting a prior classification, trace every location the value appears (target flag, departure ledger, per-section counts, results sheet) and update all of them.
- Judgment calls that stay as stored get flagged to the engineer with a short rationale rather than silently resolved.
