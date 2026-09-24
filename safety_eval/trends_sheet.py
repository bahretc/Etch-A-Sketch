"""Trends sheet of the office Intersection Evaluation Workbook (Accessible
xlsm, VHB v2 layout), written with live formulas on Before and After.

The office workbook's One Pager reads its Additional Information counts from
a Trends sheet by label: ``INDEX(Trends!C:C, MATCH(pick, Trends!F:F, 0))``
for the crash-type lines, ``INDEX(Trends!I:I, MATCH(pick, Trends!L:L, 0))``
for the fault, target and condition lines. Copies of the workbook have been
found with that Trends sheet, the pick list and the drop-down lists living
in another file (an external link to a copy in someone's Downloads folder),
so the counts shown were another project's. This module writes the v2
layout into the workbook itself. Positions and labels are the ones the v2
workbook carries (read from its cached link data, 41000076148 VHB v2):

* summary, rows 4 to 9: total crashes and a check that the crash-type
  totals add up to it (C/D), and the target 1, lane departure, rear end,
  target 2 and target 3 totals (I/J);
* crash type by direction, labels in F, counts in C (Before) and D (After):
  one block of six rows per type from row 11 (Angle) to row 115 (Rear
  end), then Pedestrian, Bicycle, Animal and Other at rows 124 to 127;
* fault, approach, target and condition lines, labels in L, counts in I/J,
  rows 11 to 70;
* custom lines from row 73 (label in L, counts in I/J, definition in M),
  for Additional Information rows the standard lines do not cover;
* the drop-down lists the Before/After entry columns and the One Pager
  pick use (columns O to S), which the workbook's defined names point at.

Column meanings on Before/After (rows 4 to 1003): A crash ID, D road
condition, F light, G severity, H crash type, I vehicle 1, J vehicle 2 (a
movement code such as "NBT"), K at fault ("V1", "V2", "Unclear"), L/M/N
Target-1/2/3 ("Y").

Definitions, stated on the sheet as well:

* "vehicle 1" lines use vehicle 1's approach; "turning vehicle" lines the
  vehicle whose movement is the turn (L, R or U); "striking" and "rear"
  vehicles are the at-fault vehicle;
* frontal impact = Angle, LTSR, LTDR, RTSR, RTDR, HeadOn (Target Crash 1 of
  the Assumptions sheet); lane departure = RORR, RORL, RORS, Overturn;
* wet = road condition 2 or 3, night = light 4 to 6, injury = K, A, B, C.
"""
from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass

from .xlsx_patch import _cell_xml, _col_index, replace_sheet_rows, sheet_files

DIRS = ("NB", "SB", "EB", "WB")
FIRST, LAST = 4, 1003
FRONTAL = ("Angle", "LTSR", "LTDR", "RTSR", "RTDR", "HeadOn")
LANE_DEPARTURE = ("RORR", "RORL", "RORS", "Overturn")

CRASH_TYPES = ("Angle", "LTSR", "LTDR", "RTSR", "RTDR", "HeadOn", "U-Turn",
               "RE", "RORR", "RORL", "RORS", "SSSD", "SSDD", "Overturn",
               "Ped", "Bike", "Animal", "Other")
VEHICLE_CODES = tuple(f"{d}{m}" for d in DIRS for m in "TLRU") + ("Unk",)
AT_FAULT = ("V1", "V2", "Unclear")

# (type code, label stem, which vehicle, suffix for the turn movement)
_TYPE_BLOCKS = (
    ("Angle", "Angle crashes", "v1", None),
    ("LTSR", "LTSR crashes", "turn", "L"),
    ("LTDR", "LTDR crashes", "turn", "L"),
    ("RTSR", "RTSR crashes", "turn", "R"),
    ("RTDR", "RTDR crashes", "turn", "R"),
    ("HeadOn", "HeadOn crashes", "v1", None),
    ("U-Turn", "U-Turn crashes", "turn", "U"),
    ("RORR", "Ran off road right crashes", "plain", None),
    ("RORL", "Ran off road left crashes", "plain", None),
    ("RORS", "Ran off road straight crashes", "plain", None),
    ("SSSD", "Sideswipe same direction crashes", "striking", None),
    ("SSDD", "Sideswipe opposite direction crashes", "striking", None),
    ("Overturn", "Overturn crashes", "plain", None),
    ("RE", "Rear end crashes", "rear", None),
)
_WHO = {"v1": ("vehicle 1", "unclear direction vehicle 1"),
        "turn": ("turning vehicle", "unclear direction turning vehicle"),
        "plain": ("", "unclear direction"),
        "striking": ("striking vehicle", "unclear direction striking vehicle"),
        "rear": ("rear vehicle", "unclear direction rear vehicle")}
_SINGLE = (("Ped", "Pedestrian crashes"), ("Bike", "Bicycle crashes"),
           ("Animal", "Animal crashes"), ("Other", "Other crashes"))

# styles of the office Trends sheet (styles.xml of the Accessible xlsm)
STYLE = {"title": "104", "head": "5", "group": "630", "label": "631",
         "count": "109", "custom": "107", "note": None}


@dataclass
class CustomLine:
    """One custom Trends line (row 73 on). ``crash_ids`` counts those crashes
    wherever they sit on Before/After; ``rows`` sums other Trends lines by
    label (both of the I/J column block and the C/D block may be named)."""
    label: str
    crash_ids: tuple[str, ...] = ()
    sum_of: tuple[str, ...] = ()
    definition: str = ""


def _rng(period: str, col: str) -> str:
    return f"{period}!${col}${FIRST}:${col}${LAST}"


def _at_fault(period: str, d: str) -> str:
    k, i, j = (_rng(period, c) for c in "KIJ")
    return (f'((({k}="V1")*(LEFT({i},2)="{d}"))'
            f'+(({k}="V2")*(LEFT({j},2)="{d}")))')


def _type_mask(period: str, types) -> str:
    h = _rng(period, "H")
    return "(" + "+".join(f'({h}="{t}")' for t in types) + ")"


def _type_total(period: str, types) -> str:
    h = _rng(period, "H")
    return "+".join(f'COUNTIF({h},"{t}")' for t in types)


def _type_dir(period: str, code: str, who: str, turn: str | None, d: str) -> str:
    h, i, j = (_rng(period, c) for c in "HIJ")
    if who in ("v1", "plain"):
        return f'COUNTIFS({h},"{code}",{i},"{d}*")'
    if who == "turn":
        return (f'COUNTIFS({h},"{code}",{i},"{d}{turn}")'
                f'+COUNTIFS({h},"{code}",{j},"{d}{turn}")')
    return f'SUMPRODUCT(({h}="{code}")*{_at_fault(period, d)})'


def layout(custom: list[CustomLine] | None = None):
    """Cells of the sheet: {ref: (value | None, formula | None, style)} and
    the ordered pick list (F labels, then L labels, then custom labels)."""
    custom = custom or []
    cells: dict[str, tuple] = {}
    labels_f: list[str] = []
    labels_l: list[str] = []
    where: dict[str, tuple[str, int]] = {}        # label -> (block, row)

    def put(ref, value=None, formula=None, style=None):
        cells[ref] = (value, formula, style)

    put("B1", "Trends", style=STYLE["title"])
    put("B2", "Live counts on Before and After (rows 4 to 1003). The One "
              "Pager picks a line by its label in column F or L.")

    # ---- crash type by direction (labels F, counts C/D)
    row = 11
    for code, stem, who, turn in _TYPE_BLOCKS:
        put(f"B{row}", code, style=STYLE["group"])
        put(f"C{row}", "Before", style=STYLE["head"])
        put(f"D{row}", "After", style=STYLE["head"])
        who_txt, unclear_txt = _WHO[who]
        first = row + 1
        for k, d in enumerate(DIRS):
            r = first + k
            label = f"{stem} ({d} {who_txt})" if who_txt else f"{stem} ({d})"
            put(f"F{r}", label, style=STYLE["label"])
            for col, period in (("C", "Before"), ("D", "After")):
                put(f"{col}{r}", formula=_type_dir(period, code, who, turn, d),
                    style=STYLE["count"])
            labels_f.append(label); where[label] = ("CD", r)
        r_unc, r_tot = first + 4, first + 5
        total_label = "Head on crashes (total)" if code == "HeadOn" else f"{stem} (total)"
        put(f"F{r_unc}", f"{stem} ({unclear_txt})", style=STYLE["label"])
        put(f"F{r_tot}", total_label, style=STYLE["label"])
        for col, period in (("C", "Before"), ("D", "After")):
            put(f"{col}{r_tot}", formula=f'COUNTIF({_rng(period, "H")},"{code}")',
                style=STYLE["count"])
            put(f"{col}{r_unc}", formula=f"{col}{r_tot}-SUM({col}{first}:{col}{first + 3})",
                style=STYLE["count"])
        labels_f += [f"{stem} ({unclear_txt})", total_label]
        where[f"{stem} ({unclear_txt})"] = ("CD", r_unc)
        where[total_label] = ("CD", r_tot)
        row += 8
    type_totals = [f"{{c}}{r}" for r in range(17, row, 8)]
    put(f"C{row}", "Before", style=STYLE["head"])
    put(f"D{row}", "After", style=STYLE["head"])
    for k, (code, label) in enumerate(_SINGLE):
        r = row + 1 + k
        put(f"F{r}", label, style=STYLE["label"])
        for col, period in (("C", "Before"), ("D", "After")):
            put(f"{col}{r}", formula=f'COUNTIF({_rng(period, "H")},"{code}")',
                style=STYLE["count"])
        labels_f.append(label); where[label] = ("CD", r)
        type_totals.append(f"{{c}}{r}")

    # ---- fault / approach / target / condition lines (labels L, counts I/J)
    def l_block(head_row, lines):
        put(f"I{head_row}", "Before", style=STYLE["head"])
        put(f"J{head_row}", "After", style=STYLE["head"])
        for k, (label, fb, fa) in enumerate(lines):
            r = head_row + 1 + k
            put(f"L{r}", label, style=STYLE["label"])
            put(f"I{r}", formula=fb.replace("{r}", str(r)), style=STYLE["count"])
            put(f"J{r}", formula=fa.replace("{r}", str(r)), style=STYLE["count"])
            labels_l.append(label); where[label] = ("IJ", r)

    def by_fault(stem, mask_fn, total_fn, unclear="fault unclear"):
        lines = []
        for d in DIRS:
            lines.append((f"{stem} ({d} at fault)",
                          f"SUMPRODUCT({mask_fn('Before')}*{_at_fault('Before', d)})",
                          f"SUMPRODUCT({mask_fn('After')}*{_at_fault('After', d)})"))
        lines.append((f"{stem} ({unclear})", "I{t}-SUM(I{a}:I{b})", "J{t}-SUM(J{a}:J{b})"))
        lines.append((f"{stem} (total)", total_fn("Before"), total_fn("After")))
        return lines

    def placed(head_row, lines):
        a, b, t = head_row + 1, head_row + 4, head_row + 6
        out = []
        for label, fb, fa in lines:
            out.append((label, fb.format(a=a, b=b, t=t), fa.format(a=a, b=b, t=t)))
        l_block(head_row, out)

    fi_mask = lambda p: _type_mask(p, FRONTAL)                    # noqa: E731
    ld_mask = lambda p: _type_mask(p, LANE_DEPARTURE)             # noqa: E731
    placed(11, by_fault("Frontal impact crashes", fi_mask,
                        lambda p: f"SUMPRODUCT({fi_mask(p)}*1)"))
    l_block(19, [(f"Frontal impact crashes involving the {d} approach",
                  f'SUMPRODUCT({fi_mask("Before")}*(((LEFT({_rng("Before", "I")},2)="{d}")'
                  f'+(LEFT({_rng("Before", "J")},2)="{d}"))>0))',
                  f'SUMPRODUCT({fi_mask("After")}*(((LEFT({_rng("After", "I")},2)="{d}")'
                  f'+(LEFT({_rng("After", "J")},2)="{d}"))>0))') for d in DIRS])
    placed(25, by_fault("Lane departure crashes", ld_mask,
                        lambda p: f"SUMPRODUCT({ld_mask(p)}*1)"))
    for n, (head, col) in enumerate(((33, "L"), (41, "M"), (49, "N")), start=1):
        mask = (lambda c: lambda p: f'({_rng(p, c)}="Y")')(col)
        placed(head, by_fault(f"Target {n} crashes", mask,
                              (lambda c: lambda p: f'COUNTIF({_rng(p, c)},"Y")')(col)))
    any_t = lambda p: ("(((" + "+".join(f'({_rng(p, c)}="Y")' for c in "LMN")  # noqa: E731
                       + ")>0)*1)")
    placed(57, by_fault("All target crashes", any_t,
                        lambda p: f"SUMPRODUCT({any_t(p)})"))
    cond = lambda p: [                                            # noqa: E731
        f'COUNTIFS({_rng(p, "D")},">=2",{_rng(p, "D")},"<=3")',
        f'COUNTIFS({_rng(p, "F")},">=4",{_rng(p, "F")},"<=6")',
        "+".join(f'COUNTIF({_rng(p, "G")},"{s}")' for s in "KABC"),
        f'COUNTIF({_rng(p, "H")},"Avoidance*")',
        f'COUNTIF({_rng(p, "K")},"Unclear")']
    l_block(65, list(zip(("Wet crashes", "Night crashes", "Injury crashes",
                          "Avoidance maneuver crashes", "Crashes with fault unclear"),
                         cond("Before"), cond("After"))))

    # ---- custom lines
    put("I72", "Before", style=STYLE["head"])
    put("J72", "After", style=STYLE["head"])
    put("L72", "Custom lines", style=STYLE["group"])
    put("M72", "Definition", style=STYLE["head"])
    labels_c = []
    for k, line in enumerate(custom):
        r = 73 + k
        put(f"L{r}", line.label, style=STYLE["custom"])
        if line.crash_ids:
            ids = ",".join(str(int(c)) for c in line.crash_ids)
            fb = f'SUMPRODUCT(COUNTIF({_rng("Before", "A")},{{{ids}}}))'
            fa = f'SUMPRODUCT(COUNTIF({_rng("After", "A")},{{{ids}}}))'
            text = line.definition or ("Crash IDs " + ", ".join(line.crash_ids))
        else:
            refs_b, refs_a = [], []
            for label in line.sum_of:
                block, rr = where[label]
                refs_b.append(f"{'C' if block == 'CD' else 'I'}{rr}")
                refs_a.append(f"{'D' if block == 'CD' else 'J'}{rr}")
            fb, fa = "+".join(refs_b), "+".join(refs_a)
            text = line.definition or " + ".join(line.sum_of)
        put(f"I{r}", formula=fb, style=STYLE["count"])
        put(f"J{r}", formula=fa, style=STYLE["count"])
        put(f"M{r}", text)
        labels_c.append(line.label); where[line.label] = ("IJ", r)

    # ---- summary
    put("C4", "Before", style=STYLE["head"]); put("D4", "After", style=STYLE["head"])
    put("I4", "Before", style=STYLE["head"]); put("J4", "After", style=STYLE["head"])
    for r, label in ((5, "Total crashes"), (6, "Crashes with a crash type"),
                     (7, "Crashes without a crash type"),
                     (8, "Sum of the crash type totals"), (9, "Check")):
        put(f"B{r}", label, style=STYLE["label"])
    for col, period in (("C", "Before"), ("D", "After")):
        a, h = _rng(period, "A"), _rng(period, "H")
        put(f"{col}5", formula=f"{period}!AB9", style=STYLE["count"])
        put(f"{col}6", formula=f'COUNTIFS({a},"<>",{h},"<>")', style=STYLE["count"])
        put(f"{col}7", formula=f"{col}5-{col}6", style=STYLE["count"])
        put(f"{col}8", formula="SUM(" + ",".join(t.format(c=col) for t in type_totals) + ")",
            style=STYLE["count"])
        put(f"{col}9", formula=f'IF({col}8={col}5,"OK","CHECK")', style=STYLE["count"])
    for r, label, src in ((5, "Target 1 crashes", "L39"), (6, "Lane departure crashes", "L31"),
                          (7, "Rear end crashes", "F121"), (8, "Target 2 crashes", "L47"),
                          (9, "Target 3 crashes", "L55")):
        put(f"H{r}", label, style=STYLE["label"])
        block, rr = where[cells[src][0]]
        put(f"I{r}", formula=f"{'C' if block == 'CD' else 'I'}{rr}", style=STYLE["count"])
        put(f"J{r}", formula=f"{'D' if block == 'CD' else 'J'}{rr}", style=STYLE["count"])

    # ---- definitions and drop-down lists
    notes = ("Vehicle 1 lines use vehicle 1's approach; turning vehicle lines the vehicle "
             "making the turn; striking and rear vehicle lines the at-fault vehicle.",
             "Frontal impact: Angle, LTSR, LTDR, RTSR, RTDR, HeadOn. Lane departure: "
             "RORR, RORL, RORS, Overturn.",
             "Wet: road condition 2 or 3. Night: light 4 to 6. Injury: K, A, B or C.")
    for k, text in enumerate(notes):
        put(f"L{130 + k}", text)
    picks = labels_f + labels_l + labels_c
    lists = (("O", "Crash types", CRASH_TYPES), ("P", "Vehicle codes", VEHICLE_CODES),
             ("Q", "At fault", AT_FAULT), ("R", "Target", ("Y",)),
             ("S", "Trends lines (One Pager picks)", tuple(picks)))
    list_ranges = {}
    for col, head, values in lists:
        put(f"{col}1", head, style=STYLE["head"])
        for k, v in enumerate(values):
            put(f"{col}{2 + k}", v)
        list_ranges[head] = f"Trends!${col}$2:${col}${1 + len(values)}"
    return cells, picks, list_ranges, where


#: defined names of the office workbook that feed the drop-downs
LIST_NAMES = {"CrashTypeList": "Crash types", "VehicleCodeList": "Vehicle codes",
              "AtFaultList": "At fault", "YList": "Target",
              "TrendsMetricList": "Trends lines (One Pager picks)"}

_COLS = ('<cols><col min="2" max="2" width="12.7" customWidth="1"/>'
         '<col min="3" max="4" width="7.7" customWidth="1"/>'
         '<col min="5" max="5" width="2.7" customWidth="1"/>'
         '<col min="6" max="6" width="58" customWidth="1"/>'
         '<col min="7" max="7" width="2.7" customWidth="1"/>'
         '<col min="8" max="8" width="26" customWidth="1"/>'
         '<col min="9" max="10" width="7.7" customWidth="1"/>'
         '<col min="11" max="11" width="2.7" customWidth="1"/>'
         '<col min="12" max="12" width="52" customWidth="1"/>'
         '<col min="13" max="13" width="44" customWidth="1"/>'
         '<col min="14" max="14" width="2.7" customWidth="1"/>'
         '<col min="15" max="18" width="12.7" customWidth="1"/>'
         '<col min="19" max="19" width="58" customWidth="1"/></cols>')


def rows_xml(cells, styled: bool = True) -> str:
    by_row: dict[int, list[str]] = {}
    for ref in cells:
        by_row.setdefault(int(re.search(r"\d+", ref).group(0)), []).append(ref)
    out = []
    for r in sorted(by_row):
        refs = sorted(by_row[r], key=lambda x: _col_index(re.match(r"[A-Z]+", x).group(0)))
        parts = [_cell_xml(ref, cells[ref][0], cells[ref][2] if styled else None,
                           cells[ref][1]) for ref in refs]
        out.append(f'<row r="{r}">' + "".join(parts) + "</row>")
    return "".join(out)


def write_trends(path_in: str, path_out: str, custom: list[CustomLine] | None = None,
                 sheet: str = "Trends", styled: bool = True):
    """Rewrite the Trends sheet of ``path_in`` into ``path_out``; returns the
    pick labels, the list ranges for the defined names and the label rows.
    ``styled`` uses the office workbook's style indexes (STYLE); a plain
    workbook without them takes ``styled=False``."""
    cells, picks, list_ranges, where = layout(custom)
    replace_sheet_rows(path_in, path_out, sheet, rows_xml(cells, styled), from_row=1)
    member = sheet_files(path_out)[sheet]
    with zipfile.ZipFile(path_out) as z:
        infos = z.infolist()
        payload = {i.filename: z.read(i.filename) for i in infos}
    xml = payload[member].decode("utf-8")
    xml = re.sub(r"<cols>.*?</cols>", _COLS, xml, 1, flags=re.S)
    if "<cols>" not in xml:
        xml = xml.replace("<sheetData", _COLS + "<sheetData", 1)
    xml = re.sub(r"<sortState\b.*?</sortState>|<sortState\b[^>]*/>", "", xml, flags=re.S)
    payload[member] = xml.encode("utf-8")
    tmp = path_out + ".trends.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            zout.writestr(info, payload[info.filename])
    os.replace(tmp, path_out)
    names = {name: list_ranges[head] for name, head in LIST_NAMES.items()}
    return picks, names, where


def one_pager_formulas(row: int) -> tuple[str, str]:
    """The office One Pager L/M formulas for pick row ``row``, on the
    workbook's own Trends sheet."""
    before = (f"IFERROR(INDEX(Trends!$C:$C,MATCH($J{row},Trends!$F:$F,0)),"
              f"IFERROR(INDEX(Trends!$I:$I,MATCH($J{row},Trends!$L:$L,0)),\"\"))")
    after = (f"IFERROR(INDEX(Trends!$D:$D,MATCH($J{row},Trends!$F:$F,0)),"
             f"IFERROR(INDEX(Trends!$J:$J,MATCH($J{row},Trends!$L:$L,0)),\"\"))")
    return before, after


__all__ = ["CustomLine", "layout", "write_trends", "one_pager_formulas",
           "CRASH_TYPES", "VEHICLE_CODES", "AT_FAULT", "LIST_NAMES"]
