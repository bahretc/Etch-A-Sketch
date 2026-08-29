"""Populate the '1 page results' sheet manual cells (docs/02, docs/05).

Everything numeric on the results sheet is formula-driven off the Before/After
and Evaluation Set-up sheets; the manual cells are the project-identity block,
the narrative text blocks, the Additional Information rows, and Items for
Discussion. Cells are located by their labels (rule 8: layouts drift between
the intersection and section variants).

docs/05 style rules are enforced on all provided text: no em or en dashes
anywhere. Text failing the check is rejected, not silently rewritten; the
wording is the engineer's.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .setup_sheet import _col_index, _col_letter, _find_label
from .xlsx_patch import KEEP_VALUE as _KEEP_VALUE
from .xlsx_patch import CellEdit, sheet_files, xlsx_patch

RESULTS_1T = "1 page results - 1 Target"
RESULTS_2T = "1 page results - 2 Targets"

# label regex -> ResultsData attribute (value cell = next column, same row)
_IDENTITY_LABELS = {
    r"^Order ID:$": "order_id",
    r"^Project ID:$": "project_id",
    r"^Signal ID:$": "signal_id",
    r"^Location:$": "location",
    r"^Length:$": "length",
    r"^GPS Coordinates:$": "gps",
    r"^County:$": "county",
    r"^City:$": "city",
    r"^Division:$": "division",
    r"^Countermeasure\(s\):$": "countermeasures",
    r"^Estimated Project Cost:$": "cost",
    r"^Completion Date:$": "completion_date",
    r"^Analysis Criteria:$": "analysis_criteria",
    r"^Target Crashes:$": "target_crashes",
    # Data Prepared By block, bottom right of the printed 1-pager
    r"^Principal Investigator:$": "principal_investigator",
    r"^Work Group/Consultant:$": "work_group",
    r"^Date:$": "prepared_date",
}


@dataclass
class AdditionalInfoRow:
    label: str
    before: object = None
    after: object = None


@dataclass
class ResultsData:
    order_id: str | None = None
    project_id: str | None = None
    signal_id: str | None = None
    location: str | None = None
    length: str | None = None
    gps: str | None = None
    county: str | None = None
    city: str | None = None
    division: str | None = None
    countermeasures: str | None = None
    cost: str | None = None
    completion_date: str | None = None
    analysis_criteria: str | None = None
    target_crashes: str | None = None
    principal_investigator: str | None = None
    work_group: str | None = None
    prepared_date: object = None       # str or datetime.date (-> serial)
    additional_info: list = field(default_factory=list)   # AdditionalInfoRow
    items_for_discussion: list = field(default_factory=list)  # bullet strings
    #: Project Development column of the per-year comparison block:
    #: {years, start, end, total, fatal, a, b, c, pdo}, rates per year,
    #: straight from the assumptions email's Project Dev Crash Summary.
    project_development: dict | None = None


_BANNED = {"—": "em dash", "–": "en dash"}

#: Where the completed workbooks park the Project Development crash counts
#: that feed the per-year formulas: O57:O62, outside the printed area.
_PD_HELPER_COL = "O"
_PD_HELPER_ROW = 57

#: The completed workbooks' saved print scale for the results 1-pager.
REPORT_PAGE_SCALE = 64

#: Font sizes the engineer uses, largest first. Items for Discussion is
#: never smaller than 9.0 in the archive (11.0, 10.0 and 9.5 observed);
#: the narrower blocks go down to 8.0, and this template's smaller cells
#: sometimes need one step below that.
BLOCK_SIZES = (11.0, 10.5, 10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0)
ITEMS_SIZES = (11.0, 10.5, 10.0, 9.5, 9.0)
ITEMS_PREFERRED_MIN = 9.5

#: The sheet's row pitch; rows are added, never stretched.
ROW_PITCH_PT = 15.0
#: Letter portrait minus the deliverable's 0.5in top and bottom margins.
PRINTABLE_HEIGHT_PT = 720.0
#: Most rows the Items cell may gain (the engineer added 1 and 2).
MAX_ADDED_ROWS = 6
#: Rows are worth adding down to this print scale; below it the page is
#: harder to read than a smaller font would have been.
MIN_PAGE_SCALE = 62
#: The corpus scan settled the margin question: his grown AWSC pages
#: (SS-6001P, SS-6010AG) keep the template's 0.25/0.5in margins and
#: print at 63; the whole page stays centered with visible margins.
#: SS-6010O/SS-6202A ran 0.1in, but that is the minority look.
PAGE_MARGIN_IN = 0.25


def _box_bottom_row(xml: str, styles_xml: str) -> int | None:
    """Row carrying the report box's heavy bottom border.

    The printed page must end on it, or the box prints open at the
    bottom. The blank template's saved print area stops one row short of
    it, which is why every completed workbook has a hand-corrected print
    area (B2:L72 rather than the template's B2:L71).
    """
    import re as _re
    borders = _re.search(r"<borders.*?</borders>", styles_xml, _re.S)
    xfs = _re.search(r"<cellXfs.*?</cellXfs>", styles_xml, _re.S)
    if not (borders and xfs):
        return None
    blist = _re.findall(r"<border\b[^>]*?/>|<border\b[^>]*?>.*?</border>",
                        borders.group(0), _re.S)
    heavy = {i for i, b in enumerate(blist)
             if _re.search(r'<bottom style="(medium|thick|double)"', b)}
    xflist = _re.findall(r"<xf\b[^>]*?/>|<xf\b[^>]*?>.*?</xf>",
                         xfs.group(0), _re.S)
    heavy_styles = set()
    for i, xf in enumerate(xflist):
        bid = _re.search(r'borderId="(\d+)"', xf)
        if bid and int(bid.group(1)) in heavy:
            heavy_styles.add(i)
    last = None
    for m in _re.finditer(r'<c r="([A-Z]{1,3})(\d+)"(?: s="(\d+)")?', xml):
        if int(m.group(3) or 0) in heavy_styles and m.group(1) in set("CDEFGHIJK"):
            row = int(m.group(2))
            last = row if last is None else max(last, row)
    return last


def _print_area_last_row(template: str, sheet: str) -> int | None:
    """Last row of the sheet's saved Print_Area, if it has one."""
    import re as _re
    import zipfile as _zipfile
    with _zipfile.ZipFile(template) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
    m = _re.search(r'<definedName name="_xlnm.Print_Area"[^>]*>\''
                   + _re.escape(sheet) + r"'!\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?(\d+)",
                   wb)
    return int(m.group(1)) if m else None


def check_style(text: str, where: str) -> None:
    """docs/05: plain and understated, no em dashes anywhere."""
    for ch, name in _BANNED.items():
        if ch in text:
            raise ValueError(
                f"{where}: {name} found; docs/05 forbids em/en dashes in "
                "report text. Use commas, periods, colons, or parentheses.")


def build_results_edits(template: str, data: ResultsData,
                        sheet: str = RESULTS_1T) -> list[CellEdit]:
    from .setup_sheet import _scan_sheet

    names = sheet_files(template)
    if sheet not in names:
        raise KeyError(f"Template has no {sheet!r} sheet: {sorted(names)}")
    cells = _scan_sheet(template, sheet)
    edits: list[CellEdit] = []

    for pattern, attr in _IDENTITY_LABELS.items():
        value = getattr(data, attr)
        if value is None:
            continue
        if isinstance(value, str):
            check_style(value, attr)
        lbl = _find_label(cells, pattern)
        if lbl is None:
            continue
        col, row = lbl
        edits.append(CellEdit(f"{_col_letter(_col_index(col) + 1)}{row}", value))

    # Additional Information rows: between the header and 'Map/Satellite Views'
    if data.additional_info:
        hdr = _find_label(cells, r"^Additional Information$")
        stop = _find_label(cells, r"Map/?Satellite Views")
        if hdr:
            hcol, hrow = hdr
            first_row = hrow + 2                     # header + subheader rows
            last_row = (stop[1] - 1) if stop else first_row + 4
            capacity = last_row - first_row + 1
            if len(data.additional_info) > capacity:
                raise ValueError(
                    f"{len(data.additional_info)} Additional Information rows "
                    f"but the sheet has {capacity}.")
            bcol = _col_letter(_col_index(hcol) + 1)
            acol = _col_letter(_col_index(hcol) + 2)
            for i in range(capacity):
                row = first_row + i
                if i < len(data.additional_info):
                    info = data.additional_info[i]
                    check_style(info.label, f"additional_info[{i}].label")
                    edits.append(CellEdit(f"{hcol}{row}", info.label))
                    edits.append(CellEdit(f"{bcol}{row}", info.before))
                    edits.append(CellEdit(f"{acol}{row}", info.after))
                else:
                    # unused rows keep 'n/a' in the leftmost column (docs/02)
                    edits.append(CellEdit(f"{hcol}{row}", "n/a"))
                    edits.append(CellEdit(f"{bcol}{row}", None))
                    edits.append(CellEdit(f"{acol}{row}", None))

    # Project Development column of the Crashes Per Year block: the header
    # cell anchors the column, the row labels one column left anchor each
    # value row (the same label texts appear elsewhere on the sheet, so
    # the search is scoped to below the header in the adjacent column).
    # The completed workbooks enter the period dates as real dates, park
    # the period's crash COUNTS in the off-print helper column (O57:O62),
    # and drive Years and every per-year rate with formulas, so the
    # reviewer can trace each number (rule 4). ``counts`` selects that
    # convention; the legacy flat mapping still writes plain values.
    if data.project_development:
        hdr = _find_label(cells, r"^Project Development$")
        if hdr:
            hcol, hrow = hdr
            lcol = _col_letter(_col_index(hcol) - 1)
            pd = data.project_development
            rows = {}
            for (col, row), val in cells.items():
                if col == lcol and row > hrow:
                    rows[str(val).strip()] = row
            if "counts" in pd:
                r_start, r_end = rows["Start Date"], rows["End Date"]
                dcol = hcol
                edits.append(CellEdit(f"{dcol}{r_start}", pd["start"]))
                edits.append(CellEdit(f"{dcol}{r_end}", pd["end"]))
                years = (f"ROUND(YEARFRAC({dcol}{r_start},{dcol}{r_end},1),2)")
                edits.append(CellEdit(
                    f"{dcol}{rows['Years']}",
                    formula=(f'IF(MOD({years},1)=0, TEXT({years},"0.00")'
                             f' & " years", {years} & " years")')))
                order = ["total", "fatal", "a", "b", "c", "pdo"]
                labels = {"Total": "total", "Fatal Injury": "fatal",
                          "Class A Injury": "a", "Class B Injury": "b",
                          "Class C Injury": "c",
                          "Property Damage Only": "pdo"}
                for text, key in labels.items():
                    row = rows[text]
                    helper = (f"{_PD_HELPER_COL}"
                              f"{_PD_HELPER_ROW + order.index(key)}")
                    edits.append(CellEdit(helper, pd["counts"][key]))
                    edits.append(CellEdit(
                        f"{dcol}{row}",
                        formula=(f"{helper}/ROUND(YEARFRAC("
                                 f"${dcol}${r_start},${dcol}${r_end}),2)")))
            else:
                labels = {"Years": "years", "Start Date": "start",
                          "End Date": "end", "Total": "total",
                          "Fatal Injury": "fatal", "Class A Injury": "a",
                          "Class B Injury": "b", "Class C Injury": "c",
                          "Property Damage Only": "pdo"}
                for text, key in labels.items():
                    if text in rows and key in pd:
                        value = pd[key]
                        if isinstance(value, str):
                            check_style(value, f"project_development.{key}")
                        edits.append(CellEdit(f"{hcol}{rows[text]}", value))

    # Items for Discussion: one merged cell below the header, bullets joined
    # with line breaks (ALT+ENTER = plain \n in the XML).
    if data.items_for_discussion:
        lbl = _find_label(cells, r"^Items for Discussion$")
        if lbl:
            col, row = lbl
            bullets = []
            for i, item in enumerate(data.items_for_discussion):
                check_style(item, f"items_for_discussion[{i}]")
                item = item.strip()
                if not item.startswith(("•", "-")):
                    item = "• " + item
                bullets.append(item)
            edits.append(CellEdit(f"{col}{row + 1}", "\n".join(bullets)))

    return edits


def _as_date(value):
    """m/d/yyyy strings become dates (written as serials, format kept)."""
    import re as _re
    from datetime import date as _date
    if isinstance(value, str):
        m = _re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value.strip())
        if m:
            return _date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    return value


def load_results_yaml(path: str) -> ResultsData:
    """Load results-sheet inputs from YAML. ``additional_info`` entries are
    ``{label, before, after}``; ``items_for_discussion`` is a list of strings."""
    import yaml

    with open(path) as fh:
        d = yaml.safe_load(fh) or {}
    pd = d.get("project_development")
    if pd:
        for key in ("start", "end"):
            if key in pd:
                pd[key] = _as_date(pd[key])
    rows = [AdditionalInfoRow(label=str(r["label"]),
                              before=r.get("before"), after=r.get("after"))
            for r in d.get("additional_info", []) or []]
    return ResultsData(
        order_id=d.get("order_id"), project_id=d.get("project_id"),
        signal_id=d.get("signal_id"), location=d.get("location"),
        length=d.get("length"), gps=d.get("gps"), county=d.get("county"),
        city=d.get("city"), division=(str(d["division"])
                                      if d.get("division") is not None else None),
        countermeasures=d.get("countermeasures"), cost=d.get("cost"),
        completion_date=d.get("completion_date"),
        analysis_criteria=d.get("analysis_criteria"),
        target_crashes=d.get("target_crashes"),
        principal_investigator=d.get("principal_investigator"),
        work_group=d.get("work_group"),
        prepared_date=_as_date(d.get("prepared_date")),
        additional_info=rows,
        items_for_discussion=list(d.get("items_for_discussion", []) or []),
        project_development=d.get("project_development"),
    )


def _wrapped_lines(text: str, chars_per_line: int) -> int:
    import math
    return sum(max(1, math.ceil(len(seg) / chars_per_line))
               for seg in text.split("\n"))


def items_text(data: ResultsData) -> str:
    """The Items block exactly as it lands in the cell."""
    return "\n".join("• " + t if not t.startswith(("•", "-")) else t
                      for t in data.items_for_discussion)


def plan_items_growth(template: str, sheet: str, data: ResultsData):
    """Rows to add under the Items cell, or None if the text already fits.

    The engineer grows this block by inserting whole rows (SS-6202A by
    one, SS-6010O by two), never by stretching a row and never by taking
    the blank row above 'Data Prepared For:'. Rows are added only while
    the print scale stays at his 64.
    """
    import re as _re
    import zipfile as _zipfile

    from .setup_sheet import _scan_sheet
    from .text_fit import box_size_pt, fit_font_size
    from .xlsx_patch import sheet_files

    if not (data and data.items_for_discussion):
        return None
    cells = _scan_sheet(template, sheet)
    lbl = _find_label(cells, r"^Items for Discussion$")
    footer = _find_label(cells, r"^Data Prepared For:$")
    if lbl is None or footer is None:
        return None
    with _zipfile.ZipFile(template) as z:
        xml = z.read(sheet_files(template)[sheet]).decode("utf-8")
    icol, irow = lbl[0], lbl[1] + 1
    m = _re.search(rf'<mergeCell ref="({icol}{irow}:([A-Z]+)(\d+))"/>', xml)
    if m is None:
        return None
    mref, ecol, last = m.group(1), m.group(2), int(m.group(3))
    width, height = box_size_pt(xml, mref)
    text = items_text(data)

    heights = {}
    for rm in _re.finditer(r'<row r="(\d+)"([^>]*)>', xml):
        hm = _re.search(r'ht="([\d.]+)"', rm.group(2))
        heights[int(rm.group(1))] = float(hm.group(1)) if hm else 15.0
    with _zipfile.ZipFile(template) as z:
        styles = z.read("xl/styles.xml").decode("utf-8")
    last_print = (_box_bottom_row(xml, styles)
                  or _print_area_last_row(template, sheet)
                  or (footer[1] + 4))
    page = sum(heights.get(r, 15.0) for r in range(2, last_print + 1))

    added = 0
    while added < MAX_ADDED_ROWS:
        size, _, _ = fit_font_size(text, width, height + ROW_PITCH_PT * added,
                                   sizes=ITEMS_SIZES)
        if size is not None and size >= ITEMS_PREFERRED_MIN:
            break
        if int(PRINTABLE_HEIGHT_PT
               / (page + ROW_PITCH_PT * (added + 1)) * 100) < MIN_PAGE_SCALE:
            break
        added += 1
    if added == 0:
        return None

    def style_of(ref):
        mm = _re.search(rf'<c r="{ref}"(?: s="(\d+)")?', xml)
        return mm.group(1) if mm and mm.group(1) else None

    edits: list[CellEdit] = []
    # the box outline lives on the merge's perimeter cells: the old bottom
    # row becomes interior and the new bottom row takes its border styles,
    # or the grown box prints open at the bottom
    for i in range(_col_index(icol) - 1, _col_index(ecol) + 2):
        col = _col_letter(i)
        interior, bottom = style_of(f"{col}{last - 1}"), style_of(f"{col}{last}")
        for r in range(last, last + added):
            edits.append(CellEdit(f"{col}{r}", _KEEP_VALUE, style=interior))
        edits.append(CellEdit(f"{col}{last + added}", _KEEP_VALUE,
                              style=bottom))
    ops = dict(grow_rows={sheet: (last + 1, added)},
               swap_merges={sheet: {mref: f"{icol}{irow}:{ecol}{last + added}"}},
               row_heights={sheet: {r: ROW_PITCH_PT
                                    for r in range(last + 1, last + added + 1)}},
               print_area={sheet: f"$B$2:$L${last_print + added}"})
    return edits, ops, added


def format_results_sheet(template: str, sheet: str = RESULTS_1T,
                         data: ResultsData | None = None):
    """Reproduce the engineer's manual formatting of the printed 1-pager.

    Everything here mirrors the completed workbooks (SS-6002AD et al.)
    against the shipped template:

    * the Map/Satellite Views heading moves down one row so an empty
      spacer row separates it from the Additional Information table, with
      the two rows' heights swapped (15pt spacer, 18pt heading) so the
      overall page height does not change;
    * the last Additional Information row gets the same bordered styles
      and live percent formula as the rows above it (the template ships
      row 38 unformatted and without the K-column formula);
    * the bulleted Countermeasure(s) block is left-aligned at 8pt and the
      Target Crashes list left-aligned at 10pt, as in every completed
      workbook (the template centers both, which scrambles indented
      bullets);
    * the saved print scale becomes the completed workbooks' 64%.

    Returns ``(edits, ops)`` where ``ops`` are keyword arguments for
    :func:`xlsx_patch` (row heights, merges, page scale, replaced
    styles.xml).
    """
    import re as _re
    import zipfile as _zipfile

    from .setup_sheet import _scan_sheet
    from .xlsx_patch import clone_style, sheet_files

    cells = _scan_sheet(template, sheet)
    names = sheet_files(template)
    with _zipfile.ZipFile(template) as z:
        xml = z.read(names[sheet]).decode("utf-8")
        styles_xml = z.read("xl/styles.xml").decode("utf-8")

    def style_of(ref):
        m = _re.search(rf'<c r="{ref}"(?: s="(\d+)")?', xml)
        return m.group(1) if m and m.group(1) else None

    edits: list[CellEdit] = []
    row_heights: dict[int, float] = {}
    merges: list[str] = []

    # -- Map/Satellite Views heading: down one row, spacer left behind
    lbl = _find_label(cells, r"Map/?Satellite Views")
    if lbl is None:
        raise KeyError("Map/Satellite Views heading not found")
    mcol, mrow = lbl
    merge = _re.search(rf'<mergeCell ref="({mcol}{mrow}:([A-Z]+){mrow})"/>',
                       xml)
    end_col = merge.group(2) if merge else mcol
    edits.append(CellEdit(f"{mcol}{mrow}", None))
    edits.append(CellEdit(f"{mcol}{mrow + 1}", "Map/Satellite Views",
                          style=style_of(f"{mcol}{mrow}")))
    merges.append(f"{mcol}{mrow + 1}:{end_col}{mrow + 1}")
    row_heights[mrow] = 15.0
    row_heights[mrow + 1] = 18.0

    # -- last Additional Information row: formats and formula of the rows
    #    above it
    hdr = _find_label(cells, r"^Additional Information$")
    if hdr is not None:
        hcol, hrow = hdr
        first, last = hrow + 2, mrow - 1
        src = last - 1
        ic = _col_index(hcol)
        cols = [hcol, _col_letter(ic + 1), _col_letter(ic + 2),
                _col_letter(ic + 3)]
        for col in cols[:3]:
            st = style_of(f"{col}{src}")
            if st and st != style_of(f"{col}{last}"):
                edits.append(CellEdit(f"{col}{last}", _KEEP_VALUE, style=st))
        kcol = cols[3]
        has_formula = _re.search(
            rf'<c r="{kcol}{last}"[^>]*>\s*<f', xml) is not None
        if not has_formula:
            bcol, acol = cols[1], cols[2]
            edits.append(CellEdit(
                f"{kcol}{last}",
                formula=(f'IFERROR(({acol}{last}-{bcol}{last})'
                         f'/{bcol}{last}, "n/a")'),
                style=style_of(f"{kcol}{src}")))
        # long row labels shrink to fit instead of clipping at the border
        base = style_of(f"{hcol}{first}")
        if base is not None:
            styles_xml, shrunk = clone_style(styles_xml, int(base),
                                             shrink=True)
            for r in range(first, last + 1):
                edits.append(CellEdit(f"{hcol}{r}", _KEEP_VALUE,
                                      style=str(shrunk)))

    # -- text blocks: the engineer never changes a row height on this
    #    sheet (every completed workbook keeps rows 58-66 at 15.0pt); when
    #    a block outgrows its merged cell he drops the font size, and only
    #    when that is not enough does he insert whole rows, always leaving
    #    a blank row above 'Data Prepared For:'. Same order here.
    from .text_fit import box_size_pt, fit_font_size

    style_overrides: dict[str, str] = {}
    notes: list[str] = []
    swaps: dict[str, str] = {}

    def merge_from(ref: str) -> str | None:
        m = _re.search(rf'<mergeCell ref="({ref}:[A-Z]+\d+)"/>', xml)
        return m.group(1) if m else None

    def fitted(attr: str, text: str, ref: str, floor: float):
        """(size, note) for a block that must fit its native merge."""
        mref = merge_from(ref)
        if mref is None:
            return None, None
        width, height = box_size_pt(xml, mref)
        size, lines, need = fit_font_size(text, width, height,
                                          sizes=BLOCK_SIZES)
        if size is None:
            return None, (f"{attr}: {lines} lines do not fit the "
                          f"{height:.0f}pt cell even at "
                          f"{BLOCK_SIZES[-1]:g}pt (needs {need:.0f}pt)")
        if size < floor:
            return size, (f"{attr}: sized {size:g}pt, below the usual "
                          f"{floor:g}pt, to fit {lines} lines in the "
                          f"{height:.0f}pt cell")
        return size, None

    for pattern, attr, floor in ((r"^Countermeasure\(s\):$",
                                  "countermeasures", 8.0),
                                 (r"^Target Crashes:$", "target_crashes", 9.0)):
        lbl = _find_label(cells, pattern)
        if lbl is None:
            continue
        ref = f"{_col_letter(_col_index(lbl[0]) + 1)}{lbl[1]}"
        base = style_of(ref)
        if base is None:
            continue
        size = floor
        text = getattr(data, attr, None) if data is not None else None
        if text:
            picked, note = fitted(attr, text, ref, floor)
            if picked is not None:
                size = picked
            if note:
                notes.append(note)
        styles_xml, idx = clone_style(
            styles_xml, int(base), font_size=size,
            halign="left", valign="center", wrap=True)
        style_overrides[attr] = str(idx)

    # -- Items for Discussion: size to whatever cell it has. The cell is
    #    grown beforehand by :func:`plan_items_growth` when the text
    #    cannot be held at the engineer's smallest size.
    if data is not None and data.items_for_discussion:
        lbl = _find_label(cells, r"^Items for Discussion$")
        icol, irow = lbl[0], lbl[1] + 1
        mref = merge_from(f"{icol}{irow}")
        if mref:
            width, height = box_size_pt(xml, mref)
            text = items_text(data)
            size, lines, need = fit_font_size(text, width, height,
                                              sizes=ITEMS_SIZES)
            if size is None:
                raise ValueError(
                    f"Items for Discussion needs {need:.0f}pt for {lines} "
                    f"lines but the cell holds {height:.0f}pt even at "
                    f"{ITEMS_SIZES[-1]:g}pt; shorten the text.")
            if size < ITEMS_PREFERRED_MIN:
                notes.append(
                    f"items_for_discussion: {size:g}pt for {lines} lines in "
                    f"the {height:.0f}pt cell, below the preferred "
                    f"{ITEMS_PREFERRED_MIN:g}pt")
            base_items = style_of(f"{icol}{irow}")
            if base_items is not None:
                styles_xml, idx = clone_style(
                    styles_xml, int(base_items), font_size=size,
                    halign="left", valign="top", wrap=True)
                edits.append(CellEdit(f"{icol}{irow}", _KEEP_VALUE,
                                      style=str(idx)))

    # -- saved print scale: the engineer's 64, or smaller only if grown
    #    rows push the sheet past the printable height
    heights = {}
    for rm in _re.finditer(r'<row r="(\d+)"([^>]*)>', xml):
        hm = _re.search(r'ht="([\d.]+)"', rm.group(2))
        heights[int(rm.group(1))] = float(hm.group(1)) if hm else 15.0
    last_print = (_box_bottom_row(xml, styles_xml)
                  or _print_area_last_row(template, sheet) or 71)
    total = sum(heights.get(r, 15.0) for r in range(2, last_print + 1))
    scale = min(REPORT_PAGE_SCALE, int(PRINTABLE_HEIGHT_PT / total * 100))

    ops = dict(row_heights={sheet: row_heights},
               add_merges={sheet: merges},
               swap_merges={sheet: swaps},
               page_scale={sheet: scale},
               print_area={sheet: f"$B$2:$L${last_print}"},
               replace_members={"xl/styles.xml": styles_xml.encode("utf-8")})
    return edits, ops, style_overrides, notes


def populate_results_sheet(template: str, output: str, data: ResultsData,
                           sheet: str = RESULTS_1T,
                           apply_format: bool = True) -> list[str]:
    """Write the results sheet. Returns notes about how text was fitted."""
    import os

    notes: list[str] = []
    grown = None
    if apply_format:
        plan = plan_items_growth(template, sheet, data)
        if plan:
            grow_edits, grow_ops, added = plan
            grown = output + ".grow.tmp"
            xlsx_patch(template, grown, edits={sheet: grow_edits},
                       full_calc_on_load=False, **grow_ops)
            template = grown
            notes.append(
                f"items_for_discussion: cell grown by {added} row(s); the "
                "footer, the blank spacer row and the print area moved down "
                "with it and no row height changed")
    try:
        edits = build_results_edits(template, data, sheet)
        ops = {}
        if apply_format:
            fmt_edits, ops, overrides, fmt_notes = format_results_sheet(
                template, sheet, data)
            notes += fmt_notes
            for e in edits:
                for attr, idx in overrides.items():
                    if (getattr(data, attr) is not None
                            and isinstance(e.value, str)
                            and e.value == getattr(data, attr)):
                        e.style = idx
            edits += fmt_edits
        xlsx_patch(template, output, edits={sheet: edits}, **ops)
    finally:
        if grown and os.path.exists(grown):
            os.unlink(grown)
    return notes
