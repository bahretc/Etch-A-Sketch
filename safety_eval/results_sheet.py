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
    prepared_date: str | None = None
    additional_info: list = field(default_factory=list)   # AdditionalInfoRow
    items_for_discussion: list = field(default_factory=list)  # bullet strings
    #: Project Development column of the per-year comparison block:
    #: {years, start, end, total, fatal, a, b, c, pdo}, rates per year,
    #: straight from the assumptions email's Project Dev Crash Summary.
    project_development: dict | None = None


_BANNED = {"—": "em dash", "–": "en dash"}


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
    if data.project_development:
        hdr = _find_label(cells, r"^Project Development$")
        if hdr:
            hcol, hrow = hdr
            lcol = _col_letter(_col_index(hcol) - 1)
            labels = {"Years": "years", "Start Date": "start",
                      "End Date": "end", "Total": "total",
                      "Fatal Injury": "fatal", "Class A Injury": "a",
                      "Class B Injury": "b", "Class C Injury": "c",
                      "Property Damage Only": "pdo"}
            pd = data.project_development
            for (col, row), val in cells.items():
                if col != lcol or row <= hrow:
                    continue
                key = labels.get(str(val).strip())
                if key is not None and key in pd:
                    value = pd[key]
                    if isinstance(value, str):
                        check_style(value, f"project_development.{key}")
                    edits.append(CellEdit(f"{hcol}{row}", value))

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


def load_results_yaml(path: str) -> ResultsData:
    """Load results-sheet inputs from YAML. ``additional_info`` entries are
    ``{label, before, after}``; ``items_for_discussion`` is a list of strings."""
    import yaml

    with open(path) as fh:
        d = yaml.safe_load(fh) or {}
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
        prepared_date=d.get("prepared_date"),
        additional_info=rows,
        items_for_discussion=list(d.get("items_for_discussion", []) or []),
        project_development=d.get("project_development"),
    )


def populate_results_sheet(template: str, output: str, data: ResultsData,
                           sheet: str = RESULTS_1T) -> None:
    xlsx_patch(template, output,
               edits={sheet: build_results_edits(template, data, sheet)})
