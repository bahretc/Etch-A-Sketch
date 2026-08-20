"""Generate the Filtered Fiche review sheet (docs/02, docs/03).

The Filtered Fiche is the working sheet where the engineer makes every
IS/RE/ADD/DEL/NIS determination. The app GENERATES it with a pre-screen so
review starts organized, and never fills a status the engineer has not made:

* Crashes already determined in-study (the TEAAS ID lists) get IS, or RE with
  the corrected milepost when the import file's milepost differs from the
  coded fiche milepost (section analyses only).
* Location candidates (on a study route within the milepost range, or not
  mileposted) are grouped for review with the status left BLANK.
* Everything else is grouped as NOT IN STUDY with status left blank; blanket
  NIS classification without review is not acceptable (docs/03).

Layout matches the completed 04-15-39049 workbook: A-H fiche columns,
I status, J New MP, K MA, L Crash ID, M Date, N-R T/C/F/L/S, S Comments.
"""
from __future__ import annotations

from .binned_sheet import _HEADERS, _fmt
from .models import Crash
from .xlsx_patch import render_row, replace_sheet_rows, sheet_row_styles

SHEET = "Filtered Fiche"
MP_SENTINEL = 999.999


def prescreen(
    fiche: list[Crash],
    before_ids: set[str],
    after_ids: set[str],
    mp_by_id: dict[str, float] | None = None,
    study_routes: set[str] | None = None,
    mp_range: tuple[float, float] | None = None,
    analysis_type: str = "section",
) -> dict[str, list[tuple[Crash, str | None, float | None]]]:
    """Group fiche crashes for review.

    Returns {'in_study' | 'review' | 'rest': [(crash, status, new_mp), ...]}.
    Statuses are only prefilled for the already-determined ID-list crashes.
    """
    mp_by_id = mp_by_id or {}
    in_ids = before_ids | after_ids
    groups: dict[str, list] = {"in_study": [], "review": [], "rest": []}

    def _candidate(crash: Crash) -> bool:
        on_route = study_routes and (crash.milepost_road in study_routes
                                     or crash.on_road in study_routes)
        if not on_route:
            return False
        if crash.mp is None or abs(crash.mp - MP_SENTINEL) < 1e-6:
            return True                       # not mileposted: needs review
        if mp_range:
            lo, hi = min(mp_range), max(mp_range)
            return lo - 1e-9 <= crash.mp <= hi + 1e-9
        return False

    for crash in fiche:
        if crash.crash_id in in_ids:
            new_mp = mp_by_id.get(crash.crash_id)
            remileposted = (
                analysis_type == "section" and new_mp is not None
                and (crash.mp is None
                     or abs(crash.mp - MP_SENTINEL) < 1e-6
                     or abs(crash.mp - new_mp) > 1e-9))
            status = "RE" if remileposted else "IS"
            groups["in_study"].append((crash, status, new_mp))
        elif _candidate(crash):
            groups["review"].append((crash, None, None))
        else:
            groups["rest"].append((crash, None, None))
    return groups


def build_filtered_rows_xml(template: str, groups: dict) -> str:
    styles = sheet_row_styles(template, SHEET, 3)
    banners = [
        ("in_study", "IN STUDY"),
        ("review", "REVIEW CANDIDATES - STATUS TO BE DETERMINED"),
        ("rest", "NOT IN STUDY CANDIDATES - NOT REVIEWED"),
    ]
    parts = [render_row(1, dict(_HEADERS))]
    row = 2
    for key, title in banners:
        parts.append(render_row(row, {"A": title}))
        row += 1
        for crash, status, new_mp in groups.get(key, []):
            parts.append(render_row(row, {
                "A": crash.muni_code or None, "B": crash.on_road or None,
                "C": crash.miles, "D": crash.dir_from or None,
                "E": crash.from_road or None, "F": crash.toward_road or None,
                "G": crash.milepost_road or None, "H": crash.mp,
                "I": status, "J": new_mp, "K": crash.ma or None,
                "L": (int(crash.crash_id) if crash.crash_id.isdigit()
                      else crash.crash_id),
                "M": _fmt(crash.date) if crash.date else None,
                "N": crash.t, "O": crash.c, "P": crash.f, "Q": crash.l,
                "R": crash.s or None, "S": crash.comments or None,
            }, styles))
            row += 1
    return "".join(parts)


ORIGINAL_SHEET = "Original Fiche"

#: Original Fiche columns: the fiche's own layout plus the DetailedFiche's
#: coordinates, which is what locates a crash when its milepost cannot.
_ORIGINAL_HEADERS = {
    "A": "Muni.\nCode", "B": "On Road", "C": "Miles", "D": "Dir From",
    "E": "From Road", "F": "Toward Road", "G": "Milepost Road", "H": "MP",
    "I": "MA", "J": "Crash ID", "K": "Date", "L": "T", "M": "C", "N": "F",
    "O": "L", "P": "S", "Q": "Latitude", "R": "Longitude", "S": "Source",
}


def build_original_rows_xml(template: str, fiche, coords: dict) -> str:
    """The full fiche dump for the Original Fiche sheet.

    ``coords`` maps crash_id to (latitude, longitude, source) from the
    DetailedFiche; rows without an entry keep those cells empty.
    """
    styles = sheet_row_styles(template, ORIGINAL_SHEET, 2)
    parts = [render_row(1, dict(_ORIGINAL_HEADERS))]
    for row, crash in enumerate(fiche, start=2):
        la, lo, src = coords.get(crash.crash_id, (None, None, None))
        parts.append(render_row(row, {
            "A": crash.muni_code or None, "B": crash.on_road or None,
            "C": crash.miles, "D": crash.dir_from or None,
            "E": crash.from_road or None, "F": crash.toward_road or None,
            "G": crash.milepost_road or None, "H": crash.mp,
            "I": crash.ma or None,
            "J": (int(crash.crash_id) if crash.crash_id.isdigit()
                  else crash.crash_id),
            "K": _fmt(crash.date) if crash.date else None,
            "L": crash.t, "M": crash.c, "N": crash.f, "O": crash.l,
            "P": crash.s or None, "Q": la, "R": lo, "S": src,
        }, styles))
    return "".join(parts)


def populate_original_sheet(template: str, output: str, fiche,
                            coords: dict) -> int:
    rows_xml = build_original_rows_xml(template, fiche, coords)
    replace_sheet_rows(template, output, ORIGINAL_SHEET, rows_xml,
                       from_row=1)
    return len(fiche)


def populate_filtered_sheet(
    template: str, output: str, fiche: list[Crash],
    before_ids: set[str], after_ids: set[str],
    mp_by_id: dict[str, float] | None = None,
    study_routes: set[str] | None = None,
    mp_range: tuple[float, float] | None = None,
    analysis_type: str = "section",
) -> dict[str, int]:
    groups = prescreen(fiche, before_ids, after_ids, mp_by_id,
                       study_routes, mp_range, analysis_type)
    rows_xml = build_filtered_rows_xml(template, groups)
    replace_sheet_rows(template, output, SHEET, rows_xml, from_row=1)
    return {k: len(v) for k, v in groups.items()}
