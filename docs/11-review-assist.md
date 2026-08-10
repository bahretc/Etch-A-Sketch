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

## Measured against 45 real determinations (2026-08)

The first measurement of the assist itself. 48 crashes were pre-registered in
`examples/samples/assist_eval_sample.csv` before any report was fetched; 47
arrived as a 120-page TEAAS binder; 45 survived redaction (two were refused by
the verifier and excluded rather than downgraded). `decide` ran on each with
the coded fiche fields and the study definition, and never saw the engineer's
call.

**Overall agreement: 14 of 45, 31%.**

| engineer | IS | RE | ADD | DEL | NIS | accuracy |
|---|---|---|---|---|---|---|
| IS (14) | **11** | 0 | 0 | 3 | 0 | 79% |
| RE (16) | 12 | **0** | 0 | 4 | 0 | **0%** |
| ADD (5) | 0 | 0 | **0** | 3 | 2 | 0% |
| DEL (3) | 1 | 0 | 0 | **2** | 0 | 67% |
| NIS (7) | 0 | 0 | 0 | 6 | **1** | 14% |

**RE was never proposed once.** On 12 of the 16 RE rows the assist returned IS,
which means it accepted the coded milepost the engineer had corrected. This is
the same conclusion the fiche arithmetic (7%) and the coordinate work reached
by other routes, now measured on the assist directly: nothing available to it
detects that a coded milepost is wrong. The engineer's own comments say how
they did it, and it is not something in the coded data: "ROR right, NB, placed
at address", "placed in curve".

**The gate does not catch the errors.** `needs_manual` fired on only 22% of the
sample, and **22 of the 31 disagreements would pass unflagged**, 12 of them at
"high" confidence. Confidence is not correctness, restated with a number: the
assist is confidently wrong about half the time and says so about a fifth of
the time.

**NIS is being reported as DEL.** Six of seven NIS rows came back DEL. Both
mean "not in this study", but DEL means struck from an evaluation it was
already in, and they are not interchangeable in a deliverable (docs/03).

Read this as a floor, not a verdict. It is one evaluation, one route, n=45, and
the IS column here comes from a corridor review rather than the 0.12 mile
treatment section, so IS-versus-NIS accuracy is partly an artifact of where the
section boundary was set. Two things are not artifacts: RE at 0% does not
depend on the boundary at all, and neither does the rate of confident
disagreement.

### Why RE is 0%, all the way down (2026-08, second re-run)

Two corrections later the number did not move: 31% with addresses redacted,
**32%** with the redaction scoped correctly and the study limits confirmed from
the source. RE stayed 0 of 16. The redaction fix was still right on its own
terms (all 47 reports now verify clean, where 2 had been blocked by a narrative
address flagged as a leak) and the model does now read the address: one comment
cites "a private drive at 14550 Buffalo Rd". It just does not change the call.

The reason is a chain, and every link is a design decision here:

1. On these reports the location block carries a **municipality** distance and
   no from-road distance. Read off a real page: `on_road='SR 1003'`,
   `municipality='ARCHERS LODGE' 0.8 mi`, `from_road=''`,
   `dist_from_intersection=None`.
2. `location.resolve` therefore cannot derive a milepost, and says so:
   *"a municipality distance is not a milepost"*. That refusal is the guard
   added after the model read "04.20 Miles outside municipality" as MP 4.20.
3. No independent milepost means `resolved_location.milepost` is None.
4. `_RULES` then tells the model, in as many words, that it *cannot establish
   RE* because there is nothing to correct the coded milepost to.
5. So it never proposes RE. Every RE row came back "coded MP within study
   limits", which is the instruction being followed.

**The guard forbids the reasoning the engineer actually uses.** Their own notes
are "placed at address" and "placed in curve": they compare where the report
shows the crash against where the coded milepost points, and call it wrong.
That is a qualitative judgement from the diagram and narrative, not an
arithmetic derivation, and the design admits only the arithmetic kind.

So RE is not blocked by the model, the redaction, or the study limits. It is
blocked by a rule written here to stop one failure (a fabricated milepost) that
also stops the legitimate case.

**Fixed (2026-08).** The rule collapsed two judgements that are made separately:

| judgement | answered by | 
| --- | --- |
| the coded milepost is wrong | the report: diagram, narrative, cross street, address |
| the corrected milepost is 16.94 | a lookup: features report, route geometry, coordinates |

Failing the second does not forbid the first, so the guard moved off the status
and onto the number, where the original hazard actually lives:

* `_RULES` now says RE is a statement about where the crash happened, propose it
  whenever the report puts the crash somewhere other than the coded milepost,
  and cite what puts it there. A null New MP on a proposed RE is correct.
* `_parse` drops any New MP on an RE row when no resolved milepost was supplied,
  because with nothing to read it off, the number can only have come from a
  distance field. The flag names the dropped value.
* Validation runs **last**, after the guards have had their say, so an RE that
  lost its milepost comes back carrying *"RE requires the corrected milepost in
  New MP"* and `needs_manual`. The proposal reaches the engineer; the incomplete
  row cannot reach a workbook.

Net effect: the assist can now say "this one is misplaced, here is why, go look
the milepost up", which is the thing the engineer wanted from it. What it still
cannot do is invent the milepost, which is the thing it must not do.

### Re-measured under the fixed rule (2026-08, third re-run, n=47)

Same 47 reports, same corridor, same harness, all 47 redacted clean with zero
residual. Only the rule changed.

The fix does what it was built to do, and it does not move the number.

| | old rule | fixed rule |
|---|---|---|
| exact agreement | 32% | **30%** (14 of 47) |
| RE proposed | 0 | **5** |
| RE recall | 0 of 16 | 1 of 16 |
| in-study vs not | 72% | 74% |
| `needs_manual` | 30% | 30% |

30 against 32 is one crash at n=47. Nothing moved. What the re-run bought is
not accuracy, it is **visibility**: with the status unblocked, the model's
actual reasoning reaches the output, and three things are now legible that the
old rule was hiding.

**1. Most of the disagreement is vocabulary, not judgement.** Twenty-one of the
33 disagreements get *does this crash belong in the study* right and pick the
wrong word for it: RE→IS 11, NIS→DEL 5, ADD→RE 2, ADD→IS 1, IS→RE 1, DEL→NIS 1.
On the belongs-or-not question the assist runs at **74%**, and that is the
honest statement of what it can currently do. Exact-match at 30% is measuring
vocabulary on top of it.

**2. The dominant RE pattern is one corridor judgement, not sixteen report
judgements.** Eight of the 16 RE rows are a single cluster: seven coded at
17.691 and one at 17.685, every one of them moved to 17.811. MP 17.691 is the
SR 1716 / Lake Wendell intersection; **17.811 is SR 2637 / SR 2638, the next
intersection, 0.12 mi along**. (The features report's fifth column is distance
to the next feature, not an offset for the current one: MERRITT 17.204 + 0.487
= 17.691, LAKE WENDELL 17.691 + 0.120 = 17.811. It does not state the
correction; it only says the two intersections are adjacent.)

The engineer moved a batch of crashes from one intersection to the one next
door. The assist said "belongs in the study" on all eight and IS on seven,
which is defensible for each report taken alone and wrong about the batch. **A
per-report reviewer cannot see a per-corridor correction.** That is
architectural, not a prompt defect: the unit of work is wrong. What evidence
moved those eight is the single most useful thing a worked transcript would
tell us, and this run does not answer it.

**3. ADD has no rule, and it shows.** ADD scored 0 of 5, and all five ADD rows
are coded 999.999 or off the study route entirely. That *is* the working
definition, and docs/03 never says so, so the model cannot apply it. It got the
substance right anyway on three of them, in its own words: *"crash at SR 1716 /
SR 1003 intersection within study limits; coded on SR 1716 with placeholder mp
1000.00"*. That is ADD, described exactly, and labelled RE. Teaching the
distinction (RE = already on the study route at a wrong milepost; ADD = coded
off the study and belongs in it) is the cheapest available correction.

**The guard behaves.** All five RE proposals carried `needs_manual`, the
"look the New MP up" flag, and a null New MP. Not one fabricated milepost.

**`resolve` contributed nothing: 0 independent mileposts on 47 reports.** These
location blocks give a municipality distance, and the resolver additionally
cannot use a named cross street unless a distance from it is also present, so
`at_intersection` is dead as a signal (it is only ever set from
`distance == 0`). Every determination here was made without an independent
milepost.

### Re-measured with the working resolver (2026-08, fourth run, n=47)

Same frozen 47 reports, same harness byte for byte except the output filename;
only the library changed underneath it (mile markers in the inventory, the
route shape from coded crashes, the DetailedFiche coordinate ranked last -
the fixes study 41000079305 forced). Recorded in
`examples/samples/assist_eval_result_v2.csv`.

| | third run | fourth run |
|---|---|---|
| exact agreement | 14 of 47 (30%) | **24 of 47 (51%)** |
| IS (16) | 11 | 12 |
| RE (16) | 1 | 4 |
| ADD (5) | 0 | 1 |
| DEL (3) | 1 | 0 |
| NIS (7) | 1 | **7 of 7** |

The gains generalise: this corridor has no mile markers and the sample no
coordinates, so nothing here was fitted to US 74. What moved is the punting -
the spurious DEL proposals (12 of them in the third run) vanished entirely,
which is what recovered NIS, and RE went 1 to 4 as the resolver started
producing something to compare the coded milepost against.

What did not move, and why, both already diagnosed above:

* **RE at 4 of 16.** Eleven true REs still come back IS: municipality-distance
  location blocks resolve to nothing, so the assist trusts the coded location.
  The corridor data that cracked this on 41000079305 (markers, the DetailedFiche
  crash cloud) does not exist in this study's measurement inputs. The
  per-corridor batch correction (the 17.691 cluster) also still needs the unit
  of work it always needed.
* **DEL at 0 of 3.** The harness predates branch narrowing and never says which
  crashes were in the Initial Study, and DEL only exists on that branch
  (docs/03). The membership is NOT recoverable from the Before/After ID lists
  in examples/04-15-39049 - those are period-scoped final lists, and a crash in
  the construction gap sits in neither while still being IS - it is the
  InitialStudy.pdf strip analysis (study 41000075911, 327 crashes) that
  carries it. Wiring `--initial-ids` into the measurement is the next cheap
  correction, once that export is in hand.

### Study limits: read them, do not infer them

The corridor was inferred from the labels twice. It is stated outright in
`InitialStudy.pdf`, the TEAAS Strip Analysis Report that ships with the
evaluation: *"SR 1003 (Buffalo Road) from SR 1702 (Archer Lodge Road) to the
Wake County Line"*, study 41000075911. The features report gives SR 1702 at
MP 15.154 and `CL-WAKE` at MP 18.941, and the 327 crashes in the initial study
span exactly that. The inferred upper bound (18.911, the last labelled crash)
was 0.03 mi short.

### The first run of this measured the harness, not the assist

Scored at first with the section set to the project's treatment limits
(MP 17.691 to 17.811), agreement was 7%. That was wrong: the reviewed
determinations cover SR 1003 from MP 15.154 to 18.911, a 3.76 mile corridor,
and the 0.12 mile treatment section is a slice of it. Under the narrow
definition an IS crash at MP 15.3 really is outside the section, so the assist
was answering a different question correctly. The tell was in the data: all 29
reviewed NIS rows sit on the side streets (SR 1716, SR 2638) while 191 of 215
IS rows are on SR 1003 inside the corridor.

Two lessons, both already paid for: the study limits are an input the
measurement has to get right, and a result far worse than chance is a signal to
audit the harness before believing it.

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

## What the coordinates are actually like (measured on 14,122 rows)

Run on the full `DetailedFicheBuncombe.csv` (10,243 rows) and
`DetailedFicheMcDowell.csv` (3,879 rows). An earlier version of this section
used 25 rows scraped from a Drive search preview and got two things wrong; both
are corrected here. A preview is the **head** of a file, not a sample of it.

**Coordinates are far scarcer than the preview suggested.** Not "roughly two
thirds" but **35% of Buncombe rows and 18% of McDowell rows**. And the largest
single source is not the report at all:

| source | what it is | Buncombe | McDowell |
|---|---|---|---|
| `CITYOFASHEVILLE_ADDRESSBASED` | municipal address geocoding | 2,701 | 0 |
| `DMV349CLEANED` | the report's boxes, cleaned | 577 | 600 |
| `DMV349` | the report's boxes, raw | 99 | 52 |
| `ITRE_*`, `HSRC_*`, `NCDOT_TSU` | research feeds | ~180 | ~35 |

**5.4% of raw `DMV349` coordinates are corrupt** (8 of 149) - outside North
Carolina entirely. The failures are a longitude carrying the latitude's value
(`-35.58545`) and a longitude with its sign dropped (`82.42702`).
`DMV349CLEANED` had none, so the cleaning step is doing real work.
`location.in_nc` rejects these and `coordinate_consistency` counts them instead
of dropping them silently.

**Two method defects, both mine, found and fixed before reporting.** NCDOT
mileposts restart at county lines, so "I 40 MP 15" exists in both counties
about 40 miles apart; pooling them produced a 2,600 mile "disagreement". And
the corrupt coordinates above skewed every percentile. Corrected, comparing
only within one route in one county:

| route | source | pairs | median gap | 90th pct | under 634 ft |
|---|---|---|---|---|---|
| I 40 (Bun) | `CITYOFASHEVILLE_ADDRESSBASED` | 259,067 | 3,109 ft | 24,704 ft | 14% |
| I 40 (Bun) | `DMV349CLEANED` | 13,618 | 2,064 ft | 6,672 ft | 18% |
| I 40 (McD) | `DMV349CLEANED` | 12,130 | 2,217 ft | 7,768 ft | 17% |
| US 70 (Bun) | `DMV349CLEANED` | 3,238 | 583 ft | 7,930 ft | 52% |
| US 70 (McD) | `DMV349CLEANED` | 1,378 | 455 ft | 2,472 ft | 59% |
| US 70 (Bun) | `CITYOFASHEVILLE_ADDRESSBASED` | 140,492 | 467 ft | 41,045 ft | 59% |
| NC 81 (Bun) | `CITYOFASHEVILLE_ADDRESSBASED` | 1,225 | 358 ft | 9,489 ft | 67% |

**The answer is route-class dependent, which 25 rows could not have shown.** On
freeways the disagreement runs 2,000 to 3,100 ft and only 14 to 18 percent of
pairs agree within 634 ft: coordinates cannot see a remilepost there. On
surface and secondary routes it drops to 358 to 583 ft with 52 to 67 percent
inside the threshold, which is borderline usable. 04-15-39049 was SR 1003, a
secondary route, so the case that matters most is the marginal one rather than
the hopeless one.

**What the gap is not.** It is not pure coordinate error. It is coordinate
error plus coded-milepost error plus the genuine spread of crashes sharing one
coded reference point, which at a freeway interchange is hundreds of feet of
real ground. That is why freeways look worst. Treat it as an upper bound on
coordinate imprecision. The conclusion survives that caveat, because the
question is not what causes the spread but whether a 634 ft correction can be
told apart from it, and on freeways it plainly cannot.

**Where this leaves RE.** Fiche arithmetic cannot find it (7 percent, measured
above). Coordinates cannot find it on freeways, and might on secondary routes
for the fifth or so of crashes that carry a coordinate at all. Neither is a
detector. RE stays a diagram-and-narrative judgment, which is the case for
having the assist read the redacted report.

## Scoring against the engineer

`safety-eval assist-score --proposals proposals.jsonl --workbook reviewed.xlsx`
compares decide-mode proposals with the engineer's reviewed statuses, and the
Review Queue tab carries the same scorer in an expander. The engineer's
determinations are ground truth, full stop: the number measures the assist,
never the review. Output is overall and per-status agreement plus every
disagreement by crash ID with the assist's stated confidence, which is the
list to read when tightening the assist's rules.

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
