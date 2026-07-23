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


def assign_bins(
    fiche: list[Crash],
    before_ids: set[str],
    after_ids: set[str],
    periods: dict[str, Period],
    study_routes: set[str] | None = None,
    mp_range: tuple[float, float] | None = None,
) -> dict[str, list[Crash]]:
    """Split all fiche crashes into ordered bins.

    In-study membership comes from the ID lists; a crash outside them that
    sits on a study route within the milepost range but predates the before
    period goes to 'prior'; a construction-window crash at the study location
    goes to 'construction'; everything else is NIS.
    """
    bins: dict[str, list[Crash]] = {
        "prior": [], "before": [], "construction": [], "after": [], "nis": [],
    }
    b, c, a = periods["before"], periods["construction"], periods["after"]

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
) -> dict[str, int]:
    """Bin all fiche crashes and write the sheet. Returns bin counts."""
    bins = assign_bins(fiche, before_ids, after_ids, periods,
                       study_routes=study_routes, mp_range=mp_range)
    rows_xml = build_binned_rows_xml(template, bins, periods, mp_by_id)
    replace_sheet_rows(template, output, SHEET, rows_xml, from_row=HEADER_ROW)
    return {k: len(v) for k, v in bins.items()}
