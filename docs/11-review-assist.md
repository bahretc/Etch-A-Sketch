# 11 - Review assist (LLM help on the IS/NIS/ADD call)

How the assistant helps with a fiche determination, what it is allowed to see,
and what it was measured doing on a real DMV-349. The rules it applies are
docs/03; this file covers the mechanism and its limits.

## Two modes, chosen by the engineer

`safety_eval/review_assist.py`, `safety-eval review-assist --mode ...`, and the
Streamlit review tab all offer the same choice per crash:

- **decide** - works out where the crash occurred from the diagram, narrative
  and coded fields, applies the 150 ft rule (or the section milepost rule), and
  proposes one determination with its evidence and a confidence.
- **prepare** - makes no call. It lays out the diagram read, the narrative
  read, where the report places the crash, the distance assessment, the
  governing rule, plausible statuses and a draft comment, and leaves the status
  blank so the engineer decides unanchored.

Either way it is a proposal. `apply_determinations` re-validates against
docs/03 before anything is written, every accepted call lands in the audit
trail, and the PE decides and seals. Low confidence, an invalid status, a
refusal or a missing report all set `needs_manual`.

## What it is allowed to see

Only **redacted** pages. `assist()` raises unless the caller passes
`redacted=True`, and the pages it takes are `binder.render_crash_pages`
output, which runs the docs/06 redaction pass first. Raw DMV-349 imagery never
reaches a model.

This is why the redaction work in `form_geometry.py` matters to the assist and
not just to privacy: the identity blocks are covered by field position, while
the **diagram, narrative, location block and coded field grid stay legible**.
A redactor that blacked the narrative would leave the assist with nothing to
reason from.

The GPS pre-screen distance passed in `StudyContext.prescreen_ft` comes from
the DetailedFiche, never from the report. Taking coordinates off the report
would make the screen circular: the report is the thing being checked.

## The milepost must be resolved, never inferred

Nothing on the DMV-349 is a milepost. The location block gives a distance from
a municipality and a distance from an intersecting route; converting either one
needs the features report. `location.py` does that conversion and the assist is
handed the answer, because a first run showed what happens otherwise: with no
resolved location supplied, the model read the "04.20 Miles outside
municipality" field as milepost 4.20 and reported **high confidence**.

That was a design fault, not a model quirk. The prompt now states the rule and
carries `StudyContext.resolved_location`; when no features report is available
it says so and forbids inferring one. The fiche milepost is passed as the value
being **checked**, not restated.

## Measured on a real report (2026-07)

One archived DMV-349 (single vehicle, ran off US 13 into a ditch, no
intersection involved), redacted by field geometry and verified clean.

**Intersection study, US 13 at SR 1132, 150 ft buffer.** `decide` returned
**NIS**, high confidence, comment `0.80 mi from SR 1132, no intersection in
diagram`, citing the absent cross street in the diagram and the coded distance.
That call is well evidenced and needed no milepost.

**Section study.** Read the first run as a caution about test design, not a
result: the milepost range used was chosen around a number already visible on
the report, so the match was invited. A later run fixed that by putting the
features report's `SR 1132` at MP 7.30, making the correct answer MP 8.10 and
any appearance of "4.20" a fabrication. With the features report the assist
returned MP **8.10** and cited `MP(SR 1132)=7.30 + 0.80 mi toward SR 1142`;
with no features report it returned no milepost, `needs_manual`, and the
comment `milepost cannot be confirmed without features report`.

`prepare` returned no status in every run, and raised two points a reviewer
would want: the crash is a run-off-road-right, so it is **not** in the
frontal-impact target set for an AWSC study and **not** a centerline crossing
for a centerline rumble strip study (docs/03 correctability); and the report's
Latitude/Longitude boxes are blank, so nothing on the form confirms the
location independently.

## Limits worth knowing

- **A status can still be unjustified.** In the no-features-report run the
  assist proposed IS for a milepost-dependent section study while stating it
  could not establish the milepost. `needs_manual` gates it out of one-click
  acceptance, but the status itself was not defensible. Treat `decide` output
  as a claim to check, and prefer `prepare` where the location is weak.
- **Confidence is not correctness.** The fabricated milepost came back "high".
- **It reads what the redactor left.** A value the redaction covered is
  invisible to it, and a poor scan is invisible to both.
- Names scrubbed out of a narrative occasionally take an ordinary word with
  them when it matches a harvested name.

## Still to build

- **Reading the location block by geometry.** `location.py` resolves a
  `ReportLocation`, but nothing yet fills one from the page; the fields were
  supplied by hand for the runs above. The zone map in `form_geometry.py` is
  where those boxes belong, alongside the ZIP fields already measured there.
- ~~A real features report.~~ **Done.** Every assignment folder carries the
  TEAAS Features Reports for its routes (136 of them across 58 archived
  evaluations), and `FeatureInventory.from_features_report` parses that format
  directly; `from_csv` remains for hand-built inventories. The manifest now
  classifies them under `files.features`, which it previously ignored.

  Checked against the real US 13 (Greene) report: SR 1132 is at MP 1.993 and
  SR 1142 at MP 2.983, so the crash used in the runs above, "0.80 mi from
  SR 1132 toward SR 1142", is at **MP 2.79**. Not 4.20. The parsed span
  between the two also matches the report's own distance-to-next column
  (0.990), which is an independent check on the parse.
- **Address geocoding.** A street reference is carried through with no
  milepost; placing it on a route needs a geocoder.
