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
             "Every sentence in Items for Discussion supported by the data; counts in the at-fault breakdown match the "
             "Additional Information rows; no em or en dashes; consistent route naming, county, division, dates, PE and "
             "firm; countermeasure and target text match the assumptions email; placeholders; unexplained route numbers; "
             "text that relied on a volume trend that no longer holds."),
    "teaas": ("TEAAS CROSS-CHECK",
              "TEAAS report totals, severity breakdowns and indices versus the workbook and results page; Study Criteria "
              "dates, Y-line, road combinations, Included and Excluded Accidents versus ADD/DEL; ADT used by TEAAS versus "
              "the workbook representative volumes; run date versus the results page date; crash ID lists versus import files."),
    "pdf": ("PDF ASSEMBLY",
            "Page counts and order; results page text versus the workbook cells including the Volume row; disclaimer "
            "present; TEAAS pages identical to the standalone reports; embedded aerial not downsampled; margins match the "
            "Excel print; PDF metadata; zip contents versus the folder."),
}

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

    def by_status(self, status: str) -> list:
        return [f for f in self.findings if f.status == status]


# --------------------------------------------------------------------------- #
# package to text
# --------------------------------------------------------------------------- #
def _clip(text: str, limit: int = MAX_CHARS_PER_PART) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def workbook_text(path: str, sheets: dict | None = None) -> str:
    """Key sheets as compact 'cell=value' text."""
    import openpyxl

    sheets = sheets or {"Evaluation Set-up": "A1:R40", "1 page results - 1 Target": "B2:L75",
                        "Before": "A1:M120", "After": "A1:M120", "Binned Crashes": "A1:U200",
                        "For NCDOT staff - for Tracking": "A1:BE8"}
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out = [f"# Workbook {os.path.basename(path)}; sheets: {', '.join(wb.sheetnames)}"]
    for name, rng in sheets.items():
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


def pdf_text(path: str, max_pages: int = 30) -> str:
    from .print_results import pdf_page_texts

    pages = pdf_page_texts(path)
    parts = [f"--- page {i + 1} ---\n{p.strip()}" for i, p in enumerate(pages[:max_pages])]
    return _clip(f"# PDF {os.path.basename(path)} ({len(pages)} pages)\n" + "\n".join(parts))


def gather_context(package_dir: str, workbook: str | None = None) -> dict[str, str]:
    """{part name: text} for everything a reviewer can read."""
    ctx: dict[str, str] = {}
    inventory = []
    for dp, _, fn in os.walk(package_dir):
        for f in sorted(fn):
            p = os.path.join(dp, f)
            inventory.append(f"{os.path.relpath(p, package_dir)} ({os.path.getsize(p)} bytes)")
            low = f.lower()
            rel = os.path.relpath(p, package_dir)
            try:
                if low.endswith(".xlsx") and (workbook is None or os.path.samefile(p, workbook)):
                    ctx[rel] = workbook_text(p)
                elif low.endswith(".pdf") and "redact" not in low:
                    ctx[rel] = pdf_text(p)
                elif low.endswith((".md", ".txt", ".jsonl", ".csv")) and os.path.getsize(p) < 400_000:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        ctx[rel] = _clip(f"# {rel}\n" + fh.read())
            except Exception as exc:  # noqa: BLE001 - a bad part is reported, not fatal
                ctx[rel] = f"# {rel}\n[could not read: {exc}]"
    ctx["_inventory"] = "# Package inventory\n" + "\n".join(inventory)
    return ctx


def context_blocks(ctx: dict[str, str]) -> list[dict]:
    """Cacheable system blocks: rules first, then the package text."""
    blocks = [{"type": "text", "text": RULES}]
    body = "\n\n".join(ctx[k] for k in sorted(ctx))
    blocks.append({"type": "text", "text": "PACKAGE MATERIAL\n\n" + body,
                   "cache_control": {"type": "ephemeral"}})
    return blocks


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
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(text)


def review_dimension(client, key: str, system: list, model: str, effort: str, usage: dict) -> tuple[list, list]:
    title, brief = DIMENSIONS[key]
    user = (f"You are the {title} reviewer for this safety evaluation package. Scope: {brief}\n"
            "Read the package material in the system context and report findings with exact evidence "
            "(cell addresses, crash ids, page numbers, values). Also list what you verified with no discrepancy. "
            "Severity: High = wrong number or membership on the deliverable; Medium = inconsistency a reviewer "
            "would question; Low = hygiene.")
    data = _json_call(client, model, system, user, FINDINGS_SCHEMA, effort, usage)
    findings = [SweepFinding(id=f"{key}-{i + 1}", dimension=key, **f) for i, f in enumerate(data["findings"])]
    return findings, data.get("verified", [])


def refute(client, index: int, findings: list, system: list, model: str, effort: str, usage: dict) -> list[dict]:
    listing = "\n".join(f"[{f.id}] ({f.severity}) {f.where}: {f.claim}\n   evidence: {f.evidence}\n   proposed fix: {f.fix}"
                        for f in findings)
    user = (f"You are independent verifier {index + 1} of 3. For EACH finding below, try to disprove it against the "
            "package material. Return CONFIRMED only when you personally located the evidence in the material, "
            "REFUTED when the material contradicts it or the rule cited does not apply, PARTIAL when the facts hold "
            "but the severity or fix is wrong. Say whether the proposed fix is safe and give a better one if not.\n\n"
            + listing)
    data = _json_call(client, model, system, user, VERDICTS_SCHEMA, effort, usage)
    return data["verdicts"]


def run_sweep(ctx: dict[str, str], client=None, model: str = DEFAULT_MODEL, dimensions: list | None = None,
              n_refuters: int = 3, effort: str = "high", progress=None, max_workers: int = 6) -> SweepReport:
    """Reviewers in parallel, then refuters in parallel over the merged findings."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    dims = dimensions or list(DIMENSIONS)
    system = context_blocks(ctx)
    report = SweepReport()
    usage: dict = {}

    def _p(msg: str):
        if progress:
            progress(msg)

    _p(f"reviewing {len(dims)} dimensions")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(review_dimension, client, d, system, model, effort, usage): d for d in dims}
        for fut, d in futs.items():
            try:
                findings, verified = fut.result()
                report.findings.extend(findings)
                report.verified[d] = verified
                _p(f"{DIMENSIONS[d][0]}: {len(findings)} finding(s)")
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{d}: {exc}")
                _p(f"{d} failed: {exc}")
    if report.findings and n_refuters > 0:
        _p(f"refuting {len(report.findings)} finding(s) with {n_refuters} verifiers")
        by_id = {f.id: f for f in report.findings}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(refute, client, i, report.findings, system, model, effort, usage) for i in range(n_refuters)]
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
    if report.errors:
        lines.append("## Errors")
        lines += [f"- {e}" for e in report.errors]
    if report.usage:
        lines.append(f"\nTokens: {report.usage}")
    return "\n".join(lines).replace("—", ",").replace("–", ",")
