"""LLM-assisted fiche-review determinations (docs/03 rules, docs/07 Phase 3+5).

Reads the REDACTED DMV-349 pages for one crash together with its coded fiche
fields and the study context, and helps the engineer with the IS / NIS / ADD /
DEL (/ RE) call in one of two engineer-selected modes:

* ``decide``  - the assistant works out WHERE the crash occurred from the
  diagram, narrative and coded data, applies the 150 ft rule (or the section
  milepost rule), and proposes a determination with its evidence. It is still
  a proposal: the engineer accepts or overrides, and the write-back path
  re-validates it (docs/03). Nothing here ever seals a status.
* ``prepare`` - the assistant makes NO call. It lays out the evidence (report
  fields, a plain read of the diagram and narrative, where the report places
  the crash, the distance assessment, the governing rule) and a draft comment,
  and leaves the status blank so the engineer decides unanchored.

Two invariants, by construction:

1. **Redact-first.** This module only ever sees the images the caller passes,
   which must already be redacted (``binder.render_crash_pages`` /
   ``redact`` output). ``assist`` refuses to run unless the caller asserts
   ``redacted=True``; raw crash-report imagery must never reach the model.
2. **Prepares, never decides.** Even in ``decide`` mode the result is a
   proposal carrying its evidence; the engineer decides and seals, and
   ``apply_determinations`` validates again before anything is written.
"""
from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field

from .review_queue import (STATUS_VOCAB, Determination, branch_vocab,
                           validate_determination)

#: cap per-page raster before sending to the model (longest side, px) and the
#: number of pages, so a supplemental-heavy report stays a sane request.
MAX_IMAGE_SIDE = 1600
MAX_PAGES = 4
DEFAULT_MODEL = "claude-opus-4-8"

#: ``max_tokens`` is a ceiling on thinking PLUS the answer, and it is only
#: billed for what is generated, so headroom is free and truncation is not.
#: Measured live on one page of coded fields and a short narrative: 200 output
#: tokens on claude-opus-4-8 (no thinking block), 460 on claude-opus-5 (which
#: thinks by default).  A dense report with a full diagram goes higher, and a
#: truncated response loses the whole JSON object, not just its tail.
DEFAULT_MAX_TOKENS = 4000

MODES = ("decide", "prepare")


@dataclass
class StudyContext:
    """The study a crash is being reviewed against (all engineer-supplied)."""
    name: str = ""
    analysis_type: str = "intersection"        # intersection | section
    buffer_ft: int = 150                       # the intersection IS buffer
    study_point: tuple | None = None           # (lat, lon), if known
    mp_range: tuple | None = None              # (lo, hi) for sections
    target_definition: str = ""                # from the assignment / results sheet
    prescreen_ft: float | None = None          # DetailedFiche distance (NOT the report's)
    #: Location resolved from the report's location block against the features
    #: report (``location.resolve``). Supplied so the assistant is never left
    #: to work a milepost out of a distance field, which it must not do.
    resolved_location: object | None = None
    fiche_milepost: float | None = None         # what the study was built on
    #: Was this crash in the Initial Study? This is not a judgement and must not
    #: be inferred from the coded milepost: crashes coded on a cross street at
    #: MP 1.44 were in the study, and approximating the flag from the milepost
    #: mislabelled 5 of 47 on the real sample. It is membership in the initial
    #: crash list, which the caller already has. None means unknown, and the
    #: full vocabulary stays open.
    in_initial_study: bool | None = None


@dataclass
class AssistResult:
    """The assistant's output for one crash; a proposal, never a decision."""
    crash_id: str
    mode: str
    # decide-mode fields (None/empty in prepare mode)
    proposed_status: str | None = None
    new_mp: float | None = None
    at_study_location: bool | None = None
    where_occurred: str = ""
    confidence: str = ""                        # low | medium | high
    # shared / prepare-mode fields
    comment: str = ""                           # draft comment (decide: for the status; prepare: candidate)
    diagram_summary: str = ""
    narrative_summary: str = ""
    report_location: str = ""
    distance_assessment: str = ""
    applicable_rule: str = ""
    candidate_statuses: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    needs_manual: bool = False                  # report missing / low confidence / invalid
    validation_problems: list = field(default_factory=list)
    note: str = ""

    def as_determination(self) -> Determination | None:
        """The proposed Determination (decide mode only), or None."""
        if self.mode != "decide" or not self.proposed_status:
            return None
        return Determination(crash_id=self.crash_id, status=self.proposed_status,
                             new_mp=self.new_mp, comment=self.comment or None)


# --------------------------------------------------------------------------- #
# prompt assembly
# --------------------------------------------------------------------------- #
_RULES = """\
NCDOT crash-review rules you must follow exactly (docs/03); do not improvise:
- The vocabulary is NOT a flat five-way choice. It is two branches, and which \
branch applies was fixed before you saw the crash, by one fact: was the crash \
in the Initial Study? You are told below which branch you are in. Never answer \
outside it.
- IN the Initial Study, the crash starts as IS and the only questions are \
whether the coded milepost is right and whether it belongs at all:
    IS  = it belongs and the coded milepost is right.
    RE  = it belongs but the coded milepost is wrong (section analyses only; \
the corrected milepost goes in New MP).
    DEL = it does not belong in the study area, so it is deleted from it.
- NOT in the Initial Study, the crash is a candidate and the only question is \
whether it belongs:
    ADD = the report shows it IS in the study area, so it is added.
    NIS = the report shows it is not, filed under "NOT IN STUDY - REPORT \
REVIEWED".
- So the moves run one way only. IS can become RE; RE never becomes IS. DEL and \
NIS both read as "not in this study" and are NEVER interchangeable, because \
they start from opposite branches. Nor are ADD and RE.
- Intersection IS = the crash occurred AT or within the study buffer (default \
150 ft) of the study intersection, confirmed by the DMV-349 diagram and \
narrative, not the coded milepost alone. NIS = confirmed not at and not within \
the buffer.
- Coded location can be deceptive: identically named cross streets exist a \
mile or more apart. When a diagram superficially matches, confirm with the \
report's front-page coordinates.
- Animal crashes are ignored in this review (no report review needed).
- NOTHING on the DMV-349 is a milepost. "N Miles outside municipality" is a \
distance from a town and "N Miles from <route>" is a distance from an \
intersecting route. Do NOT convert either into a milepost yourself.
- The milepost the study was built on is the one CODED ON THE FICHE, and it is \
given to you below. Use it. The report is being checked against it.
- A resolved milepost, when given, is an INDEPENDENT reading of the same \
location, worked out from the features report or the report's coordinates. Its \
job is to confirm or contradict the coded one.
- RE is a statement about WHERE THE CRASH HAPPENED, not a piece of arithmetic. \
Propose it whenever the report puts the crash somewhere other than the coded \
milepost, and say in the evidence what puts it there: the intersection drawn in \
the diagram, the address in the narrative, the coordinates, the officer's \
description. You do NOT need the corrected milepost in hand to make that call.
- The corrected milepost is a separate question with a separate answer. Fill in \
new_mp only when a resolved milepost is given above, or when the corrected \
location can be read straight off the features report. Otherwise leave new_mp \
null, set needs_manual, and say in the comment what the engineer should look the \
milepost up against. A null New MP on a proposed RE is expected and correct. A \
New MP you worked out from a distance field is not, ever.
- Comments are brief and plain: no em dashes, and do not restate a value the \
row already shows. Acceptable patterns: "no intersection in diagram", ">150'", \
"at [road]", "per coords".
You assist a licensed PE. You never finalize a status; the engineer decides \
and seals. Base every statement on the coded data and the report images; if \
the report does not resolve the location, say so and defer."""

_DECIDE_SYS = _RULES + "\n\nMode: DECIDE. Determine where the crash occurred " \
    "and propose the single most defensible determination, with the evidence " \
    "that supports it. If the report cannot resolve it, set needs_manual and " \
    "keep confidence low."

_PREPARE_SYS = _RULES + "\n\nMode: PREPARE. Do NOT choose a status. Lay out " \
    "the evidence and a draft comment so the engineer can decide. List the " \
    "plausible statuses in candidate_statuses without picking one."


def _decide_schema(analysis_type: str, in_initial_study: bool | None = None) -> dict:
    # The enum is narrowed to the crash's branch, so an off-branch status is not
    # discouraged, it is unrepresentable. On the real sample 15 of 47 calls were
    # off-branch and 12 of those were wrong.
    vocab = list(branch_vocab(analysis_type, in_initial_study))
    return {
        "type": "object",
        "properties": {
            "where_occurred": {"type": "string"},
            "at_study_location": {"type": "boolean"},
            "proposed_status": {"type": "string", "enum": vocab},
            "new_mp": {"type": ["number", "null"]},
            "comment": {"type": "string"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "needs_manual": {"type": "boolean"},
        },
        "required": ["where_occurred", "at_study_location", "proposed_status",
                     "comment", "confidence", "evidence"],
        "additionalProperties": False,
    }


_PREPARE_SCHEMA = {
    "type": "object",
    "properties": {
        "diagram_summary": {"type": "string"},
        "narrative_summary": {"type": "string"},
        "report_location": {"type": "string"},
        "distance_assessment": {"type": "string"},
        "applicable_rule": {"type": "string"},
        "draft_comment": {"type": "string"},
        "candidate_statuses": {"type": "array", "items": {"type": "string"}},
        "flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["diagram_summary", "narrative_summary", "report_location",
                 "distance_assessment", "applicable_rule", "draft_comment"],
    "additionalProperties": False,
}


def _coded_view(row) -> dict:
    """The coded fiche fields the model may look at (no PII in the fiche)."""
    keep = ("crash_id", "date", "t", "c", "f", "l", "s", "crash_type",
            "on_road", "from_road", "toward_road", "mp", "miles", "status",
            "section")
    return {k: row.fields.get(k) for k in keep if row.fields.get(k) not in (None, "")}


def _context_block(row, ctx: StudyContext) -> str:
    lines = [f"Study: {ctx.name or '(unnamed)'}",
             f"Analysis type: {ctx.analysis_type}"]
    if ctx.analysis_type == "intersection":
        lines.append(f"IS buffer: {ctx.buffer_ft} ft")
        if ctx.study_point:
            lines.append(f"Study point (lat,lon): {ctx.study_point[0]}, {ctx.study_point[1]}")
    else:
        if ctx.mp_range:
            lines.append(f"Study mileposts: {min(ctx.mp_range)}–{max(ctx.mp_range)}")
    if ctx.target_definition:
        lines.append(f"Target crashes: {ctx.target_definition}")
    rl = getattr(ctx, "resolved_location", None)
    if rl is not None:
        lines.append("Resolved crash location: " + rl.summary())
        for note in getattr(rl, "notes", [])[:4]:
            lines.append(f"  - {note}")
    else:
        lines.append(
            "Resolved crash location: NOT AVAILABLE. No features report was "
            "supplied, so the coded milepost below has not been independently "
            "checked. You can still tell from the report whether the crash "
            "happened where the coded milepost puts it. If it did not, that is "
            "RE: propose it, cite what the report shows, and leave new_mp null "
            "for the engineer to look up. Do not infer a milepost from a "
            "distance field.")
    if ctx.fiche_milepost is not None:
        lines.append(f"Milepost coded on the fiche: {ctx.fiche_milepost:.2f} "
                     "(this is what the study was built on; the report is "
                     "being checked against it, not used to restate it)")
    if ctx.prescreen_ft is not None:
        lines.append(f"GPS pre-screen distance (from the DetailedFiche, not the "
                     f"report): {ctx.prescreen_ft:.0f} ft")
    if ctx.in_initial_study is None:
        lines.append("In the Initial Study: UNKNOWN. The caller did not say, so "
                     "the full vocabulary is open and you must reason about "
                     "which branch applies before choosing.")
    else:
        lines.append(
            "In the Initial Study: "
            + ("YES. This crash is already in the study, so the question is "
               "whether the coded milepost is right and whether it belongs."
               if ctx.in_initial_study else
               "NO. This crash is a candidate, so the only question is whether "
               "the report puts it in the study area."))
    lines.append("Status vocabulary you may use, and nothing else: "
                 + ", ".join(branch_vocab(ctx.analysis_type,
                                          ctx.in_initial_study)))
    return "\n".join(lines)


def _image_blocks(pages) -> list[dict]:
    """Redacted PIL pages -> Anthropic base64 image content blocks."""
    blocks = []
    for img in pages[:MAX_PAGES]:
        im = img
        if max(im.size) > MAX_IMAGE_SIDE:
            scale = MAX_IMAGE_SIDE / max(im.size)
            im = im.resize((max(1, int(im.size[0] * scale)),
                            max(1, int(im.size[1] * scale))))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/png",
            "data": base64.b64encode(buf.getvalue()).decode("ascii")}})
    return blocks


def build_request(row, ctx: StudyContext, pages, mode: str,
                  model: str = DEFAULT_MODEL,
                  max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
    """Messages-API params for one assist call (decide or prepare)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    system = _DECIDE_SYS if mode == "decide" else _PREPARE_SYS
    schema = (_decide_schema(ctx.analysis_type, ctx.in_initial_study)
              if mode == "decide" else _PREPARE_SCHEMA)
    text = ("Coded fiche fields:\n"
            + json.dumps(_coded_view(row), indent=1)
            + "\n\n" + _context_block(row, ctx)
            + f"\n\nThe {len(pages)} redacted DMV-349 page(s) follow. Review the "
            "diagram, the narrative and the coded fields, then respond in the "
            "required JSON shape.")
    content = [{"type": "text", "text": text}] + _image_blocks(pages)
    return {
        "model": model, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": content}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }


# --------------------------------------------------------------------------- #
# the assist call
# --------------------------------------------------------------------------- #
def _parse(data: dict, row, ctx: StudyContext, mode: str) -> AssistResult:
    res = AssistResult(crash_id=row.crash_id, mode=mode)
    if mode == "decide":
        res.where_occurred = data.get("where_occurred", "")
        res.at_study_location = data.get("at_study_location")
        res.proposed_status = data.get("proposed_status")
        # New MP belongs to RE rows only (docs/03): in the delivered workbooks
        # every RE row carries one and no other row does, and
        # apply_determinations would otherwise write a milepost onto an IS row.
        base = (res.proposed_status or "").split("-")[0]
        res.new_mp = data.get("new_mp") if base == "RE" else None
        if base != "RE" and data.get("new_mp") is not None:
            res.flags.append("model returned a New MP on a non-RE status; "
                             "dropped (New MP is the RE field)")
        res.comment = data.get("comment", "")
        res.confidence = data.get("confidence", "")
        res.evidence = list(data.get("evidence", []))
        res.needs_manual = bool(data.get("needs_manual", False))
        # Section analyses are milepost-dependent (docs/03). Without a resolved
        # milepost, and with none coded on the fiche, IS and RE have nothing to
        # stand on: the crash cannot be placed inside or outside the section.
        # NIS and DEL can still be justified by the diagram alone (wrong road,
        # not a study crash), so they are left as proposals.
        if ctx.analysis_type == "section":
            rl = getattr(ctx, "resolved_location", None)
            have_mp = (getattr(rl, "milepost", None) is not None
                       or ctx.fiche_milepost is not None)
            base = (res.proposed_status or "").split("-")[0]
            if not have_mp and base in ("IS", "RE"):
                res.needs_manual = True
                res.flags.append(
                    f"{base} proposed for a milepost-dependent section study "
                    "with no resolved and no coded milepost; the crash cannot "
                    "be placed in the section at all.")
            elif base == "RE" and getattr(rl, "milepost", None) is None:
                # RE is a location call, and the report can support it on its
                # own: the diagram, the narrative, a named cross street. The
                # corrected milepost is a separate lookup against the features
                # report, and nothing on the DMV-349 is a milepost (docs/09).
                # So the status survives and the number does not. A New MP here
                # could only have come from a distance field, which is how
                # "04.20 Miles outside municipality" once became MP 4.20.
                if res.new_mp is not None:
                    res.flags.append(
                        f"dropped New MP {res.new_mp:.2f}: no resolved milepost "
                        "was supplied, so it was not read off the features "
                        "report, and nothing on the DMV-349 is a milepost.")
                    res.new_mp = None
                res.needs_manual = True
                res.flags.append(
                    "RE proposed without a corrected milepost. The location "
                    "call stands on the report; look the New MP up against the "
                    "features report for this route before the row is written.")
        # Validated last, so it judges the fields as they will actually be used:
        # the guards above can drop a fabricated New MP, and an RE that has lost
        # its milepost has to come back as "not deliverable yet" rather than as
        # a clean row (docs/03: every delivered RE row carries a New MP).
        det = res.as_determination()
        if det is not None:
            res.validation_problems = validate_determination(
                det, ctx.analysis_type,
                in_initial_study=ctx.in_initial_study)
            if res.validation_problems:
                res.needs_manual = True
        if res.confidence == "low":
            res.needs_manual = True
    else:
        res.diagram_summary = data.get("diagram_summary", "")
        res.narrative_summary = data.get("narrative_summary", "")
        res.report_location = data.get("report_location", "")
        res.distance_assessment = data.get("distance_assessment", "")
        res.applicable_rule = data.get("applicable_rule", "")
        res.comment = data.get("draft_comment", "")
        res.candidate_statuses = list(data.get("candidate_statuses", []))
        res.flags = list(data.get("flags", []))
    return res


def assist(row, ctx: StudyContext, pages, mode: str = "decide",
           client=None, redacted: bool = False,
           model: str = DEFAULT_MODEL) -> AssistResult:
    """Assist one crash's determination from its REDACTED report pages.

    ``pages`` are already-redacted PIL images (``render_crash_pages`` output);
    the caller must pass ``redacted=True`` to affirm it. Animal crashes and
    crashes with no report short-circuit without an API call.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if pages and not redacted:
        raise ValueError(
            "review_assist.assist refuses un-redacted pages: pass images from "
            "binder.render_crash_pages / redact (redacted=True). Raw DMV-349 "
            "imagery must never reach the model (docs/03, docs/07).")

    if getattr(row, "is_animal", False):
        return AssistResult(crash_id=row.crash_id, mode=mode, needs_manual=False,
                            applicable_rule="Animal crash: ignored in the IS "
                            "review (docs/03); no report review needed.",
                            note="animal crash", flags=["animal-skip"])
    if not pages:
        return AssistResult(crash_id=row.crash_id, mode=mode, needs_manual=True,
                            note="No DMV-349 page for this crash; a determination "
                            "that needs the report is unverifiable (docs/03).",
                            flags=["no-report"])

    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    params = build_request(row, ctx, pages, mode, model=model)
    response = client.messages.create(**params)
    if getattr(response, "stop_reason", None) == "refusal":
        return AssistResult(crash_id=row.crash_id, mode=mode, needs_manual=True,
                            note="model declined to assist", flags=["refusal"])
    text = next((b.text for b in response.content
                 if getattr(b, "type", None) == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return AssistResult(crash_id=row.crash_id, mode=mode, needs_manual=True,
                            note=f"unparseable model output: {exc}",
                            flags=["parse-error"])
    return _parse(data, row, ctx, mode)
