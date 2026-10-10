"""Apply DMV-349 report determinations (IS / ADD / DEL / NIS) to the screened fiche.

A determinations file is JSON lines, one object per reviewed crash:
  {"n": 5, "crash_id": 108196690, "pages": [9, 10], "decision": "ADD", "in_section": "yes",
   "report_mp": 0.198, "report_location": "...", "facts": "...", "teaas_issue": "...", "confidence": "medium"}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .screen import Screened, Study

DECISIONS = ("IS", "ADD", "DEL", "NIS")


@dataclass
class Determination:
    n: int
    crash_id: int
    decision: str
    in_section: str
    report_mp: float | None
    report_location: str
    facts: str
    teaas_issue: str
    confidence: str
    pages: list[int]
    verified: bool = False
    verify_notes: str = ""

    @property
    def at_limit(self) -> bool:
        return "limit" in (self.in_section or "")


def load_determinations(path: str) -> dict[int, Determination]:
    out: dict[int, Determination] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            dec = d["decision"].upper()
            if dec not in DECISIONS:
                raise ValueError(f"bad decision {dec!r} for {d.get('crash_id')}")
            mp = d.get("report_mp")
            out[int(d["crash_id"])] = Determination(
                n=int(d.get("n", 0)), crash_id=int(d["crash_id"]), decision=dec, in_section=d.get("in_section", ""),
                report_mp=(None if mp is None or mp < 0 else float(mp)), report_location=d.get("report_location", ""),
                facts=d.get("facts", ""), teaas_issue=d.get("teaas_issue", ""), confidence=d.get("confidence", ""),
                pages=list(d.get("pages", [])), verified=bool(d.get("verified", False)), verify_notes=d.get("verify_notes", ""))
    return out


def apply_determinations(screened: list[Screened], dets: dict[int, Determination]) -> list[Screened]:
    """Set each reviewed crash's flag to its decision and write the report finding into its comment."""
    for s in screened:
        d = dets.get(s.row.crash_id)
        if not d:
            continue
        s.flag = d.decision
        s.priority = {"IS": 0, "ADD": 1, "DEL": 2, "NIS": 3}[d.decision]
        s.priority_label = {"IS": "In study", "ADD": "Added to study", "DEL": "Deleted from study", "NIS": "Not in study"}[d.decision]
        where = d.in_section if d.in_section not in ("yes", "no") else ("inside the section" if d.in_section == "yes" else "outside the section")
        mp = f"; report MP {d.report_mp:.3f}" if d.report_mp is not None else ""
        prefix = "in initial study; " if s.in_initial else ""
        s.comment = f"{prefix}report: {d.report_location}; {where}{mp}" + (f"; {d.teaas_issue}" if d.teaas_issue else "")
        s.reasons = [s.comment]
        if d.confidence:
            s.reasons.append(f"confidence {d.confidence}")
    return screened


def determination_table(screened: list[Screened], dets: dict[int, Determination]) -> list[dict]:
    """Rows for the review summary (markdown / JSON), in review order."""
    rows = []
    by_id = {s.row.crash_id: s for s in screened}
    for d in sorted(dets.values(), key=lambda x: x.n):
        s = by_id.get(d.crash_id)
        r = s.row if s else None
        rows.append({"n": d.n, "crash_id": d.crash_id, "date": r.date if r else "", "decision": d.decision,
                     "in_initial": bool(s.in_initial) if s else None, "in_section": d.in_section,
                     "report_mp": d.report_mp, "teaas_mp": (None if r is None or r.unmileposted else r.mp),
                     "teaas_on_road": r.on_road if r else "", "type": r.T if r else None, "severity": r.S if r else "",
                     "report_location": d.report_location, "facts": d.facts, "teaas_issue": d.teaas_issue,
                     "confidence": d.confidence, "pages": d.pages})
    return rows


def write_review_outputs(study: Study, screened: list[Screened], dets: dict[int, Determination], out_dir: str) -> list[str]:
    sid = study.study_id
    rows = determination_table(screened, dets)
    paths = []
    p = os.path.join(out_dir, f"{sid}_review_determinations.jsonl")
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    paths.append(p)
    # markdown summary for the memo
    p = os.path.join(out_dir, f"{sid}_ReportReview.md")
    counts = {k: sum(1 for r in rows if r["decision"] == k) for k in DECISIONS}
    lim = study.cfg["limits"]
    lines = [f"# DMV-349 report review, study {sid}", "",
             f"{study.cfg['route']['name']} ({study.cfg['route'].get('local_name', '')}) MP {lim['begin_mp']:.3f} ({lim['begin_desc']}) to "
             f"MP {lim['end_mp']:.3f} ({lim['end_desc']}). {len(rows)} reports read. "
             f"IS {counts['IS']}, ADD {counts['ADD']}, DEL {counts['DEL']}, NIS {counts['NIS']}.", "",
             "| # | Crash ID | Date | TEAAS coding | Report location | Report MP | Decision | Confidence |",
             "| --: | --: | --- | --- | --- | --: | --- | --- |"]
    for r in rows:
        tm = "999.999" if r["teaas_mp"] is None else f"{r['teaas_mp']:.3f}"
        rm = "" if r["report_mp"] is None else f"{r['report_mp']:.3f}"
        lines.append(f"| {r['n']} | {r['crash_id']} | {r['date']} | {r['teaas_on_road']} MP {tm} | {r['report_location']} | {rm} | "
                     f"{r['decision']}{' (' + r['in_section'] + ')' if r['in_section'] not in ('yes', 'no') else ''} | {r['confidence']} |")
    # section crash summary after the review (IS + ADD), with the at-limit crashes called out
    from .teaas import TYPE_LONG, SEVERITY_LONG
    by_id = {s.row.crash_id: s for s in screened}
    inside = [r for r in rows if r["decision"] in ("IS", "ADD")]
    at_limit = [r for r in inside if r["in_section"] not in ("yes", "no")]
    core = [r for r in inside if r["in_section"] == "yes"]
    def tally(rs, key):
        c = {}
        for r in rs:
            c[key(r)] = c.get(key(r), 0) + 1
        return sorted(c.items(), key=lambda kv: -kv[1])
    lines += ["", f"## Section crashes after the review: {len(inside)} ({len(core)} inside the limits, {len(at_limit)} at a limit)", "",
              "| Crash type | Inside | At a limit | Total |", "| --- | --: | --: | --: |"]
    types = sorted({r["type"] for r in inside}, key=lambda t: -sum(1 for r in inside if r["type"] == t))
    for t in types:
        a = sum(1 for r in core if r["type"] == t); b = sum(1 for r in at_limit if r["type"] == t)
        lines.append(f"| {TYPE_LONG.get(t, t)} | {a} | {b} | {a + b} |")
    lines += ["", "| Severity | Inside | At a limit | Total |", "| --- | --: | --: | --: |"]
    for sev in ("K", "A", "B", "C", "O"):
        a = sum(1 for r in core if (r["severity"] or "O") == sev); b = sum(1 for r in at_limit if (r["severity"] or "O") == sev)
        if a + b:
            lines.append(f"| {SEVERITY_LONG[sev]} | {a} | {b} | {a + b} |")
    if at_limit:
        lines += ["", "### Crashes at a limit (the PE's call)", ""]
        for r in at_limit:
            lines.append(f"- **{r['crash_id']}** ({r['date']}, {TYPE_LONG.get(r['type'], r['type'])}, {r['severity'] or 'O'}): {r['in_section']}, report MP {r['report_mp']:.3f}. {r['report_location']}")
    outside_near = [r for r in rows if r["decision"] == "NIS" and r["report_mp"] is not None and r["report_mp"] <= lim["begin_mp"] + 0.005]
    if outside_near:
        lines += ["", "### Reviewed and left out, between the NC 179 intersection and the begin limit", ""]
        for r in outside_near:
            lines.append(f"- **{r['crash_id']}** ({r['date']}, {TYPE_LONG.get(r['type'], r['type'])}, {r['severity'] or 'O'}): report MP {r['report_mp']:.3f}. {r['report_location']}")
    lines += ["", "## Facts from the reports", ""]
    for r in rows:
        lines.append(f"- **{r['crash_id']}** ({r['decision']}): {r['facts']}" + (f" _TEAAS: {r['teaas_issue']}_" if r["teaas_issue"] else ""))
    with open(p, "w") as f:
        f.write("\n".join(lines) + "\n")
    paths.append(p)
    return paths


def decisions_for_map(study: Study, screened: list[Screened], dets: dict[int, Determination]) -> dict[int, dict]:
    """Where to plot each reviewed crash on the crash map: report MP on the centerline, coordinates where they agree."""
    out = {}
    by_id = {s.row.crash_id: s for s in screened}
    for cid, d in dets.items():
        s = by_id.get(cid)
        entry = {"decision": d.decision, "mp": d.report_mp, "lat": None, "lon": None, "n": d.n,
                 "location": d.report_location, "facts": d.facts}
        if s and s.latlon and s.dmv_mp is not None and d.report_mp is not None and abs(s.dmv_mp - d.report_mp) <= 0.02:
            entry["lat"], entry["lon"] = s.latlon
        if cid == study.cfg["fatal"]["crash_id"]:
            entry["lat"], entry["lon"] = study.cfg["fatal"]["lat"], study.cfg["fatal"]["lon"]
        out[cid] = entry
    return out
