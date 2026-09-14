"""Populate the Binned Crashes sheet (docs/02, docs/03).

Every fiche crash lands under exactly one banner:

    NOT IN STUDY - BEFORE STUDY LIMITS   (in-study location, before the study)
    BEFORE PERIOD: {dates}
    CONSTRUCTION PERIOD: {dates}
    AFTER PERIOD: {dates}
    NIS CRASHES

Layout (verified on the completed 04-15-39049 workbook): header row 1 with
A-H fiche columns, I 'IS' status, J 'New MP', K 'MA', L 'Crash ID', M 'Date',
N-R 'T C F L S', S 'Comments'. Banners are text rows in column A.

Bin membership is derived from the TEAAS ID lists (the engineer's final
in-study determination) plus the study period dates; crashes on the study
route within the milepost range but dated before the before period go to the
prior bin. NIS statuses and review comments are the engineer's work and are
left blank here.
"""
from __future__ import annotations

from datetime import date

from .models import Crash, Period
from .xlsx_patch import render_row, replace_sheet_rows, sheet_row_styles

SHEET = "Binned Crashes"
HEADER_ROW = 1
DATA_START_ROW = 2

_HEADERS = {
    "A": "Muni.\nCode", "B": "On Road", "C": "Miles", "D": "Dir From",
    "E": "From Road", "F": "Toward Road", "G": "Milepost Road", "H": "MP",
    "I": "IS", "J": "New MP", "K": "MA", "L": "Crash ID", "M": "Date",
    "N": "T", "O": "C", "P": "F", "Q": "L", "R": "S", "S": "Comments",
}

_COLS = {
    "muni_code": "A", "on_road": "B", "miles": "C", "dir_from": "D",
    "from_road": "E", "toward_road": "F", "milepost_road": "G", "mp": "H",
    "status": "I", "new_mp": "J", "ma": "K", "crash_id": "L", "date": "M",
    "t": "N", "c": "O", "f": "P", "l": "Q", "s": "R", "comments": "S",
}


def _fmt(d: date) -> str:
    return f"{d.month}/{d.day}/{d.year}"


# Filtered Fiche status vocabulary (per the engineer):
#   Intersection analyses: IS / ADD / DEL / NIS (Reviewed and Not Reviewed)
#   Section analyses:      IS / RE / ADD / DEL / NIS (Reviewed and Not Reviewed)
# RE = re-milepost: in-study with a corrected milepost in New MP (section
# analyses only; every RE row on 04-15-39049 carries a New MP). DEL and NIS
# are out of the evaluation. Statuses here mean "in the evaluation".
IN_STUDY_STATUSES = {"IS", "ADD", "RE"}


def read_filtered_fiche(workbook_path: str,
                        sheet: str = "Filtered Fiche") -> dict[str, dict]:
    """Read the engineer's determinations from a Filtered Fiche sheet.

    The Filtered Fiche is where all IS/NIS/ADD/REV review decisions are made
    (docs/03); this reads them back so Binned Crashes can sort the evaluation
    crashes accordingly. Returns {crash_id: {status, new_mp, comments}}.
    """
    import openpyxl

    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        wb.close()
        raise KeyError(f"{workbook_path} has no {sheet!r} sheet")
    ws = wb[sheet]
    cols: dict[str, int] = {}
    out: dict[str, dict] = {}
    for row in ws.iter_rows(values_only=True):
        if not cols:
            if row and "Crash ID" in row:
                for i, v in enumerate(row):
                    if v is None:
                        continue
                    key = str(v).strip().lower().replace("\n", " ")
                    cols[key] = i
            continue
        cid_i = cols.get("crash id")
        if cid_i is None or cid_i >= len(row) or row[cid_i] is None:
            continue
        cid = str(row[cid_i]).strip()
        if not cid.isdigit():
            continue

        def _get(name):
            i = cols.get(name)
            return row[i] if i is not None and i < len(row) else None

        out[cid] = {
            "status": (str(_get("is")).strip().upper()
                       if _get("is") is not None else None),
            "new_mp": _get("new mp"),
            "comments": _get("comments"),
        }
    wb.close()
    return out


def validate_statuses(statuses: dict[str, dict], analysis_type: str) -> None:
    """Reject statuses that are invalid for the analysis type.

    RE (re-milepost) exists only in section analyses; encountering one in an
    intersection analysis means the review data is wrong and must be fixed,
    not silently binned (per the engineer, 2026-07).
    """
    allowed = {"intersection": {"IS", "ADD", "DEL", "NIS"},
               "section": {"IS", "RE", "ADD", "DEL", "NIS"}}.get(analysis_type)
    if allowed is None:
        raise ValueError(f"Unknown analysis type: {analysis_type!r}")
    bad: dict[str, list[str]] = {}
    for cid, det in statuses.items():
        status = det.get("status")
        if status and status not in allowed:
            bad.setdefault(status, []).append(cid)
    if bad:
        detail = "; ".join(
            f"{status!r} on {len(ids)} crash(es), e.g. {ids[:3]}"
            for status, ids in sorted(bad.items()))
        raise ValueError(
            f"Invalid Filtered Fiche status(es) for an {analysis_type} "
            f"analysis: {detail}. Allowed: {sorted(allowed)}.")


def analysis_type_of(template: str) -> str:
    """'section' when the Before sheet has a Final MP column, else 'intersection'."""
    from .eval_workbook import sheet_layout

    layout = sheet_layout(template, "Before")
    return "section" if "final_mp" in layout else "intersection"


def assign_bins(
    fiche: list[Crash],
    before_ids: set[str],
    after_ids: set[str],
    periods: dict[str, Period],
    study_routes: set[str] | None = None,
    mp_range: tuple[float, float] | None = None,
    statuses: dict[str, dict] | None = None,
    in_study_statuses: set[str] = frozenset(IN_STUDY_STATUSES),
) -> dict[str, list[Crash]]:
    """Split all fiche crashes into ordered bins.

    When ``statuses`` (from :func:`read_filtered_fiche`) is provided it is the
    AUTHORITY: the engineer's IS/ADD/RE (re-milepost) determinations bin by
    crash date into prior/before/construction/after; DEL and NIS go to the
    NIS section. The ID lists and the route/milepost heuristic are only a
    pre-screen for evaluations whose Filtered Fiche review has not happened
    yet.
    """
    bins: dict[str, list[Crash]] = {
        "prior": [], "before": [], "construction": [], "after": [], "nis": [],
    }
    b, c, a = periods["before"], periods["construction"], periods["after"]

    def _bin_by_date(crash: Crash) -> str:
        if crash.date is None:
            return "nis"
        if crash.date < b.start:
            return "prior"
        if crash.date <= b.end:
            return "before"
        if crash.date <= c.end:
            return "construction"
        if crash.date <= a.end:
            return "after"
        return "nis"

    if statuses is not None:
        for crash in fiche:
            det = statuses.get(crash.crash_id)
            status = (det or {}).get("status")
            if status in in_study_statuses:
                bins[_bin_by_date(crash)].append(crash)
            else:
                bins["nis"].append(crash)
        return bins

    # pre-screen fallback (no Filtered Fiche review yet)
    def _at_location(crash: Crash) -> bool:
        if mp_range and crash.mp is not None:
            lo, hi = min(mp_range), max(mp_range)
            on_route = (not study_routes
                        or crash.milepost_road in study_routes
                        or crash.on_road in study_routes)
            return on_route and lo - 1e-9 <= crash.mp <= hi + 1e-9
        return False

    for crash in fiche:
        if crash.crash_id in before_ids:
            bins["before"].append(crash)
        elif crash.crash_id in after_ids:
            bins["after"].append(crash)
        elif _at_location(crash) and crash.date is not None:
            if crash.date < b.start:
                bins["prior"].append(crash)
            elif c.start <= crash.date <= c.end:
                bins["construction"].append(crash)
            else:
                bins["nis"].append(crash)
        else:
            bins["nis"].append(crash)
    return bins


def build_binned_rows_xml(
    template: str,
    bins: dict[str, list[Crash]],
    periods: dict[str, Period],
    mp_by_id: dict[str, float] | None = None,
    statuses: dict[str, str] | None = None,
) -> str:
    """Render the header + banner + crash-row XML for the sheet.

    The pristine template ships this sheet EMPTY (the analyst pastes the
    filtered fiche in), so the header row is created here to match the
    completed-workbook layout.
    """
    styles = sheet_row_styles(template, SHEET, 3)   # inherit any template look
    banner_style = sheet_row_styles(template, SHEET, 2)
    mp_by_id = mp_by_id or {}
    statuses = statuses or {}
    b, c, a = periods["before"], periods["construction"], periods["after"]
    banners = [
        ("prior", "NOT IN STUDY - BEFORE STUDY LIMITS"),
        ("before", f"BEFORE PERIOD: {_fmt(b.start)} - {_fmt(b.end)}"),
        ("construction",
         f"CONSTRUCTION PERIOD: {_fmt(c.start)} - {_fmt(c.end)}"),
        ("after", f"AFTER PERIOD: {_fmt(a.start)} - {_fmt(a.end)}"),
        ("nis", "NIS CRASHES"),
    ]

    parts: list[str] = [render_row(HEADER_ROW, dict(_HEADERS))]
    row = DATA_START_ROW
    for key, title in banners:
        parts.append(render_row(row, {"A": title},
                                banner_style or {"A": None}))
        row += 1
        for crash in bins.get(key, []):
            default_status = "IS" if key in ("before", "after") else None
            cells = {
                _COLS["muni_code"]: crash.muni_code or None,
                _COLS["on_road"]: crash.on_road or None,
                _COLS["miles"]: crash.miles,
                _COLS["dir_from"]: crash.dir_from or None,
                _COLS["from_road"]: crash.from_road or None,
                _COLS["toward_road"]: crash.toward_road or None,
                _COLS["milepost_road"]: crash.milepost_road or None,
                _COLS["mp"]: crash.mp,
                _COLS["status"]: statuses.get(crash.crash_id, default_status),
                _COLS["new_mp"]: mp_by_id.get(crash.crash_id),
                _COLS["ma"]: crash.ma or None,
                _COLS["crash_id"]: (int(crash.crash_id)
                                    if crash.crash_id.isdigit()
                                    else crash.crash_id),
                # string form: the empty template sheet has no date styles, so
                # a raw serial would display as a bare number
                _COLS["date"]: _fmt(crash.date) if crash.date else None,
                _COLS["t"]: crash.t, _COLS["c"]: crash.c,
                _COLS["f"]: crash.f, _COLS["l"]: crash.l,
                _COLS["s"]: crash.s or None,
                _COLS["comments"]: crash.comments or None,
            }
            parts.append(render_row(row, cells, styles))
            row += 1
    return "".join(parts)


def populate_binned_sheet(
    template: str,
    output: str,
    fiche: list[Crash],
    before_ids: set[str],
    after_ids: set[str],
    periods: dict[str, Period],
    mp_by_id: dict[str, float] | None = None,
    study_routes: set[str] | None = None,
    mp_range: tuple[float, float] | None = None,
    statuses: dict[str, dict] | None = None,
) -> dict[str, int]:
    """Bin all fiche crashes and write the sheet. Returns bin counts.

    ``statuses`` (from :func:`read_filtered_fiche`) is authoritative when
    given; the engineer's status text and review comments carry into the
    sheet."""
    bins = assign_bins(fiche, before_ids, after_ids, periods,
                       study_routes=study_routes, mp_range=mp_range,
                       statuses=statuses)
    status_text: dict[str, str] = {}
    if statuses:
        for cid, det in statuses.items():
            if det.get("status"):
                status_text[cid] = det["status"]
        by_id = {c.crash_id: c for c in fiche}
        for cid, det in statuses.items():
            crash = by_id.get(cid)
            if crash is not None:
                if det.get("comments") and not crash.comments:
                    crash.comments = str(det["comments"])
                if det.get("new_mp") is not None and cid not in (mp_by_id or {}):
                    mp_by_id = dict(mp_by_id or {})
                    mp_by_id[cid] = det["new_mp"]
    rows_xml = build_binned_rows_xml(template, bins, periods, mp_by_id,
                                     statuses=status_text or None)
    replace_sheet_rows(template, output, SHEET, rows_xml, from_row=HEADER_ROW)
    return {k: len(v) for k, v in bins.items()}
