"""Fit a report text block to its merged cell by sizing the font.

The engineer never changes a row height on the printed 1-pager: every
completed workbook keeps rows 58-66 at 15.0pt and row 57 at 18.0pt.
When a text block outgrows its merged cell he shrinks the font instead
(Items for Discussion at 11.0, 10.0 and 9.5pt across the archive;
Countermeasure(s) at 9.0, 8.5 and 8.0pt), and only when even that is not
enough does he grow the box by inserting whole rows, always leaving at
least one blank row above 'Data Prepared For:'.

This module measures how many lines a block wraps to at a given size, so
the size can be chosen the same way: the largest that still fits.

Measurement uses the real font metrics. Times New Roman and Liberation
Serif are metric-identical (same unitsPerEm, ascent, descent and every
advance width), so either file measures the same; the msttcorefonts copy
is preferred only so the exported PDF embeds the same face the engineer's
own prints do.
"""
from __future__ import annotations

import re

#: Font file candidates per family, best first. Metric-compatible clones
#: are equivalent for measurement.
_FONT_FILES = {
    "times new roman": (
        "/usr/share/fonts/truetype/msttcorefonts/Times.TTF",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    ),
    "calibri": (
        "/usr/share/fonts/truetype/msttcorefonts/calibri.ttf",
        "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
    ),
}

#: Line advance as a multiple of the font size. Times New Roman is
#: (ascent 1825 + descent 443 + gap 87) / 2048 = 1.150; rendered prints
#: measure 1.12 to 1.13, so this is the conservative end.
LINE_FACTOR = 1.15

#: Excel reserves a couple of pixels of padding on each side of a cell.
CELL_PAD_PT = 5.0

#: Font sizes the engineer actually uses, largest first (0.5pt grid).
SIZE_LADDER = (11.0, 10.5, 10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0)


def _font_path(family: str) -> str:
    import os
    for path in _FONT_FILES.get(family.strip().lower(), ()):
        if os.path.exists(path):
            return path
    raise RuntimeError(
        f"No font file on this host for {family!r}; install msttcorefonts "
        "or the metric-compatible clone (fonts-liberation / carlito).")


def column_width_pt(chars: float) -> float:
    """Excel column width (in '0'-digit units) as points.

    pixels = round(width * MDW) + padding, with MDW = 7px for the 11pt
    default font; points = pixels * 0.75.
    """
    return (round(chars * 7) + 5) * 0.75


def sheet_geometry(xml: str) -> tuple[dict, dict]:
    """(column widths in points by letter, row heights in points by row)."""
    widths: dict[str, float] = {}
    for col in re.findall(r"<col\b[^>]*/>", xml):
        lo = int(re.search(r'min="(\d+)"', col).group(1))
        hi = int(re.search(r'max="(\d+)"', col).group(1))
        w = re.search(r'width="([\d.]+)"', col)
        if w is None:
            continue
        pts = column_width_pt(float(w.group(1)))
        for i in range(lo, min(hi, 40) + 1):
            widths[_letter(i)] = pts
    heights: dict[int, float] = {}
    for row, attrs in re.findall(r'<row r="(\d+)"([^>]*)>', xml):
        h = re.search(r'ht="([\d.]+)"', attrs)
        heights[int(row)] = float(h.group(1)) if h else 15.0
    return widths, heights


def _letter(index: int) -> str:
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _index(letter: str) -> int:
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch) - 64)
    return n


def box_size_pt(xml: str, merge_ref: str) -> tuple[float, float]:
    """Usable (width, height) of a merged range, in points."""
    m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)$", merge_ref)
    if m is None:
        raise ValueError(f"not a merged range: {merge_ref!r}")
    c0, r0, c1, r1 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
    widths, heights = sheet_geometry(xml)
    width = sum(widths.get(_letter(i), column_width_pt(8.43))
                for i in range(_index(c0), _index(c1) + 1))
    height = sum(heights.get(r, 15.0) for r in range(r0, r1 + 1))
    return width - CELL_PAD_PT, height


def wrapped_lines(text: str, size_pt: float, width_pt: float,
                  family: str = "Times New Roman") -> int:
    """Display lines the text occupies, wrapped the way Excel wraps it.

    Hard breaks at newlines; inside a paragraph, greedy break on spaces.
    """
    from PIL import ImageFont

    ref = 200                      # measure large, scale down: less rounding
    font = ImageFont.truetype(_font_path(family), ref)
    scale = size_pt / ref

    def width_of(s: str) -> float:
        return font.getlength(s) * scale

    lines = 0
    for para in text.split("\n"):
        para = para.rstrip()
        if not para:
            lines += 1
            continue
        used, count = "", 1
        for word in para.split(" "):
            trial = word if not used else used + " " + word
            if width_of(trial) <= width_pt:
                used = trial
            else:
                count += 1
                used = word
        lines += count
    return lines


def fit_font_size(text: str, width_pt: float, height_pt: float,
                  family: str = "Times New Roman",
                  sizes=SIZE_LADDER, line_factor: float = LINE_FACTOR):
    """Largest ladder size whose wrapped text fits, or None.

    Returns ``(size, lines, needed_pt)``; ``size`` is None when even the
    smallest candidate overflows, and ``needed_pt`` is then the height the
    smallest candidate would need.
    """
    last = None
    for size in sizes:
        lines = wrapped_lines(text, size, width_pt, family)
        needed = lines * line_factor * size
        last = (None, lines, needed)
        if needed <= height_pt:
            return (size, lines, needed)
    return last


def rows_needed(text: str, size_pt: float, width_pt: float,
                row_height_pt: float = 15.0,
                family: str = "Times New Roman",
                line_factor: float = LINE_FACTOR) -> int:
    """Whole rows of ``row_height_pt`` needed to hold the text at a size."""
    lines = wrapped_lines(text, size_pt, width_pt, family)
    import math
    return int(math.ceil(lines * line_factor * size_pt / row_height_pt))
