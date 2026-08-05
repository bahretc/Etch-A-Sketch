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

## Where the milepost comes from

The fiche carries a coded milepost for every crash: that is the milepost the
study was built on, and it is what places the crash. Nothing has to be derived
to do an ordinary IS or NIS call.

What nothing on the DMV-349 carries is a milepost of its own. The location
block gives a distance from a municipality and a distance from an intersecting
route, and an early run showed what happens when a drafting layer is left to
make something of them: with no resolved location supplied, the model read
"04.20 Miles outside municipality" as milepost 4.20 and called it high
confidence. The real answer for that crash was 2.79.

So the features report is not what places a crash. It is what lets the coded
milepost be **checked**, by working the same location out independently:
MP(from_road) +/- the distance on the form, or the report's own coordinates
interpolated along the route. That check is the whole point, because a coded
milepost the report contradicts is the **RE** case (docs/03).

Which means, precisely:

- with the fiche milepost alone, IS / NIS / ADD / DEL are all judgeable from
  the coded location and what the report shows;
- **RE needs the features report** (or coordinates), because RE disputes the
  coded milepost and the correction cannot come from the fiche it disputes.
  Proposing RE with nothing to correct it to sets `needs_manual`;
- a milepost is never inferred from a distance field, in either direction.

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
Latitude/Longitude boxes are blank, so nothing on that form confirmed the
location independently. Blank boxes turned out to be the exception rather than
the rule; see "What the coordinates are actually like" below.

## The request itself is checked against the live API

The offline suite injects a fake client, so it proves the parsing and the
docs/03 guards and says nothing about whether the Messages API still accepts
what we build. `tests/test_review_assist_live.py` sends one real request and is
skipped unless `ANTHROPIC_API_KEY` is set. It uses a blank synthetic page, so
no report imagery leaves the machine.

It pins the structured-output shape (`output_config.format` with a
`json_schema` carrying `required` and `additionalProperties: false`, both of
which strict mode needs), that the model ID is a current one, and that the
response is not truncated.

That last one is not hypothetical. `max_tokens` caps thinking **plus** the
answer, and a truncated response loses the whole JSON object rather than its
tail. Measured on one page of coded fields and a short narrative: 200 output
tokens on `claude-opus-4-8`, which returned no thinking block, and 460 on
`claude-opus-5`, which thinks by default. A real report with a full diagram
goes higher. `max_tokens` is only billed for what is generated, so the default
is now 4000: headroom is free, truncation is not.

The default model is still `claude-opus-4-8`. `claude-opus-5` is a drop-in at
the same price and the live check passes on it, but the assist has no measured
baseline on either, so switching would trade a known-unmeasured component for
an unknown-unmeasured one. Worth doing alongside the labelled-sample
measurement, not before it.

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

## The features report is an input to the evaluation

It is supplied per analysis, the way the fiche and the assignment are, not
discovered from a folder: the engineer knows which routes the study covers and
which report belongs to it, and picking one by filename would be guessing at
the very step the milepost depends on.

    safety-eval review-assist --features FeaturesReport_US13.pdf \
                              FeaturesReport_NC58.pdf ...

`FeatureInventory.from_files` takes the TEAAS Features Report as a PDF, a text
dump, or a `route,feature,milepost` CSV, and merges several into one inventory,
because a study names more than one route: the road the crash is on, and the
roads it is measured from and toward. The Streamlit review tab has the same
uploader.

Given them, each crash's location block is read off its own redacted page and
resolved before the assist is called, and the resolution is printed beside the
proposal. Without them the run says so, resolves no milepost, and the assist is
told not to infer one.

## Measured against 1,503 real determinations (04-15-39049)

The archived SS section evaluation on SR 1003 carries 2,315 reviewed rows with
the engineer's own calls: 1,968 NIS, 215 IS, 102 RE (every one with a New MP),
21 ADD, 9 DEL. Its 1,503 SR 1003 rows were resolved from the fiche's own
location fields against that folder's SR 1003 features report.

**The resolver reproduces the coded milepost.** 1,351 of 1,503 rows resolved,
median error 0.003 mi, 98 to 99 percent inside 0.06 mi. That validates the
features-report parsing, the route-name matching, the from/toward sign rule and
the arithmetic at a scale no hand check reaches. The 152 that did not resolve
are mostly a from-road absent from that route's features report, which is
itself worth seeing.

**But disagreement does NOT find RE rows, and that was worth proving.** The
hypothesis was that where the resolver and the coded milepost disagree, the
engineer would have remileposted. It does not hold:

| determination | n | median abs difference | within 0.06 mi |
|---|---|---|---|
| IS | 181 | 0.004 | 99.4% |
| NIS | 1067 | 0.003 | 98.5% |
| **RE** | **99** | **0.001** | **97.0%** |

RE rows agree with the coded milepost as closely as everything else. On those
same rows the resolver lands within 0.06 mi of the engineer's corrected New MP
only **7 percent** of the time, median error 0.121 mi.

The reason is structural: TEAAS derives the coded milepost from the same
from-road and distance the resolver uses, so the resolver reproduces TEAAS,
including where TEAAS is wrong. The engineer's correction comes from something
the fiche does not contain, which is the DMV-349 diagram, narrative and
coordinates.

So **RE cannot be detected from the fiche.** It needs the report. That is not a
gap in the resolver, it is the reason the assist reads the redacted report at
all, and it is why the report's Latitude/Longitude boxes matter more than they
first appear: they are the one independent milepost on the page.

## What the coordinates are actually like (2026-07, preliminary)

Two claims above were written off two reports and are wrong at the population
level. Correcting both.

**The Latitude/Longitude boxes are usually filled.** The DetailedFiche carries
`Municipality, On Road, Miles, Dir From, From Road, Toward Road, Milepost Road,
MP, MA, Crash ID, Date, T, C, F, L, S, Latitude, Longitude, Source`, and the
`Source` column names where each coordinate came from. The dominant value is
`DMV349CLEANED`, meaning NCDOT harvests the report's own boxes and cleans them,
with `DMV349` raw and a minority from research feeds (`ITRE_CMV`, `HSRC_PED`,
`HSRC_BIKE`, `ITRE_SEVEREINJURY`). Roughly two thirds of rows carry
coordinates; blanks cluster on municipal and non-mileposted (MP 999.999) rows
and on older crashes, which is the wrong half for a before period.

**But they may not be precise enough to find a remilepost.** Measured
model-free on I-40 rows from the Buncombe and McDowell DetailedFiche: for pairs
of crashes close together in coded milepost, compare the straight-line distance
between their coordinates against the difference in their mileposts. A freeway
is locally straight, so the gap is coordinate error and coded-milepost error
combined, with no route geometry fitted and no features report needed.

| source of the coordinates | pairs | median gap | 90th pct | max | under 634 ft |
|---|---|---|---|---|---|
| research feeds (Buncombe) | 28 | 1584 ft | 6631 ft | 7870 ft | 8/28 |
| `DMV349` / `DMV349CLEANED` (McDowell) | 6 | 877 ft | 1425 ft | 1597 ft | 1/6 |

Both medians are larger than the **634 ft** median correction the engineer
actually makes (measured on 04-15-39049), which is the number that has to be
beaten. Two Buncombe crashes coded at the identical milepost 9.200 sit 7870 ft
apart on the ground; two coded 32 ft apart sit 2130 ft apart.

The measurement re-runs on a real fiche as::

    from safety_eval.location import coordinate_consistency
    from safety_eval.review_queue import read_detailed_fiche

    coordinate_consistency(read_detailed_fiche("DetailedFicheMcDowell.csv"))

Building that path turned up a bug worth knowing about separately from any of
this. `parse_coordinates`, which feeds the GPS pre-screen that docs/03 makes
the first step of a fiche review, split delimited text on the delimiter. The
real DetailedFiche export quotes every field, so the quote characters stayed
attached, no crash ID passed `isdigit()`, no coordinate passed `float()`, and
the function returned an empty dict. Not an error, just no coordinates, so the
queue would have fallen back to milepost ordering and looked like it was
working. The `.xlsx` fiche workbook was unaffected, which is why the tests
never caught it: openpyxl hands back typed values. Both readers now go through
the csv module.

Read this as a caution, not a result. n is 25 rows transcribed out of a search
preview of the head of each file, so it is neither large nor a random sample,
and the gap does not separate a noisy coordinate from a genuinely wrong
milepost, which is the very thing being looked for. What it does establish is
that the coordinate path is not the easy win it looks like, and that
`Source` matters: report-derived coordinates were roughly twice as consistent
as research-feed ones, so any use of them should filter on it. An earlier pass
that fitted a route through the crash points themselves gave much worse numbers
still, but that measured the route fit rather than the coordinates and should
be ignored; its own scale check came out at 4899 ft per milepost.

Before any of this is built on, run it on the full files:
`DetailedFicheBuncombe.csv`, `DetailedFicheMcDowell.csv` and the 13-18-210
(SS-4913CX) workbook, which together carry coordinates, features reports and
the engineer's own RE calls on the same route.

## Still to build

- **A geocoder.** `GazetteerGeocoder` reads an address point file already on
  disk; an online locator can be dropped in behind the same `Geocoder`
  protocol. Without either, a street reference is carried through unplaced.
- **Confidence that means something.** It is the model's own word for now, and
  it has been wrong; the gates are what hold.

## What the pipeline does end to end (verified on a real report)

    page image
      -> form_geometry: identity zones covered, location block read by position
      -> location.read_location_block: on US 13, from SR 1132 toward SR 1142,
         0.80 mi; municipality Snow Hill 4.20 mi (a town distance, not a milepost)
      -> location.resolve + the folder's FeaturesReport_US13.pdf
         (SR 1132 at MP 1.993, SR 1142 at MP 2.983)
      -> US 13 milepost 2.79, shown as MP(SR 1132) + 0.80 toward SR 1142
      -> review_assist: the milepost is given, never inferred

Nothing in that chain is hand-filled, and the "4.20" the first run mistook for
a milepost is extracted, labelled a municipality distance, and never used as
one.
