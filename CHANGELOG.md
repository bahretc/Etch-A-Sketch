# Changelog

## 0.3.0 (2026-10-10)

- One release for the three NCDOT study types. `safety_eval/criteria.py`
  states each type's criteria (analysis period and its anchor, study limits,
  crash scope, review vocabulary, warrants, AADT rule, inputs, deliverables)
  with a source on every rule; `safety-eval criteria` prints a sheet, checks
  an open study (`--study`), or writes the catalogue (`--all`, which is
  `docs/15-study-criteria.md`, kept in step by a test). The Overview page
  carries the sheet for the open study, an urban/rural context picker for
  an HSIP intersection, and what the study still owes.
- `criteria.analysis_period` computes the N-year pull from the TEAAS data
  currency date the way the study folders do: ending on the last day of the
  most recent complete month, beginning the first of the month N years
  earlier.
- The HSIP warrants run NCDOT's 2026 HSIP Warrants (Traffic Safety Systems
  Section, March 2026): I-1u frontal share 60%, I-2u 40% in the last year,
  I-3u severity index 6.5, I-4u 45% night; the rural and section thresholds
  did not change. The 2024 HSIP Overview stays reachable as edition 2024
  (`warrants --edition`, the Edition picker on the HSIP Warrants page) and
  the screen and the Warrant sheet name the edition they ran. The 2026
  text's new warrants are in: BP-1 (non-motorist intersection, run for a
  Bike/Ped analysis), MB-1 (non-motorist midblock) and B-1 (bridge, 2-lane
  roadways), the last two as opt-in extra tests on a section run
  (`--midblock`, `--bridge`).
- The Traffic Safety Unit fatal crash tooling `fca` (docs/14) is part of the
  distribution: `fca` console script, `fatal` extra, vendor files shipped,
  worked study `examples/260722124BA`, tests.
- The 41000079736 HSIP package work (`examples/41000079736`) and the
  05-08-203 reviewed set-up (`deliverables/05-08-203/reviewed-setup`) are in
  the tree.
- Verified on Python 3.13 with LibreOffice, Tesseract, Playwright Chromium
  and the desktop window present: the whole suite passes.

## 0.2.0b8 and earlier

The fatal slip and HSIP fiche workflows run start to
finish on the CLI and in the app; `docs/13-beta-walkthrough.md` is the
two-page tour and lists the known limits. New in this version: the Start
page has one drop zone. Every file dropped there is recognised from its
content (the TEAAS banner, the header row, the PDF's first page, the
workbook's sheet names; `safety_eval/intake.py`) and filed under its study
role, the study can be created right on the page, a checklist says in words
what the study has, and the Fiche Workbook and Redact pages fill in from
those files so nothing is uploaded twice. Added in 0.2.0b7: the intersection fiche roads and road combination generator (`intersection-roads` on the CLI, and on the Maps and Checks page for intersection sites). Added in 0.2.0b6: the Fiche
Workbook, Review Queue, Evaluation Workbook and AADT pages are laid out as
required then optional steps in plain words, disabled buttons say what they
are missing, and the AADT page prefills from the open study. Added in
0.2.0b5: the app runs
in its own desktop window with no terminal and no browser chrome
(`python -m safety_eval.desktop`), the sidebar puts the study first and the
navigation follows the workflow with nothing folded away, the Overview shows
what the open study already has, fatal and HSIP studies get a Maps and
Checks page, and the Field Investigation builder is parked behind
`SAFETY_EVAL_FIELD_INVESTIGATION=1`. Added in 0.2.0b4: the double click
installer for Windows and Mac (`INSTALL.md`), one current model across the
assist calls. Added in 0.2.0b2: the route
centerline and its curves and crests (`route-features`), the location check
of coded mileposts against report coordinates and geocoded addresses
(`locate-check`), the Location / Area / AADT package maps from a study YAML
(`package-maps`), the strip CalculatedAADT workbook (`calc-aadt`), and two
review rules from live work (off-fiche initial study crashes get a fiche
row; off-LRS rows can be screened NIS).
