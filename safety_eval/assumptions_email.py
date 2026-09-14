"""Assumptions email generator (docs/05).

Follows the team template exactly (verified against the App B example,
'Assumptions Email - Intersection Example.docx'): a heading and a fixed bullet
sequence. A missing bullet is a review finding, so every field is emitted;
optional ones show 'n/a' rather than disappearing (except Signal ID, omitted
entirely when None per docs/05 for pure AWSC conversions).

File naming: 'Assumptions Email - {order-id} ({project-id}).docx'.
Style: plain and understated, no em dashes (enforced).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .results_sheet import check_style


@dataclass
class AssumptionsData:
    order_id: str = ""
    project_id: str = ""
    gps: str = ""                       # "35.729528, -77.935417"
    county: str = ""
    division: str = ""
    study_type: str = ""                # e.g. "Intersection Analysis with a 150' Y-line"
    location: str = ""
    signal_id: str | None = None        # None = omit the bullet entirely
    countermeasure: str = ""
    statement_of_problem: str = ""
    project_cost: str = ""
    project_completion: str = ""
    completion_notes: list = field(default_factory=list)   # sub-bullets
    teaas_date: date | None = None      # for computed time periods
    construction_months: int | None = None
    construction_end: date | None = None
    target_crashes: str = ""
    project_dev_summary: str = ""
    additional_notes: list = field(default_factory=list)


def _fmt(d: date) -> str:
    return f"{d.month}/{d.day}/{d.year}"


def _span_text(start: date, end: date) -> str:
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    y, m = divmod(months, 12)
    parts = []
    if y:
        parts.append(f"{y} year" + ("s" if y != 1 else ""))
    if m:
        parts.append(f"{m} month" + ("s" if m != 1 else ""))
    return f"{_fmt(start)} - {_fmt(end)} ({', '.join(parts)})"


def _add_hyperlink(paragraph, url: str, text: str) -> None:
    import docx.opc.constants
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    part = paragraph.part
    r_id = part.relate_to(url, docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK,
                          is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    style = OxmlElement("w:rStyle")
    style.set(qn("w:val"), "Hyperlink")
    rpr.append(style)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def generate_assumptions_email(data: AssumptionsData, output_path: str) -> str:
    """Write the .docx; returns the path. All text passes the style gate."""
    import docx

    for name in ("countermeasure", "statement_of_problem", "target_crashes",
                 "project_dev_summary", "location"):
        value = getattr(data, name)
        if value:
            check_style(str(value), name)
    for i, note in enumerate(list(data.completion_notes)
                             + list(data.additional_notes)):
        check_style(str(note), f"note[{i}]")

    doc = docx.Document()
    doc.add_heading("Evaluation Assumptions", level=1)

    def bullet(label: str, value: str = "", style: str = "List Bullet"):
        p = doc.add_paragraph(style=style)
        run = p.add_run(f"{label}: " if label else "")
        run.bold = bool(label)
        if value:
            p.add_run(str(value))
        return p

    bullet("Order ID", data.order_id or "n/a")
    bullet("Project ID", data.project_id or "n/a")
    p = bullet("GPS Coordinates")
    if data.gps:
        coords = data.gps.replace(" ", "")
        _add_hyperlink(p, f"https://www.google.com/maps/place/{coords}",
                       data.gps)
    else:
        p.add_run("n/a")
    bullet("County / Division",
           f"{data.county} County / Division {data.division}".strip())
    bullet("Study Type", data.study_type or "n/a")
    bullet("Location", data.location or "n/a")
    if data.signal_id is not None:
        bullet("Signal ID", data.signal_id or "n/a")
    bullet("Countermeasure", data.countermeasure or "n/a")
    bullet("Statement of Problem", data.statement_of_problem or "n/a")
    bullet("Project Cost", data.project_cost or "n/a")
    bullet("Project Completion", data.project_completion or "n/a")
    for note in data.completion_notes:
        bullet("", str(note), style="List Bullet 2")

    bullet("Time Periods")
    if data.teaas_date and data.construction_months and data.construction_end:
        from .periods import compute_whole_month_periods
        p = compute_whole_month_periods(data.teaas_date,
                                        data.construction_months,
                                        data.construction_end)
        bullet("", "Before Period: "
               + _span_text(p["before"].start, p["before"].end),
               style="List Bullet 2")
        bullet("", "Construction: "
               + _span_text(p["construction"].start, p["construction"].end),
               style="List Bullet 2")
        bullet("", "After Period: "
               + _span_text(p["after"].start, p["after"].end),
               style="List Bullet 2")
    else:
        bullet("", "To be confirmed with the crash data end date",
               style="List Bullet 2")

    bullet("Target Crashes", data.target_crashes or "n/a")
    bullet("Project Dev Crash Summary", data.project_dev_summary or "n/a")
    if data.additional_notes:
        bullet("Additional Notes")
        for note in data.additional_notes:
            bullet("", str(note), style="List Bullet 2")

    doc.save(output_path)
    return output_path


def load_assumptions_yaml(path: str) -> AssumptionsData:
    import yaml

    from .assignment import _as_date

    with open(path) as fh:
        d = yaml.safe_load(fh) or {}
    return AssumptionsData(
        order_id=str(d.get("order_id", "")),
        project_id=str(d.get("project_id", "")),
        gps=str(d.get("gps", "")), county=str(d.get("county", "")),
        division=str(d.get("division", "")),
        study_type=str(d.get("study_type", "")),
        location=str(d.get("location", "")),
        signal_id=(str(d["signal_id"]) if "signal_id" in d
                   and d["signal_id"] is not None else None),
        countermeasure=str(d.get("countermeasure", "")),
        statement_of_problem=str(d.get("statement_of_problem", "")),
        project_cost=str(d.get("project_cost", "")),
        project_completion=str(d.get("project_completion", "")),
        completion_notes=list(d.get("completion_notes", []) or []),
        teaas_date=_as_date(d.get("teaas_date")),
        construction_months=(int(d["construction_months"])
                             if d.get("construction_months") else None),
        construction_end=_as_date(d.get("construction_end")),
        target_crashes=str(d.get("target_crashes", "")),
        project_dev_summary=str(d.get("project_dev_summary", "")),
        additional_notes=list(d.get("additional_notes", []) or []),
    )


def default_filename(data: AssumptionsData) -> str:
    return f"Assumptions Email - {data.order_id} ({data.project_id}).docx"
