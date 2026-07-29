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

## Measured on a real report (2026-07)

One archived DMV-349 (single vehicle, ran off US 13 into a ditch, no
intersection involved) was redacted by field geometry, verified clean by
`verify_redaction`, and then run in both modes against two study contexts. The
same crash correctly reverses on the study type, which is the behaviour that
matters: the call follows the study definition, not the shape of the text.

| Study context | decide | Comment it drafted |
|---|---|---|
| Intersection, US 13 at SR 1132, 150 ft | **NIS**, high confidence | `0.80 mi from SR 1132, no intersection in diagram` |
| Section, US 13 MP 4.00 to 5.00 | **IS**, high confidence | `MP 4.20 within study 4.0-5.0, ran off road into ditch` |

Both comments follow the docs/03 conventions without being told the patterns.
`prepare` returned no status in both runs, offered `[NIS, DEL]` and
`[IS, RE, DEL]` as candidates, and raised two points a reviewer would want:

- the crash is a run-off-road-right, so it is **not** in the frontal-impact
  target set for an AWSC study, and **not** a centerline crossing for a
  centerline rumble strip study, in both cases telling the engineer to confirm
  target relevance (docs/03 correctability);
- the report's Latitude/Longitude boxes are blank, so the location rests on the
  coded milepost and the narrative, with nothing to confirm it against.

## Limits worth knowing

- **It reads what the redactor left.** A value the redaction covered is
  invisible to it, and a poor scan is invisible to both.
- **A distance field is not a milepost.** In the section run it treated the
  coded `04.20` as milepost 4.20. That is an interpretation of a
  distance-from-municipality field, and the engineer confirms it; `prepare`
  flagged the same gap on its own.
- **Confidence is not correctness.** Both runs came back "high"; the gates and
  the engineer, not the confidence, are what stand between a draft and a
  deliverable.
- Names scrubbed out of a narrative occasionally take an ordinary word with
  them when it matches a harvested name.
