"""Multi-agent QA sweep for a finished package (reviewers + refuters).

The process that caught the real defects on live packages: six independent
reviewers, one per dimension, each reading the package and reporting
findings with evidence; then three independent refuters that try to
disprove every finding against the files. A finding is CONFIRMED when at
least two refuters confirm it, REFUTED when at least two refute it, and
PARTIAL otherwise. The engineer applies confirmed findings; nothing here
edits a file.

Runs through the official Anthropic SDK (Claude Opus 5, adaptive thinking,
structured JSON output), reviewers and refuters in parallel threads. The
package is turned into text once (workbook cells, notes, PDF page texts)
and shared by every call, so prompt caching pays for the fan-out.

What the 08-18-51363 (W-5708K) resubmittal added (October 2026):

* the package text covers what an accessible-workbook package is made of:
  .xlsm workbooks (One Pager, Assumptions, Before and After), the Word one
  pager (paragraphs, tables, image alt text) and the correspondence in
  Notes (.msg/.eml). PDF pages already given in another file (a Complete
  Evaluation repeats its one pager and TEAAS reports) are given once;
* the deterministic package checks (qa_package) run first and their results
  go into the context as established facts, so the reviewers spend their
  effort on what code cannot judge;
* a seventh reviewer, REVIEWER COMMENTS, goes through the reviewer's
  comments one by one when there are any (pass them in, or keep the email
  in Notes);
* a list of items the engineer already knows about and accepted goes to
  every reviewer and refuter, so a resubmittal is not re-litigated; a
  refuter rejects a finding that only restates one;
* the PDF ASSEMBLY and REPORT TEXT reviewers also see the one pager pages
  as images, the check a text dump cannot make (layout, a broken two-column
  section, the map);
* crash report folders are never read (docs/11: raw DMV-349 pages do not
  reach a model), nor are hidden Office owner files (~$).
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-5"
MAX_CHARS_PER_PART = 60_000

DIMENSIONS = {
    "workbook": ("WORKBOOK INTEGRITY",
                 "Sheet structure, style and shared string consistency, drawings and media versus the template, "
                 "cached values that changed for no documented reason, formulas replaced by hardcoded numbers, "
                 "anything that could make Excel repair the file."),
    "fiche": ("FICHE REVIEW CHAIN",
              "Every crash in the TEAAS lists appears in the Filtered Fiche and Binned Crashes with the same period; "
              "no crash in both periods or in the construction period; target flags agree with the T code table and the "
              "target definition; road combination and Y-line logic; statuses IS/ADD/DEL/NIS only (never RE for an "
              "intersection); determinations record and notes agree with the workbook; unreviewed rows inside the Y-line."),
    "calculations": ("CALCULATIONS",
                     "Recompute severity indices with EPDO 76.8/8.4/1.0, counts by severity, percent changes, crashes per "
                     "year, period lengths, AADT interpolation and rounding (minor roads nearest hundred), representative "
                     "years (last published year in the period, never 2020), Volume row equals ROUND(intersection AADT, -2), "
                     "tracking sheet AADT columns."),
    "text": ("REPORT TEXT",
             "Every sentence in Items for Discussion (the results sheet, or the Word one pager of an accessible "
             "workbook) supported by the crash rows: counts, crash types, directions, fault, severities, periods; counts "
             "in the at-fault breakdown match the Additional Information rows; no em or en dashes; consistent route "
             "naming, county, division, dates, PE and firm; countermeasure and target text match the Assumptions sheet "
             "(D14 countermeasure, D20 target crashes, D24 notes; the assumptions email for an older package), and "
             "anything the assumptions promised to note in Items for Discussion is there; placeholders; "
             "unexplained route numbers; text that relied on a volume trend that no longer holds; the public-document "
             "rule (no TEAAS, workbook or fiche, no exact crash times unless a time-of-day pattern); image alt text."),
    "teaas": ("TEAAS CROSS-CHECK",
              "TEAAS report totals, severity breakdowns and indices versus the workbook and results page; Study Criteria "
              "dates, Y-line, road combinations, Included and Excluded Accidents versus ADD/DEL; ADT used by TEAAS versus "
              "the workbook representative volumes; run date versus the results page date; crash ID lists versus import files."),
    "pdf": ("PDF ASSEMBLY",
            "Page counts and order; results page or one pager text versus the workbook cells including the Volume "
            "row; one pager PDF versus its Word docx; disclaimer present; TEAAS pages identical to the standalone "
            "reports; the one pager page images: layout intact, nothing overlapping or cut off, map legible; embedded "
            "aerial not downsampled; margins match the Excel print; PDF metadata; zip contents versus the folder."),
    "comments": ("REVIEWER COMMENTS",
                 "Go through the reviewer's comments one at a time, for each location. For each comment decide from "
                 "the package whether it is fully addressed, partly addressed or not addressed, citing the cell, crash "
                 "id, page or sentence that shows it. Report every comment that is not fully addressed as a finding "
                 "(High when the deliverable is wrong without it). List each addressed comment in verified with its "
                 "evidence. Crashes the reviewer asked to delete must be gone from the period sheets and every TEAAS "
                 "export; a crash that is not a target must not be flagged as one, and the tables that count it "
                 "must agree."),
}

#: Dimensions that only make sense with something to read.
NEEDS_COMMENTS = ("comments",)
CORRESPONDENCE_HEADER = "# Correspondence"
REVIEW_TAG = " (review comments)"
COMMENTS_KEY = "_reviewer_comments"
DETERMINISTIC_KEY = "_deterministic"

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["High", "Medium", "Low"]},
                "where": {"type": "string"}, "claim": {"type": "string"},
                "evidence": {"type": "string"}, "fix": {"type": "string"}},
            "required": ["severity", "where", "claim", "evidence", "fix"], "additionalProperties": False}},
        "verified": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["findings", "verified"], "additionalProperties": False,
}

VERDICTS_SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "verdict": {"type": "string", "enum": ["CONFIRMED", "REFUTED", "PARTIAL"]},
                       "evidence": {"type": "string"}, "fix_ok": {"type": "boolean"},
                       "better_fix": {"type": "string"}},
        "required": ["id", "verdict", "evidence", "fix_ok", "better_fix"], "additionalProperties": False}}},
    "required": ["verdicts"], "additionalProperties": False,
}

RULES = """Hard rules of the methodology (NCDOT HSIP, docs in the repo):
- EPDO K/A 76.8, B/C 8.4, PDO 1.0. Intersection Y-line 150 ft. Intersection studies are road-combination dependent, strip studies milepost dependent. RE status never used in intersection analyses. Animal crashes need no report review.
- AADT: black font = NCDOT published value, red = interpolated, carried forward or assumed; minor road estimates round to the nearest hundred; 2020 never a representative year; representative year = last year in the period with a published value on any leg; the printed volume is ROUND(major average + minor average, -2).
- Report text: plain, understated, no em or en dashes anywhere, no flourishes.
- Templated workbooks are edited by XML patching only; drawings and media must stay byte identical apart from the Map/Satellite Views picture.
- One pagers are public documents: never TEAAS, the workbook, the fiche or severity codes; no exact crash times or dates unless they matter (a time-of-day pattern); every crash-type acronym in the target crash text spelled out; the countermeasure names its specific components; every image has alt text, the map's being the Assumptions alt text rows verbatim, one per line; the PDF is Saved As PDF (tagged) with that alt text on the map, never printed to PDF.
- A roundabout or mini-roundabout is never called a circle or a traffic circle.
- Hidden Office owner files (names starting ~$) are never findings.
- Facts under "Deterministic checks" were established by code over the actual files. Build on them; do not report them again as new findings, and do not contradict them without quoting the material that shows they are wrong.
Report only what you verify in the material provided. Quote cell addresses, crash ids, page numbers and exact values as evidence. Never invent a check you did not perform."""


@dataclass
class SweepFinding:
    id: str
    dimension: str
    severity: str
    where: str
    claim: str
    evidence: str = ""
    fix: str = ""
    verdicts: list = field(default_factory=list)     # (refuter index, verdict, evidence, fix_ok, better_fix)

    @property
    def status(self) -> str:
        if not self.verdicts:
            return "UNVERIFIED"
        c = sum(1 for v in self.verdicts if v[1] == "CONFIRMED")
        r = sum(1 for v in self.verdicts if v[1] == "REFUTED")
        if c >= 2 or (c == 1 and r == 0 and len(self.verdicts) == 1):
            return "CONFIRMED"
        if r >= 2 or (r == 1 and c == 0 and len(self.verdicts) == 1):
            return "REFUTED"
        return "PARTIAL"


@dataclass
class SweepReport:
    findings: list = field(default_factory=list)
    verified: dict = field(default_factory=dict)      # dimension -> [str]
    errors: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)
    deterministic: str = ""

    def by_status(self, status: str) -> list:
        return [f for f in self.findings if f.status == status]


# --------------------------------------------------------------------------- #
# package to text
# --------------------------------------------------------------------------- #
def _clip(text: str, limit: int = MAX_CHARS_PER_PART) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


FULL_SHEETS = {"Evaluation Set-up": "A1:R40", "1 page results - 1 Target": "B2:L75",
               "Before": "A1:M120", "After": "A1:M120", "Binned Crashes": "A1:U200",
               "For NCDOT staff - for Tracking": "A1:BE8"}
#: The accessible (macro) workbook: inputs on Assumptions and Evaluation
#: Set-up, the One Pager's input column, Additional Information, periods and
#: the 1 Target / All Crashes block the macro writes into the Word one pager.
ACCESSIBLE_SHEETS = {"Assumptions": "A1:R40", "Evaluation Set-up": "A1:R40", "One Pager": "H3:N38",
                     "One Pager ": "AF3:AI30", "Before": "A1:N160", "After": "A1:N160",
                     "For NCDOT staff - for Tracking": "A1:BE8"}


def workbook_text(path: str, sheets: dict | None = None) -> str:
    """Key sheets as compact 'cell=value' text."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if sheets is None:
        sheets = ACCESSIBLE_SHEETS if "One Pager" in wb.sheetnames else FULL_SHEETS
    out = [f"# Workbook {os.path.basename(path)}; sheets: {', '.join(wb.sheetnames)}"]
    for key, rng in sheets.items():
        name = key.strip()              # "One Pager " is a second range on One Pager
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        cells = []
        for row in ws[rng]:
            for c in row:
                if c.value is not None and str(c.value).strip() != "":
                    v = c.value
                    if isinstance(v, float):
                        v = round(v, 6)
                    cells.append(f"{c.coordinate}={v!r}")
        out.append(f"## Sheet '{name}' ({rng})\n" + "\n".join(cells))
    # Filtered Fiche: only determined rows and headers
    if "Filtered Fiche" in wb.sheetnames:
        ws = wb["Filtered Fiche"]
        rows = []
        for r in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 800), values_only=True):
            vals = [v for v in r if v is not None]
            if not vals:
                continue
            txt = " | ".join(str(v) for v in r[:21])
            if re.search(r"\b(IS|ADD|DEL|NIS|RE|REV)\b", txt) or len(rows) < 3:
                rows.append(txt)
            if len(rows) > 120:
                break
        out.append("## Sheet 'Filtered Fiche' (determined rows)\n" + "\n".join(rows))
    return _clip("\n\n".join(out), MAX_CHARS_PER_PART * 2)


def pdf_text(path: str, max_pages: int = 80, seen: dict | None = None, budget: int = MAX_CHARS_PER_PART) -> str:
    """Page texts, whole pages only, within ``budget`` characters.

    Runs of spaces from the layout are collapsed (columns stay apart). A page
    already given in another file (``seen``: text hash -> "file page n") is a
    pointer to it; only pages actually shown are recorded there. When the
    budget runs out, interior pages go first and a TEAAS report's Study
    Criteria pages at the end are kept, since the TEAAS reviewer needs them.
    """
    import hashlib

    from .print_results import pdf_page_texts
    from .qa_package import _appendix_start

    every = pdf_page_texts(path)
    pages, total = every[:max_pages], len(every)
    keep_tail = set(range(_appendix_start(pages), len(pages)))
    texts = [re.sub(r"[ \t]{3,}", "  ", p.strip()) for p in pages]
    tail_cost = sum(len(texts[i]) + 20 for i in keep_tail)
    used, parts, dropped = 0, [], []
    for i, t in enumerate(texts):
        body = re.sub(r"\s+", " ", t).strip()
        key = hashlib.sha1(body.encode("utf-8")).hexdigest()
        if seen is not None and body and key in seen:
            parts.append(f"--- page {i + 1} --- [same text as {seen[key]}]")
            continue
        room = budget - used - (0 if i in keep_tail else tail_cost)
        if len(t) + 20 > room:
            dropped.append(i + 1)
            continue
        used += len(t) + 20
        if seen is not None and body:
            seen[key] = f"{os.path.basename(path)} page {i + 1}"
        parts.append(f"--- page {i + 1} ---\n{t}")
    if dropped:
        parts.append(f"... [pages {dropped[0]}-{dropped[-1]} not shown: over the size budget]"
                     if len(dropped) > 1 else f"... [page {dropped[0]} not shown: over the size budget]")
    if total > len(pages):
        parts.append(f"... [{total - len(pages)} more pages not shown]")
    return f"# PDF {os.path.basename(path)} ({total} pages)\n" + "\n".join(parts)


def docx_text(path: str) -> str:
    """A Word one pager: paragraphs, tables row by row, image alt text."""
    from .qa_package import read_docx_facts

    d = read_docx_facts(path)
    out = [f"# Word document {os.path.basename(path)}", "## Paragraphs"]
    out += [p for p in d.paragraphs if p.strip()]
    for i, t in enumerate(d.tables, 1):
        out.append(f"## Table {i}")
        out += [" | ".join(r) for r in t]
    out.append("## Images (name: alt text)")
    out += [f"{n}: {a!r}" for n, a, _ in d.images] or ["(none)"]
    return _clip("\n".join(out))


#: A line that reads as a review request ("* Remove comma ...", "- Add a comment ...").
_REQUEST_RE = re.compile(r"^[ \t]*[*\u2022\-][ \t]*(remove|add|include|delete|update|change|revise|correct|fill|"
                         r"move|replace|check|make sure|please)\b", re.I | re.M)


def looks_like_review(text: str) -> bool:
    """Review comments, as opposed to an assignment or assumptions thread:
    crashes named for deletion or as not targets, or at least two bulleted
    requests."""
    from .qa_package import reviewer_crash_requests

    if any(r["action"] != "mention" for r in reviewer_crash_requests(text)):
        return True
    return len(_REQUEST_RE.findall(text)) >= 2


def email_text(path: str) -> str:
    from .assignment_email import read_email

    subject, body = read_email(path)
    body = re.sub(r"\n[ \t]*\n+", "\n", body)
    kind = REVIEW_TAG if looks_like_review(body) else ""
    return _clip(f"{CORRESPONDENCE_HEADER}{kind} {os.path.basename(path)}\nSubject: {subject}\n{body}")


#: Folders of DMV-349 crash reports (package.discover); never sent to a model.
CRASH_REPORT_DIRS = ("crash reports", "dmv-349", "reports")


def gather_context(package_dir: str, workbook: str | None = None, comments: str | None = None,
                   deterministic: bool = True, progress=None) -> dict[str, str]:
    """{part name: text} for everything a reviewer can read.

    ``comments`` is the reviewer's comment text when it is not (or not only)
    in the package's Notes. ``deterministic`` runs qa_package first and puts
    its findings and facts in the context.
    """
    from .qa_package import discover_package, is_hidden

    wanted = None
    if workbook:
        wanted = [workbook] if isinstance(workbook, str) else list(workbook)
        for w in wanted:
            if not os.path.exists(w):
                raise FileNotFoundError(f"workbook not found: {w}")
    else:
        # the deliverable workbook of each location, as the package checks see it
        wanted = [l.workbook for l in discover_package(package_dir).locations if l.workbook] or None
    ctx: dict[str, str] = {}
    inventory = []
    seen: dict = {}
    pdfs = []
    for dp, dn, fn in os.walk(package_dir):
        # crash report folders (and everything under them) are never read or listed (docs/11)
        dn[:] = sorted(d for d in dn if not is_hidden(d) and d.lower() not in CRASH_REPORT_DIRS)
        for f in sorted(fn):
            if is_hidden(f):
                continue
            p = os.path.join(dp, f)
            inventory.append(f"{os.path.relpath(p, package_dir)} ({os.path.getsize(p)} bytes)")
            low = f.lower()
            rel = os.path.relpath(p, package_dir)
            try:
                if low.endswith((".xlsx", ".xlsm")):
                    if wanted is None or any(os.path.samefile(p, w) for w in wanted):
                        ctx[rel] = workbook_text(p)
                    else:
                        inventory[-1] += " [not read: not the deliverable workbook]"
                elif low.endswith(".pdf") and "redact" not in low:
                    pdfs.append((p, rel))
                elif low.endswith(".docx"):
                    ctx[rel] = docx_text(p)
                elif low.endswith((".msg", ".eml")):
                    ctx[rel] = email_text(p)
                elif low.endswith((".md", ".txt", ".jsonl", ".csv")) and os.path.getsize(p) < 400_000:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        ctx[rel] = _clip(f"# {rel}\n" + fh.read())
            except Exception as exc:  # noqa: BLE001 - a bad part is reported, not fatal
                ctx[rel] = f"# {rel}\n[could not read: {exc}]"
    # standalone reports first, so a compilation points back at them
    for p, rel in sorted(pdfs, key=lambda x: ("complete evaluation" in x[1].lower(), x[1])):
        try:
            background = rel.lower().startswith("background info")
            ctx[rel] = pdf_text(p, seen=seen, max_pages=2 if background else 80,
                                budget=MAX_CHARS_PER_PART // 6 if background else 2 * MAX_CHARS_PER_PART)
        except Exception as exc:  # noqa: BLE001
            ctx[rel] = f"# {rel}\n[could not read: {exc}]"
    ctx["_inventory"] = "# Package inventory (hidden Office owner files left out)\n" + "\n".join(inventory)
    if comments:
        ctx[COMMENTS_KEY] = f"{CORRESPONDENCE_HEADER}{REVIEW_TAG}: supplied by the engineer\n{comments}"
    if deterministic:
        try:
            from .qa_package import format_package_report, run_package_qa
            pq = run_package_qa(package_dir, comments=comments, progress=progress)
            det = format_package_report(pq) + "\n\n" + pq.facts_text()
            det = det.replace(os.path.normpath(package_dir) + os.sep, "")
            ctx[DETERMINISTIC_KEY] = "# Deterministic checks (run by code over the files; established facts)\n" + det
        except Exception as exc:  # noqa: BLE001
            ctx[DETERMINISTIC_KEY] = f"# Deterministic checks\n[could not run: {exc}]"
    return ctx


def has_correspondence(ctx: dict[str, str]) -> bool:
    """Is there anything for the REVIEWER COMMENTS reviewer? Comments the
    engineer supplied, or an email that reads as review comments; an
    assignment or assumptions thread in Notes is not enough."""
    return any(v.startswith(CORRESPONDENCE_HEADER + REVIEW_TAG) for v in ctx.values())


def page_images(package_dir: str, dpi: int = 150, max_images: int = 8) -> list[dict]:
    """The one pager (or Web) PDF pages as image blocks for the PDF and text
    reviewers and their refuters. Public documents only; never crash
    reports. 150 dpi keeps the map legend and body text legible (a legal page
    is 1275 x 2100 px, under the 2576 px limit)."""
    import base64
    import shutil
    import subprocess
    import tempfile

    from .qa_package import is_hidden

    exe = shutil.which("pdftoppm")
    if not exe:
        return []
    out: list[dict] = []
    left_out: list[str] = []
    for dp, dn, fn in os.walk(package_dir):
        dn[:] = sorted(d for d in dn if not is_hidden(d) and d.lower() not in CRASH_REPORT_DIRS)
        for f in sorted(fn):
            if is_hidden(f) or not re.search(r"(one\s*pager|\bweb)\.pdf$", f.lower()):
                continue
            with tempfile.TemporaryDirectory() as td:
                try:
                    subprocess.run([exe, "-r", str(dpi), "-png", os.path.join(dp, f), os.path.join(td, "p")],
                                   check=True, capture_output=True, timeout=180)
                except (subprocess.SubprocessError, OSError):
                    continue
                for png in sorted(os.listdir(td)):
                    page = png.rsplit("-", 1)[-1].split(".")[0].lstrip("0") or "1"
                    if sum(1 for b in out if b["type"] == "image") >= max_images:
                        left_out.append(f"{f} page {page}")
                        continue
                    with open(os.path.join(td, png), "rb") as fh:
                        data = base64.standard_b64encode(fh.read()).decode("ascii")
                    out.append({"type": "text", "text": f"Image: {f}, page {page}"})
                    out.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
    if left_out:
        out.append({"type": "text", "text": "Not shown as images (cap reached): " + ", ".join(left_out)})
    return out


def context_blocks(ctx: dict[str, str], accepted: list[str] | None = None) -> list[dict]:
    """Cacheable system blocks: rules (and the accepted items), then the package text."""
    rules = RULES
    if accepted:
        rules += ("\n\nKNOWN AND ACCEPTED by the engineer (already decided; not findings unless the material "
                  "shows the item itself is wrong in a way this list does not describe):\n"
                  + "\n".join(f"- {a.strip().lstrip('-*').strip()}" for a in accepted if a.strip()))
    blocks = [{"type": "text", "text": rules}]
    body = "\n\n".join(ctx[k] for k in sorted(ctx))
    blocks.append({"type": "text", "text": "PACKAGE MATERIAL\n\n" + body,
                   "cache_control": {"type": "ephemeral"}})
    return blocks


def read_accepted(text: str | None) -> list[str]:
    """Accepted items, one per line. Only a real list marker is stripped
    ("- ", "* ", "2. ", "3) "), so an item that starts with a crash ID or a
    year keeps it."""
    if not text:
        return []
    out = []
    for ln in text.splitlines():
        if not ln.strip() or ln.strip().startswith("#"):
            continue
        out.append(re.sub(r"^\s*(?:[-*\u2022]|\d{1,3}[.)])\s+", "", ln).strip())
    return [x for x in out if x]


def read_accepted_file(path: str | None) -> list[str]:
    if not path:
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        return read_accepted(fh.read())


# --------------------------------------------------------------------------- #
# model calls
# --------------------------------------------------------------------------- #
def _json_call(client, model: str, system: list, user: str, schema: dict, effort: str, usage: dict) -> dict:
    resp = client.messages.create(
        model=model, max_tokens=16000, system=system, thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user}])
    u = getattr(resp, "usage", None)
    if u is not None:
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            usage[k] = usage.get(k, 0) + (getattr(u, k, 0) or 0)
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("model declined the request")
    if getattr(resp, "stop_reason", None) == "max_tokens":
        raise RuntimeError("the answer ran out of output tokens before the JSON was complete; "
                           "run this dimension alone or at a lower effort")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(text)


#: Reviewers that also get the one pager page images.
SEES_PAGES = ("pdf", "text")


def review_dimension(client, key: str, system: list, model: str, effort: str, usage: dict,
                     images: list | None = None) -> tuple[list, list]:
    title, brief = DIMENSIONS[key]
    user = (f"You are the {title} reviewer for this safety evaluation package. Scope: {brief}\n"
            "Read the package material in the system context and report findings with exact evidence "
            "(cell addresses, crash ids, page numbers, values). Also list what you verified with no discrepancy. "
            "Severity: High = wrong number or membership on the deliverable; Medium = inconsistency a reviewer "
            "would question; Low = hygiene. Items the engineer listed as known and accepted are not findings.")
    if images and key in SEES_PAGES:
        user = [{"type": "text", "text": user + "\nThe one pager pages follow as images."}] + images
    data = _json_call(client, model, system, user, FINDINGS_SCHEMA, effort, usage)
    findings = [SweepFinding(id=f"{key}-{i + 1}", dimension=key, **f) for i, f in enumerate(data["findings"])]
    return findings, data.get("verified", [])


def refute(client, index: int, findings: list, system: list, model: str, effort: str, usage: dict,
           images: list | None = None) -> list[dict]:
    listing = "\n".join(f"[{f.id}] ({f.severity}) {f.where}: {f.claim}\n   evidence: {f.evidence}\n   proposed fix: {f.fix}"
                        for f in findings)
    user = (f"You are independent verifier {index + 1} of 3. For EACH finding below, try to disprove it against the "
            "package material. Return CONFIRMED only when you personally located the evidence in the material, "
            "REFUTED when the material contradicts it, the rule cited does not apply, or it only restates an item the "
            "engineer listed as known and accepted, PARTIAL when the facts hold but the severity or fix is wrong. "
            "Say whether the proposed fix is safe and give a better one if not.\n\n"
            + listing)
    if images and any(f.dimension in SEES_PAGES for f in findings):
        user = [{"type": "text", "text": user + "\nThe one pager pages follow as images."}] + images
    data = _json_call(client, model, system, user, VERDICTS_SCHEMA, effort, usage)
    return data["verdicts"]


def run_sweep(ctx: dict[str, str], client=None, model: str = DEFAULT_MODEL, dimensions: list | None = None,
              n_refuters: int = 3, effort: str = "high", progress=None, max_workers: int = 7,
              accepted: list[str] | None = None, images: list | None = None,
              warm_first: bool = True) -> SweepReport:
    """Reviewers in parallel, then refuters in parallel over the merged findings."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    dims = list(dimensions or DIMENSIONS)
    system = context_blocks(ctx, accepted)
    report = SweepReport()
    report.deterministic = ctx.get(DETERMINISTIC_KEY, "")
    usage: dict = {}

    def _p(msg: str):
        if progress:
            progress(msg)

    if not has_correspondence(ctx):
        for d in [d for d in dims if d in NEEDS_COMMENTS]:
            dims.remove(d)
            report.skipped.append(f"{DIMENSIONS[d][0]}: no review comments supplied or found in the package's emails")
            _p(f"{d} skipped: no reviewer comments")

    _p(f"reviewing {len(dims)} dimensions")

    def _review(d):
        try:
            findings, verified = review_dimension(client, d, system, model, effort, usage, images)
            report.findings.extend(findings)
            report.verified[d] = verified
            _p(f"{DIMENSIONS[d][0]}: {len(findings)} finding(s)")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{d}: {exc}")
            _p(f"{d} failed: {exc}")

    # The first reviewer runs alone: a cache entry is readable only once a
    # response has started, so parallel requests would each pay the full
    # cache write on the package text. The rest then read it from the cache.
    if dims and warm_first:
        _review(dims[0])
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_review, dims[1:] if warm_first else dims))
    order = {d: i for i, d in enumerate(dims)}
    report.findings.sort(key=lambda f: (order.get(f.dimension, 99), f.id))
    if report.findings and n_refuters > 0:
        _p(f"refuting {len(report.findings)} finding(s) with {n_refuters} verifiers")
        by_id = {f.id: f for f in report.findings}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(refute, client, i, report.findings, system, model, effort, usage, images)
                    for i in range(n_refuters)]
            for i, fut in enumerate(futs):
                try:
                    for v in fut.result():
                        f = by_id.get(v["id"])
                        if f:
                            f.verdicts.append((i, v["verdict"], v.get("evidence", ""), v.get("fix_ok", True), v.get("better_fix", "")))
                    _p(f"verifier {i + 1} done")
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"refuter {i + 1}: {exc}")
    report.usage = usage
    return report


def sweep_to_markdown(report: SweepReport, title: str = "QA sweep") -> str:
    order = {"High": 0, "Medium": 1, "Low": 2}
    lines = [f"# {title}", ""]
    for status in ("CONFIRMED", "PARTIAL", "REFUTED", "UNVERIFIED"):
        items = sorted(report.by_status(status), key=lambda f: (order.get(f.severity, 3), f.id))
        if not items:
            continue
        lines.append(f"## {status} ({len(items)})")
        for f in items:
            lines.append(f"- **{f.id}** [{f.severity}] {f.where}: {f.claim}")
            if f.evidence:
                lines.append(f"  - evidence: {f.evidence}")
            if f.fix:
                lines.append(f"  - fix: {f.fix}")
            for i, verdict, ev, fix_ok, better in f.verdicts:
                extra = "" if fix_ok else f"; better fix: {better}"
                lines.append(f"  - verifier {i + 1}: {verdict}. {ev}{extra}")
        lines.append("")
    if report.verified:
        lines.append("## Verified with no discrepancy")
        for d, items in report.verified.items():
            for v in items:
                lines.append(f"- {DIMENSIONS.get(d, (d,))[0]}: {v}")
        lines.append("")
    if report.skipped:
        lines.append("## Skipped")
        lines += [f"- {e}" for e in report.skipped]
        lines.append("")
    if report.deterministic:
        lines.append("## Deterministic checks (given to every reviewer)")
        lines.append("```")
        lines.append(report.deterministic.split("\n", 1)[-1])
        lines.append("```")
        lines.append("")
    if report.errors:
        lines.append("## Errors")
        lines += [f"- {e}" for e in report.errors]
    if report.usage:
        lines.append(f"\nTokens: {report.usage}")
    return "\n".join(lines).replace("—", ",").replace("–", ",")
