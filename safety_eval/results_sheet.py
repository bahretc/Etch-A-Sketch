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

    # -- left-aligned bullet blocks (countermeasures 8pt, target list 10pt)
    style_overrides: dict[str, str] = {}
    for pattern, attr, size in ((r"^Countermeasure\(s\):$",
                                 "countermeasures", 8),
                                (r"^Target Crashes:$", "target_crashes", 10)):
        lbl = _find_label(cells, pattern)
        if lbl is None:
            continue
        ref = f"{_col_letter(_col_index(lbl[0]) + 1)}{lbl[1]}"
        base = style_of(ref)
        if base is None:
            continue
        styles_xml, idx = clone_style(
            styles_xml, int(base), font_size=size,
            halign="left", valign="center", wrap=True)
        style_overrides[attr] = str(idx)

    # -- size the engineer-adjusted blocks to their text, the way the
    #    completed workbooks do (rows grow, fit-to-one-page settles scale)
    swaps: dict[str, str] = {}
    if data is not None and data.countermeasures:
        lbl = _find_label(cells, r"^Countermeasure\(s\):$")
        ref = f"{_col_letter(_col_index(lbl[0]) + 1)}{lbl[1]}"
        m = _re.search(rf'<mergeCell ref="{ref}:[A-Z]+(\d+)"/>', xml)
        if m:
            first, last = lbl[1], int(m.group(1))
            need = _wrapped_lines(data.countermeasures, 60) * 11 + 4
            per = max(15.0, float(-(-need // (last - first + 1))))
            for r in range(first, last + 1):
                row_heights[r] = per
    if data is not None and data.items_for_discussion:
        lbl = _find_label(cells, r"^Items for Discussion$")
        icol, irow = lbl[0], lbl[1] + 1
        m = _re.search(rf'<mergeCell ref="({icol}{irow}:([A-Z]+)(\d+))"/>',
                       xml)
        footer = _find_label(cells, r"^Data Prepared For:$")
        if m and footer:
            old_ref, ecol, last = m.group(1), m.group(2), int(m.group(3))
            avail_last = footer[1] - 1
            if avail_last > last:
                swaps[old_ref] = f"{icol}{irow}:{ecol}{avail_last}"
                last = avail_last
            text = "\n".join("• " + t if not t.startswith(("•", "-")) else t
                             for t in data.items_for_discussion)
            need = _wrapped_lines(text, 158) * 13.2 + 6
            per = max(15.0, float(-(-need // (last - irow + 1))))
            for r in range(irow, last + 1):
                row_heights[r] = per

    # -- saved print scale: the completed workbooks' 64, or smaller when
    #    the grown blocks need it (printable height 10.0in at the saved
    #    0.5in top/bottom margins)
    heights = {}
    for rm in _re.finditer(r'<row r="(\d+)"([^>]*)>', xml):
        hm = _re.search(r'ht="([\d.]+)"', rm.group(2))
        heights[int(rm.group(1))] = float(hm.group(1)) if hm else 15.0
    heights.update(row_heights)
    total = sum(heights.get(r, 15.0) for r in range(2, 73))
    scale = min(REPORT_PAGE_SCALE, int(720.0 / total * 100))

    ops = dict(row_heights={sheet: row_heights},
               add_merges={sheet: merges},
               swap_merges={sheet: swaps},
               page_scale={sheet: scale},
               replace_members={"xl/styles.xml": styles_xml.encode("utf-8")})
    return edits, ops, style_overrides


def populate_results_sheet(template: str, output: str, data: ResultsData,
                           sheet: str = RESULTS_1T,
                           apply_format: bool = True) -> None:
    edits = build_results_edits(template, data, sheet)
    ops = {}
    if apply_format:
        fmt_edits, ops, overrides = format_results_sheet(template, sheet, data)
        for e in edits:
            for attr, idx in overrides.items():
                if getattr(data, attr) is not None and isinstance(e.value, str) \
                        and e.value == getattr(data, attr):
                    e.style = idx
        edits += fmt_edits
    xlsx_patch(template, output, edits={sheet: edits}, **ops)
