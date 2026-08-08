"""Interactive fiche review queue (docs/07 Phase 3, rules from docs/03).

The queue drives the engineer's crash-by-crash review of a Filtered Fiche:

* rows are read back from the workbook (column positions detected from the
  header row, so both the generated layout and completed workbooks like
  SS-6002M with extra Crash Type / Section / ledger columns work);
* rows still needing a determination are queued first, ordered by a
  GPS-distance pre-screen when DetailedFiche coordinates are available and
  by milepost distance to the study section otherwise;
* animal crashes are flagged to skip (docs/03: no report review needed);
* every determination is validated against the status vocabulary for the
  analysis type (RE is a data error in intersection analyses; RE requires a
  New MP) and the docs/03+05 comment conventions;
* every accepted determination is appended to a JSONL audit trail;
* determinations are written back into the workbook by per-cell XML patching
  (docs/06), leaving every other cell and sheet untouched.

The tool prepares and records; the engineer decides.  Nothing here ever
assigns a status by itself, and blanket reclassification is impossible by
construction (one determination call per crash, each audited).
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .xlsx_patch import CellEdit, xlsx_patch

DEFAULT_SHEET = "Filtered Fiche"

#: Base status vocabulary per analysis type (docs/03, corrected 2026-07).
STATUS_VOCAB = {
    "intersection": ("IS", "ADD", "DEL", "NIS"),
    "section": ("IS", "RE", "ADD", "DEL", "NIS"),
}

#: The determination vocabulary is not a flat five-way choice. It is two
#: branches, and which branch applies is fixed before review by one fact: was
#: the crash in the Initial Study?
#:
#:   in the Initial Study   -> IS   (stays, milepost confirmed)
#:                             RE   (belongs, coded milepost wrong; section only)
#:                             DEL  (does not belong; struck from the study)
#:   not in the Initial Study -> ADD  (belongs after all; added)
#:                               NIS  (does not belong; "NOT IN STUDY - REPORT
#:                                     REVIEWED")
#:
#: So the moves run one way only. IS may become RE; RE never becomes IS. DEL and
#: NIS both mean "not in this study" and are never interchangeable, because they
#: start from opposite branches, and the same goes for ADD against RE.
#:
#: Membership is a property of the input crash list, never inferred from the
#: coded milepost: crashes coded on a cross street at MP 1.44 were in the study,
#: and inferring the flag from the milepost mislabelled 5 of 47 real rows.
IN_STUDY_BRANCH = ("IS", "RE", "DEL")
NOT_IN_STUDY_BRANCH = ("ADD", "NIS")


def branch_vocab(analysis_type: str, in_initial_study: bool | None):
    """The statuses actually available to one crash, narrowest first.

    ``None`` means membership is unknown, and the full vocabulary stays open.
    """
    vocab = STATUS_VOCAB.get(analysis_type, STATUS_VOCAB["intersection"])
    if in_initial_study is None:
        return tuple(vocab)
    branch = IN_STUDY_BRANCH if in_initial_study else NOT_IN_STUDY_BRANCH
    return tuple(s for s in vocab if s in branch)

#: Statuses that may carry a second-section suffix ("IS-2", "RE-2", ...) in
#: split-section evaluations (observed throughout the completed SS-6002M
#: Filtered Fiche).
_SUFFIX_RE = re.compile(r"^([A-Z]+)(?:-(\d+))?$")

#: TEAAS T-code for animal crashes (docs/09).
ANIMAL_T_CODE = 17

_HEADER_ALIASES = {
    "muni. code": "muni_code", "muni code": "muni_code",
    "on road": "on_road", "miles": "miles",
    "dir from": "dir_from", "from road": "from_road",
    "toward road": "toward_road", "milepost road": "milepost_road",
    "mp": "mp", "is?": "status", "is": "status", "new mp": "new_mp",
    "ma": "ma", "crash id": "crash_id", "date": "date",
    "t": "t", "c": "c", "f": "f", "l": "l", "s": "s",
    "crash type": "crash_type", "comment": "comment", "comments": "comment",
    "section": "section",
}


def _col_letter(idx: int) -> str:
    out = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


@dataclass
class ReviewRow:
    """One crash row of the Filtered Fiche, with its sheet position."""
    crash_id: str
    row: int                              # 1-based sheet row
    banner: str = ""                      # section banner the row sits under
    status: str | None = None
    new_mp: float | None = None
    comment: str | None = None
    fields: dict = field(default_factory=dict)   # header-keyed cell values

    @property
    def is_animal(self) -> bool:
        t = self.fields.get("t")
        try:
            return int(t) == ANIMAL_T_CODE
        except (TypeError, ValueError):
            return str(self.fields.get("crash_type", "")).strip().lower() == "animal"

    @property
    def mp(self) -> float | None:
        v = self.fields.get("mp")
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


@dataclass
class ReviewSheet:
    """The Filtered Fiche read back with header-detected column positions."""
    path: str
    sheet: str
    rows: list[ReviewRow]
    columns: dict[str, str]               # role -> column letter

    def by_id(self) -> dict[str, ReviewRow]:
        return {r.crash_id: r for r in self.rows}


def load_review_sheet(workbook_path: str,
                      sheet: str = DEFAULT_SHEET) -> ReviewSheet:
    """Read every crash row (and its banner) from a Filtered Fiche sheet."""
    import openpyxl

    wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        wb.close()
        raise KeyError(f"{workbook_path} has no {sheet!r} sheet")
    ws = wb[sheet]
    roles: dict[int, str] = {}
    columns: dict[str, str] = {}
    rows: list[ReviewRow] = []
    banner = ""
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        if not roles:
            if row and any(str(v or "").strip().lower().startswith("crash id")
                           for v in row):
                for j, v in enumerate(row):
                    key = str(v or "").strip().lower().replace("\n", " ")
                    role = _HEADER_ALIASES.get(key)
                    if role and role not in columns:
                        roles[j] = role
                        columns[role] = _col_letter(j)
                if "status" in columns and "new_mp" not in columns:
                    # standalone fiche workbooks leave the New MP header
                    # blank; the column sits immediately right of the status
                    # column in every observed layout (SS-6002M, 260412109EA)
                    j = next(k for k, r in roles.items() if r == "status") + 1
                    if j not in roles:
                        roles[j] = "new_mp"
                        columns["new_mp"] = _col_letter(j)
            continue
        vals = {role: row[j] if j < len(row) else None
                for j, role in roles.items()}
        cid = vals.get("crash_id")
        if cid is None or not str(cid).strip().isdigit():
            first = next((v for v in row if v not in (None, "")), None)
            if first is not None and isinstance(first, str):
                banner = first.strip()
            continue
        status = vals.get("status")
        new_mp = vals.get("new_mp")
        rows.append(ReviewRow(
            crash_id=str(cid).strip(),
            row=i,
            banner=banner,
            status=str(status).strip().upper() if status not in (None, "") else None,
            new_mp=float(new_mp) if isinstance(new_mp, (int, float)) else None,
            comment=str(vals["comment"]) if vals.get("comment") not in (None, "") else None,
            fields=vals,
        ))
    wb.close()
    return ReviewSheet(path=workbook_path, sheet=sheet, rows=rows,
                       columns=columns)


# --------------------------------------------------------------------------- #
# determinations
# --------------------------------------------------------------------------- #
@dataclass
class Determination:
    crash_id: str
    status: str
    new_mp: float | None = None
    comment: str | None = None


def split_status(status: str) -> tuple[str, str | None]:
    """'RE-2' -> ('RE', '2'); 'IS' -> ('IS', None)."""
    m = _SUFFIX_RE.match(status.strip().upper())
    if not m:
        return status.strip().upper(), None
    return m.group(1), m.group(2)


def validate_determination(det: Determination, analysis_type: str,
                           reviewed: bool = True,
                           in_initial_study: bool | None = None) -> list[str]:
    """Return the list of rule violations (empty when acceptable).

    Encodes docs/03 exactly:
    * status must be in the vocabulary for the analysis type; RE in an
      intersection analysis is rejected as a data error;
    * RE must carry the corrected milepost in New MP;
    * ADD and DEL must say why (comment required); a reviewed NIS must say
      what the report showed, an unreviewed NIS must not claim review;
    * comments follow docs/05 style (no em dashes).
    """
    problems: list[str] = []
    vocab = STATUS_VOCAB.get(analysis_type)
    if vocab is None:
        return [f"Unknown analysis type: {analysis_type!r}"]
    base, _suffix = split_status(det.status)
    if base not in vocab:
        if base == "RE":
            problems.append(
                "RE (re-milepost) is only valid in section analyses; in an "
                "intersection analysis it is a data error (docs/03).")
        else:
            problems.append(
                f"Status {det.status!r} is not in the {analysis_type} "
                f"vocabulary {vocab}.")
    if in_initial_study is not None and base in vocab:
        allowed = branch_vocab(analysis_type, in_initial_study)
        if base not in allowed:
            where = ("was in the Initial Study" if in_initial_study
                     else "was not in the Initial Study")
            problems.append(
                f"Status {det.status!r} is not available to a crash that "
                f"{where}; that branch allows {', '.join(allowed)} (docs/03).")
    if base == "RE" and det.new_mp is None:
        problems.append("RE requires the corrected milepost in New MP "
                        "(every RE row carries one, docs/03).")
    if base in ("ADD", "DEL") and not (det.comment or "").strip():
        problems.append(f"{base} requires a brief comment saying why "
                        "(docs/03 comment conventions).")
    if base == "NIS" and reviewed and not (det.comment or "").strip():
        problems.append("A reviewed NIS needs a comment recording what the "
                        "report showed; blanket NIS without review is not "
                        "acceptable (docs/03).")
    for ch in ("—", "–"):
        if ch in (det.comment or ""):
            problems.append("No em or en dashes in comments (docs/05 style).")
            break
    return problems


# --------------------------------------------------------------------------- #
# GPS pre-screen
# --------------------------------------------------------------------------- #
def haversine_ft(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in feet."""
    r_ft = 20_902_231.0                       # mean Earth radius in feet
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_ft * math.asin(math.sqrt(a))


def _coord_rows(header, rows) -> dict[str, tuple[float, float]]:
    """Extract {crash_id: (lat, lon)} given a header row and data rows."""
    cols: dict[str, int] = {}
    for i, cell in enumerate(header):
        p = str(cell or "").strip().upper()
        if "CRASH" in p and "ID" in p:
            cols.setdefault("id", i)
        elif "LATITUDE" in p or p == "LAT":
            cols.setdefault("lat", i)
        elif "LONGITUDE" in p or p == "LONG":
            cols.setdefault("lon", i)
    out: dict[str, tuple[float, float]] = {}
    if len(cols) < 3:
        return out
    for row in rows:
        try:
            cid = str(row[cols["id"]]).strip()
            if not cid.isdigit():
                continue
            lat = float(row[cols["lat"]])
            lon = float(row[cols["lon"]])
        except (TypeError, IndexError, ValueError):
            continue
        if lat or lon:
            out[cid] = (lat, lon)
    return out


def parse_shape_points(source: str, route: str,
                       sheet: str | None = None) -> list:
    """``(milepost, lat, lon)`` for every DetailedFiche crash coded ON
    ``route``, milepost order.

    This is the corridor's route shape, sampled by the study's own crashes:
    with the NCDOT LRS unreachable, hundreds of coded crashes on the
    milepost road ARE a dense (milepost, coordinate) map of it. Feed the
    result to ``location.clean_shape`` and put it on the inventory so
    ``resolve`` can convert coordinates to a milepost instead of reporting
    that it cannot.
    """
    from .location import normalize_route
    want = normalize_route(route)
    for header, rows in _fiche_tables(source, sheet):
        cols: dict[str, int] = {}
        for i, cell in enumerate(header):
            p = str(cell or "").strip().upper()
            if "MILEPOST" in p and "ROAD" in p:
                cols.setdefault("road", i)
            elif p == "MP" or p == "MILEPOST":
                cols.setdefault("mp", i)
            elif "LATITUDE" in p or p == "LAT":
                cols.setdefault("lat", i)
            elif "LONGITUDE" in p or p == "LONG":
                cols.setdefault("lon", i)
        if len(cols) < 4:
            continue
        pts = []
        for row in rows:
            try:
                if normalize_route(str(row[cols["road"]] or "")) != want:
                    continue
                mp = float(row[cols["mp"]])
                lat, lon = float(row[cols["lat"]]), float(row[cols["lon"]])
            except (TypeError, IndexError, ValueError):
                continue
            if lat or lon:
                pts.append((mp, lat, lon))
        if pts:
            return sorted(pts)
    return []


def parse_coordinates(source: str,
                      sheet: str | None = None) -> dict[str, tuple[float, float]]:
    """crash_id -> (lat, lon) from the DetailedFiche.

    The DetailedFiche arrives WITH the Original Fiche and Initial Study
    (observed in the 260412109EA fiche workbook): the fiche columns plus
    per-crash Latitude / Longitude (and a Source column), keyed by Crash
    ID; the review sheet joins it by a live VLOOKUP into Lat / Long
    columns.  Because these coordinates help decide WHICH crash reports
    get reviewed, the pre-screen must use the DetailedFiche only - never
    coordinates read off a DMV-349, which would make the screen circular
    (the report coords should agree, but they are the thing being
    checked).  Accepts the fiche workbook (.xlsx; ``sheet`` defaults to
    the first sheet whose header carries Crash ID and Latitude, preferring
    one named DetailedFiche) or a delimited text file (pipe, comma, or
    tab).  Rows with blank or zero coordinates are skipped.
    """
    for header, rows in _fiche_tables(source, sheet):
        found = _coord_rows(header, rows)
        if found:
            return found
    return {}


def _fiche_tables(source: str, sheet: str | None = None) -> list:
    """Candidate ``(header, rows)`` tables in a DetailedFiche.

    Accepts the fiche workbook (.xlsx/.xlsm; ``sheet`` defaults to the first
    sheet whose header carries Latitude, preferring one named DetailedFiche)
    or delimited text (comma, pipe or tab).  More than one candidate may come
    back; the caller keeps the first that yields anything.

    Text goes through the csv module rather than ``str.split``.  The real
    export quotes every field, and splitting on the delimiter leaves the quote
    characters attached, after which no crash ID is a digit string and no
    coordinate parses as a float.  That silently produced an empty result.
    """
    out = []
    if source.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
        try:
            names = wb.sheetnames
            if sheet is None:
                pref = [n for n in names
                        if n.strip().lower() == "detailedfiche"]
                names = pref + [n for n in names if n not in pref]
            else:
                names = [sheet]
            for name in names:
                it = wb[name].iter_rows(values_only=True)
                for header in it:
                    if header and any("LATITUDE" in str(v or "").upper()
                                      for v in header):
                        out.append((list(header), [list(r) for r in it]))
                        break
        finally:
            wb.close()
        return out

    text = source
    if "\n" not in source and len(source) < 400:
        with open(source, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        up = line.upper()
        if "LATITUDE" not in up or "CRASH" not in up:
            continue
        delim = max((",", "|", "\t"), key=line.count)
        if line.count(delim) == 0:
            continue
        table = list(csv.reader(lines[i:], delimiter=delim))
        if len(table) > 1:
            out.append((table[0], table[1:]))
    return out


def read_detailed_fiche(source: str, sheet: str | None = None) -> list[tuple]:
    """``(coded_mp, latitude, longitude, source)`` per crash on a DetailedFiche.

    The shape :func:`safety_eval.location.coordinate_consistency` takes, so
    checking a real fiche's coordinate quality is::

        coordinate_consistency(read_detailed_fiche("DetailedFicheMcDowell.csv"))

    ``source`` here is the fiche's own Source column (``DMV349``,
    ``DMV349CLEANED``, ``ITRE_CMV``, ``HSRC_PED`` and so on), which says where
    the coordinate came from and matters: report-derived and research-feed
    coordinates are not equally good (docs/11).  Rows without a coordinate are
    dropped; rows without a milepost are kept as ``None`` so the caller can see
    how many there are.
    """
    for header, rows in _fiche_tables(source, sheet):
        cols: dict[str, int] = {}
        for i, cell in enumerate(header):
            p = str(cell or "").strip().upper()
            if p == "MP" or "MILEPOST" == p:
                cols.setdefault("mp", i)
            elif "LATITUDE" in p or p == "LAT":
                cols.setdefault("lat", i)
            elif "LONGITUDE" in p or p in ("LONG", "LON"):
                cols.setdefault("lon", i)
            elif p == "SOURCE":
                cols.setdefault("src", i)
        if "lat" not in cols or "lon" not in cols:
            continue

        out: list[tuple] = []
        for row in rows:
            try:
                lat = float(str(row[cols["lat"]]).strip())
                lon = float(str(row[cols["lon"]]).strip())
            except (TypeError, IndexError, ValueError):
                continue
            if not (lat or lon):
                continue
            mp = None
            if "mp" in cols:
                try:
                    mp = float(str(row[cols["mp"]]).strip())
                except (TypeError, IndexError, ValueError):
                    mp = None
            src = ""
            if "src" in cols:
                try:
                    src = str(row[cols["src"]] or "").strip()
                except IndexError:
                    src = ""
            out.append((mp, lat, lon, src))
        if out:
            return out
    return []


# --------------------------------------------------------------------------- #
# the queue
# --------------------------------------------------------------------------- #
@dataclass
class QueueItem:
    row: ReviewRow
    pending: bool                       # no determination yet
    has_report: bool | None = None      # None: no binder index given
    skip_reason: str | None = None      # e.g. animal crash
    dist_ft: float | None = None        # GPS pre-screen distance

    @property
    def crash_id(self) -> str:
        return self.row.crash_id


def build_queue(
    sheet: ReviewSheet,
    binder_index=None,
    coords: dict[str, tuple[float, float]] | None = None,
    study_point: tuple[float, float] | None = None,
    mp_range: tuple[float, float] | None = None,
) -> list[QueueItem]:
    """Order the review work (docs/07: GPS pre-screen first, then the queue).

    Rows without a determination come first, closest to the study location
    on top (GPS distance to ``study_point`` when coordinates are known,
    distance outside the ``mp_range`` otherwise), so the crashes most likely
    to belong in the study are reviewed early.  Animal crashes sink to the
    bottom of their group and carry a skip reason (docs/03: ignored in the
    review, no report needed).  Rows that already have a status follow, for
    confirmation passes.
    """
    items: list[QueueItem] = []
    for row in sheet.rows:
        dist = None
        if coords and study_point and row.crash_id in coords:
            lat, lon = coords[row.crash_id]
            dist = haversine_ft(lat, lon, *study_point)
        item = QueueItem(
            row=row,
            pending=row.status is None,
            has_report=(bool(binder_index.pages_for(row.crash_id))
                        if binder_index is not None else None),
            dist_ft=dist,
        )
        if row.is_animal:
            item.skip_reason = "animal crash; ignored in the review (docs/03)"
        items.append(item)

    def _mp_penalty(row: ReviewRow) -> float:
        if row.mp is None:
            return 0.0                     # not mileposted: review first
        if mp_range:
            lo, hi = min(mp_range), max(mp_range)
            if row.mp < lo:
                return lo - row.mp
            if row.mp > hi:
                return row.mp - hi
            return 0.0
        return 0.0

    def _key(item: QueueItem):
        return (
            not item.pending,                        # pending rows first
            item.skip_reason is not None,            # animals last in group
            item.dist_ft if item.dist_ft is not None
            else _mp_penalty(item.row),              # closest first
            item.row.row,                            # stable: sheet order
        )

    items.sort(key=_key)
    return items


# --------------------------------------------------------------------------- #
# audit trail
# --------------------------------------------------------------------------- #
def record_determination(audit_path: str, det: Determination,
                         previous: ReviewRow | None = None,
                         source: str = "review-queue") -> None:
    """Append one accepted determination to the JSONL audit trail."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "crash_id": det.crash_id,
        "status": det.status,
        "new_mp": det.new_mp,
        "comment": det.comment,
        "previous_status": previous.status if previous else None,
        "previous_new_mp": previous.new_mp if previous else None,
        "source": source,
    }
    os.makedirs(os.path.dirname(os.path.abspath(audit_path)), exist_ok=True)
    with open(audit_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def read_audit(audit_path: str) -> list[dict]:
    if not os.path.exists(audit_path):
        return []
    with open(audit_path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# --------------------------------------------------------------------------- #
# write-back (docs/06 template-preserving)
# --------------------------------------------------------------------------- #
def apply_determinations(
    workbook_in: str,
    workbook_out: str,
    determinations: list[Determination],
    sheet: str = DEFAULT_SHEET,
    analysis_type: str = "section",
) -> int:
    """Patch accepted determinations into the workbook's Filtered Fiche.

    Only the status, New MP, and comment cells of the determined rows are
    touched; every other cell, sheet, drawing and style is byte-preserved
    (docs/06). Determinations are validated again here so an invalid one can
    never reach a deliverable. Returns the number of rows patched.
    """
    review = load_review_sheet(workbook_in, sheet)
    by_id = review.by_id()
    status_col = review.columns.get("status")
    newmp_col = review.columns.get("new_mp")
    comment_col = review.columns.get("comment")
    if not status_col:
        raise KeyError(f"No status (IS?) column detected in {sheet!r}")

    edits: list[CellEdit] = []
    n = 0
    for det in determinations:
        problems = validate_determination(det, analysis_type)
        if problems:
            raise ValueError(
                f"Crash {det.crash_id}: " + " ".join(problems))
        row = by_id.get(det.crash_id)
        if row is None:
            raise KeyError(f"Crash {det.crash_id} is not on the {sheet!r} "
                           "sheet")
        edits.append(CellEdit(f"{status_col}{row.row}", det.status))
        if newmp_col:
            edits.append(CellEdit(f"{newmp_col}{row.row}", det.new_mp))
        if comment_col and det.comment is not None:
            edits.append(CellEdit(f"{comment_col}{row.row}", det.comment))
        n += 1
    if edits:
        xlsx_patch(workbook_in, workbook_out, {sheet: edits})
    return n


def queue_progress(items: list[QueueItem],
                   done_ids: set[str] | None = None) -> dict[str, int]:
    """Counts for the UI: pending / determined / skippable / with report."""
    done_ids = done_ids or set()
    pending = [i for i in items if i.pending and i.crash_id not in done_ids]
    return {
        "total": len(items),
        "pending": len(pending),
        "determined": len(items) - len(pending),
        "animal_skips": sum(1 for i in pending if i.skip_reason),
        "with_report": sum(1 for i in pending if i.has_report),
    }
