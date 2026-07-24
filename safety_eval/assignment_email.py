"""Parse assignment / assumptions emails (.msg / .eml) directly (docs/07).

The assignment email thread (VHB <-> NCDOT Traffic Safety) carries one block
per assignment with a fixed bullet vocabulary, verified on the real
SS-6002M/SS-6002AS thread:

    Assignment #22
    *   Order ID: 41000075552
    *   Project ID: 02-20-61721 (TIP #SS-6002M)
    *   Location: US 13 between ... (MP 0.00 to MP 7.38; 7.38 miles)
    *   GPS Coordinates: 35.441163, -77.824727 to ...
    *   County/Division: Greene County / Division 2
    *   Signal ID: 02-0240                       (intersections only)
    *   Countermeasure: ... (+ sub-bullets)
    *   Total Cost Estimate: $116,000
    *   Project Completion: 10/16/2021 (construction began 5/26/2021)
    *   Time Periods:  <Period/Start/End/Duration table>
    *   Target Crashes: ... (+ sub-bullets)
    *   Project Development Crash Summary: 155 total crashes (...)
    *   Additional Notes/Questions: (+ sub-bullets)

Outlook .msg files are read straight from the OLE property streams with
``olefile`` (no fragile converter dependency); .eml via the stdlib.  A thread
quotes earlier copies of the same blocks, so each assignment number keeps its
FIRST (newest, top-of-thread) occurrence - that is the copy carrying NCDOT's
inline answers.

The parsed result is the transcription the engineer used to type by hand: it
converts to the assumptions-email YAML (``safety-eval assumptions``) and to a
draft assignment YAML.  It is a draft to review, not a decision maker -
notes/questions come through verbatim so nothing silently drops.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
_GPS_RE = re.compile(r"(-?\d{1,3}\.\d{3,}),\s*(-?\d{1,3}\.\d{3,})")
_TIP_RE = re.compile(r"\(TIP\s*#?([^)]+)\)")
_HEADING_RE = re.compile(r"^\s*Assignment\s*#(\d+)\s*$", re.I)
# the pre-2026 template heads its single block "Evaluation Assumptions" and
# names the assignment number only in the surrounding prose or subject
_ALT_HEADING_RE = re.compile(r"^\s*Evaluation Assumptions\s*:?\s*$", re.I)
_NUM_NEARBY_RE = re.compile(r"Assignment\s*#(\d+)", re.I)
# top-level bullet labels, in the order they appear in the templates; longer
# variants must precede their prefixes (Countermeasures before Countermeasure)
_LABELS = (
    "Order ID", "Project ID", "Location", "GPS Coordinates",
    "County/Division", "County / Division", "Signal ID", "Study Type",
    "Countermeasures", "Countermeasure", "Statement of Problem",
    "Total Cost Estimate", "Project Cost", "Project Completion",
    "Time Periods", "Target Crashes",
    "Project Development Crash Summary", "Project Dev Crash Summary",
    "Additional Notes/Questions", "Additional Notes",
)
_LABEL_CANON = {
    "Countermeasures": "Countermeasure",
    "Project Cost": "Total Cost Estimate",
    "Project Dev Crash Summary": "Project Development Crash Summary",
    "County / Division": "County/Division",
}


# --------------------------------------------------------------------------- #
# reading the email container
# --------------------------------------------------------------------------- #
def read_email(path: str) -> tuple[str, str]:
    """Return (subject, plain-text body) from a .msg, .eml, or .txt file."""
    low = path.lower()
    if low.endswith(".msg"):
        return _read_msg(path)
    if low.endswith(".eml"):
        return _read_eml(path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        return "", fh.read()


def _read_msg(path: str) -> tuple[str, str]:
    """Subject and body from the MAPI property streams of an Outlook .msg.

    0037 = PR_SUBJECT, 1000 = PR_BODY; the 001F variants are UTF-16LE, the
    001E variants are the 8-bit codepage fallback.
    """
    import olefile

    ole = olefile.OleFileIO(path)
    try:
        def prop(tag: str) -> str:
            for suffix, enc in (("001F", "utf-16-le"), ("001E", "cp1252")):
                name = f"__substg1.0_{tag}{suffix}"
                if ole.exists(name):
                    return (ole.openstream(name).read()
                            .decode(enc, errors="replace"))
            return ""
        return prop("0037"), prop("1000")
    finally:
        ole.close()


def _read_eml(path: str) -> tuple[str, str]:
    import email
    import email.policy

    with open(path, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=email.policy.default)
    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content() if body is not None else ""
    return str(msg.get("Subject", "")), text


def clean_text(text: str) -> str:
    """Strip Outlook artifacts: <url> link wrappers (safelinks and mailto)
    and non-breaking spaces. The visible text (e.g. the printed coordinates)
    is kept; only the angle-bracketed wrapper goes."""
    text = text.replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"<(?:https?:[^>]*|mailto:[^>]*)>", "", text, flags=re.S)


# --------------------------------------------------------------------------- #
# the assignment blocks
# --------------------------------------------------------------------------- #
@dataclass
class ParsedAssignment:
    number: str = ""
    order_id: str = ""
    project_id: str = ""                  # "02-20-61721"
    tip: str = ""                         # "SS-6002M"
    study_type: str = ""                  # pre-2026 template bullet
    statement_of_problem: str = ""
    location: str = ""
    location_notes: list = field(default_factory=list)
    gps: list = field(default_factory=list)     # [(lat, lon), ...]
    county: str = ""
    division: str = ""
    signal_id: str | None = None
    countermeasure: str = ""
    countermeasure_notes: list = field(default_factory=list)
    cost: str = ""
    completion: str = ""                  # completion date text
    construction_began: str = ""
    completion_notes: list = field(default_factory=list)
    periods: dict = field(default_factory=dict)  # name -> (start, end) dates
    target_crashes: str = ""
    target_notes: list = field(default_factory=list)
    dev_summary: str = ""
    dev_summary_notes: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def countermeasure_text(self) -> str:
        """The countermeasure with 'the following' sub-bullets folded in."""
        base = self.countermeasure.strip()
        if not self.countermeasure_notes:
            return base
        low = base.lower().rstrip(",: ")
        if low.endswith("following") or base.endswith((",", ":")):
            items = [n.rstrip(". ") for n in self.countermeasure_notes]
            return (base.rstrip(",: ") + ": " + "; ".join(items) + ".")
        return base

    @property
    def intersection_study(self) -> bool:
        """Single GPS point and an 'at' location read as an intersection."""
        if self.signal_id:
            return True
        return len(self.gps) == 1 and " at " in f" {self.location} "


def split_assignments(body: str) -> dict[str, str]:
    """{assignment number: block text}, keeping the FIRST occurrence.

    Threads quote older copies of the same blocks below the newest reply, so
    the first hit from the top is the one with the latest inline answers.
    """
    lines = clean_text(body).split("\n")
    starts: list[tuple[int, str]] = []
    alt = 0
    for i, line in enumerate(lines):
        stripped = line.strip("* \t")
        m = _HEADING_RE.match(stripped)
        if m:
            starts.append((i, m.group(1)))
            continue
        if _ALT_HEADING_RE.match(stripped):
            # number lives in the prose just above, or nowhere
            num = None
            for back in range(max(0, i - 12), i):
                m2 = _NUM_NEARBY_RE.search(lines[back])
                if m2:
                    num = m2.group(1)
            alt += 1
            starts.append((i, num or f"EA{alt}"))
    boundary = re.compile(
        r"^\s*(?:(?:From|Sent|To|Cc|Subject):\s|--\s*$"
        r"|(?:best regards|thank you|thanks|regards|sincerely)[,.!]?\s*$)",
        re.I)
    blocks: dict[str, str] = {}
    for idx, (start, num) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        for j in range(start + 1, end):     # stop at the reply/signature
            if boundary.match(lines[j]):
                end = j
                break
        if num not in blocks:
            blocks[num] = "\n".join(lines[start + 1: end])
    return blocks


def _label_of(line: str) -> tuple[str | None, str]:
    """(label, remainder) when the line is a top-level '* Label: value'."""
    stripped = line.lstrip()
    if not stripped.startswith("*"):
        return None, line
    if line.startswith(("\t", " ")):
        return None, line                # indented = sub-bullet
    content = stripped.lstrip("*").strip()
    for label in _LABELS:
        if content.lower().startswith(label.lower()):
            rest = content[len(label):].lstrip(" :–-")
            return _LABEL_CANON.get(label, label), rest
    return "", content                   # top-level bullet, unknown label


def _sub_text(line: str) -> str:
    return line.strip().lstrip("*").strip()


def _parse_date(text: str) -> date | None:
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    mth, day, yr = (int(g) for g in m.groups())
    try:
        return date(yr, mth, day)
    except ValueError:
        return None


def _parse_periods(lines: list[str]) -> dict[str, tuple[date, date]]:
    """The Time Periods table flattens to one cell per line:
    Period/Start/End/Duration headers, then Before, 11/1/2016, 4/30/2021,
    '4 years 6 months', Construction, ... Scan for the period names followed
    by two parseable dates."""
    out: dict[str, tuple[date, date]] = {}
    texts = [ln.strip() for ln in lines if ln.strip()]
    for i, t in enumerate(texts):
        name = t.lower()
        if name in ("before", "construction", "after") and i + 2 < len(texts):
            start, end = _parse_date(texts[i + 1]), _parse_date(texts[i + 2])
            if start and end and name not in out:
                out[name] = (start, end)
    return out


def parse_block(number: str, block: str) -> ParsedAssignment:
    pa = ParsedAssignment(number=number)
    lines = block.split("\n")
    current: str | None = None
    section_lines: dict[str, list[str]] = {}
    for line in lines:
        label, rest = _label_of(line)
        if label is None:
            if current:
                section_lines.setdefault(current, []).append(line)
            continue
        if label == "":
            # unknown top-level bullet: treat as a note so nothing drops
            if current not in ("Additional Notes/Questions",
                               "Additional Notes", "Time Periods"):
                current = "Additional Notes/Questions"
            section_lines.setdefault(current, []).append("* " + rest)
            continue
        current = label
        section_lines.setdefault(current, []).append(rest)

    def sect(*names) -> list[str]:
        for n in names:
            if n in section_lines:
                return section_lines[n]
        return []

    def first(*names) -> str:
        vals = sect(*names)
        return vals[0].strip() if vals else ""

    def subs(*names) -> list[str]:
        vals = sect(*names)
        return [_sub_text(v) for v in vals[1:] if v.strip()]

    pa.order_id = first("Order ID")
    proj = first("Project ID")
    m = _TIP_RE.search(proj)
    if m:
        pa.tip = m.group(1).strip()
        proj = _TIP_RE.sub("", proj).strip()
    pa.project_id = proj
    pa.location = first("Location")
    pa.location_notes = subs("Location")
    gps_text = " ".join(sect("GPS Coordinates"))
    pa.gps = [(float(a), float(b)) for a, b in _GPS_RE.findall(gps_text)]
    cd = first("County/Division", "County / Division")
    if "/" in cd:
        county, division = cd.split("/", 1)
        pa.county = county.replace("County", "").strip()
        pa.division = division.replace("Division", "").strip()
    else:
        pa.county = cd.replace("County", "").strip()
    signal = first("Signal ID")
    pa.signal_id = signal if signal and signal.upper() not in ("N/A", "NA") \
        else None
    pa.study_type = first("Study Type")
    pa.statement_of_problem = first("Statement of Problem")
    pa.countermeasure = first("Countermeasure")
    pa.countermeasure_notes = subs("Countermeasure")
    pa.cost = first("Total Cost Estimate")
    completion = first("Project Completion")
    m = re.search(r"\(construction began\s+([^)]+)\)", completion, re.I)
    if m:
        pa.construction_began = m.group(1).strip()
        completion = completion[: m.start()].strip()
    pa.completion = completion
    pa.completion_notes = subs("Project Completion")
    pa.periods = _parse_periods(sect("Time Periods"))
    pa.target_crashes = first("Target Crashes")
    pa.target_notes = subs("Target Crashes")
    if not pa.target_crashes and pa.target_notes:
        # caption-only label with the definition on the first sub-bullet
        pa.target_crashes = pa.target_notes.pop(0)
    pa.dev_summary = first("Project Development Crash Summary")
    pa.dev_summary_notes = subs("Project Development Crash Summary")
    pa.notes = subs("Additional Notes/Questions", "Additional Notes")
    return pa


def parse_assignment_email(path: str) -> dict[str, ParsedAssignment]:
    """Parse every assignment block of an email file, newest copy of each."""
    _subject, body = read_email(path)
    return {num: parse_block(num, block)
            for num, block in split_assignments(body).items()}


def parse_assumptions_docx(path: str) -> ParsedAssignment:
    """Parse a generated 'Assumptions Email - ....docx' into one block.

    The archive keeps the drafted assumptions document beside older
    evaluations whose .msg thread is missing; its bullet paragraphs use the
    same label vocabulary, so they are rebuilt into pseudo-email lines
    (list-styled paragraphs indent as sub-bullets) and fed through the same
    block parser.
    """
    import docx

    doc = docx.Document(path)
    lines = ["Evaluation Assumptions"]
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text or _ALT_HEADING_RE.match(text):
            continue
        style = (para.style.name or "") if para.style is not None else ""
        level = 0
        if any(ch in style for ch in ("2", "3", "4")):   # List Bullet 2/3...
            level = 1
        else:
            ilvl = para._p.xpath(".//w:numPr/w:ilvl/@w:val")
            if ilvl and str(ilvl[0]).isdigit() and int(ilvl[0]) > 0:
                level = 1
        lines.append(("\t*\t" if level else "*\t") + text)
    blocks = split_assignments("\n".join(lines))
    for num, block in blocks.items():
        return parse_block(num, block)
    return parse_block("", "\n".join(lines))


# --------------------------------------------------------------------------- #
# conversions (drafts for the engineer to review, docs/07)
# --------------------------------------------------------------------------- #
def _gps_text(pa: ParsedAssignment) -> str:
    if not pa.gps:
        return ""
    pts = [f"{lat}, {lon}" for lat, lon in pa.gps]
    return pts[0] if len(pts) == 1 else " to ".join(pts[:2])


def to_assumptions_dict(pa: ParsedAssignment) -> dict:
    """Keys accepted by ``load_assumptions_yaml`` (safety-eval assumptions)."""
    out = {
        "order_id": pa.order_id,
        "project_id": (f"{pa.project_id} (TIP #{pa.tip})" if pa.tip
                       else pa.project_id),
        "gps": _gps_text(pa),
        "county": pa.county,
        "division": pa.division,
        "study_type": pa.study_type or ("Intersection Analysis"
                                        if pa.intersection_study
                                        else "Strip Analysis"),
        "statement_of_problem": pa.statement_of_problem,
        "location": pa.location,
        "countermeasure": pa.countermeasure_text(),
        "project_cost": pa.cost,
        "project_completion": (pa.completion
                               + (f" (construction began "
                                  f"{pa.construction_began})"
                                  if pa.construction_began else "")),
        "completion_notes": list(pa.completion_notes),
        "target_crashes": pa.target_crashes,
        "project_dev_summary": pa.dev_summary,
        "additional_notes": (list(pa.location_notes)
                             + list(pa.target_notes)
                             + list(pa.dev_summary_notes)
                             + list(pa.notes)),
    }
    if pa.signal_id:
        out["signal_id"] = pa.signal_id
    if "construction" in pa.periods:
        start, end = pa.periods["construction"]
        out["construction_end"] = end.isoformat()
        out["construction_months"] = ((end.year - start.year) * 12
                                      + end.month - start.month + 1)
    return out


def to_assignment_dict(pa: ParsedAssignment) -> dict:
    """A draft of the assignment YAML (the auditable study-scope record)."""
    cm = pa.countermeasure_text()
    out: dict = {
        "project_id": pa.project_id or pa.order_id,
        "description": f"{cm} (TIP #{pa.tip})" if pa.tip else cm,
        "county": pa.county,
        "intersection_study": pa.intersection_study,
        "countermeasure": cm,
        "target_crash_types": [pa.target_crashes] if pa.target_crashes else [],
        "assumptions": list(pa.notes),
        "notes": f"Parsed from assignment email (Assignment #{pa.number}); "
                 "review before use.",
    }
    mp = re.search(r"MP\s*([\d.]+)\s*to\s*MP\s*([\d.]+)", pa.location, re.I)
    if mp:
        out["section_begin_mp"] = float(mp.group(1))
        out["section_end_mp"] = float(mp.group(2))
    if "before" in pa.periods:
        out["study_start"] = pa.periods["before"][0].isoformat()
    if "after" in pa.periods:
        out["study_end"] = pa.periods["after"][1].isoformat()
    if "construction" in pa.periods:
        out["construction_start"] = pa.periods["construction"][0].isoformat()
        out["construction_end"] = pa.periods["construction"][1].isoformat()
    return out
