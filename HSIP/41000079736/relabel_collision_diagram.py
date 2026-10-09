#!/usr/bin/env python3
"""
Enlarge and centre the MicroStation collision diagram for Order# 41000079736 without redrawing anything.

Input : data/41000079736_CollisionDiagram_VHB.pdf  (17 x 11 sheet exported from MicroStation, with the author's
        leg labels: route, street, AADT (Year) for the middle study year 2021, posted speed)
Output: maps/41000079736_CollisionDiagram_labeled.pdf  (or the path given as the first argument)

The original page is embedded as a Form XObject and drawn in pieces, each under its own clip:
  * sheet furniture (border, title text, legend, title block) stays exactly where it was;
  * the drawing (roads, crashes, insets A/B, STOP signs) is drawn once more, scaled uniformly by S and
    translated - no line or crash symbol is redrawn or altered, only enlarged as a whole;
  * the four leg labels and the four land-use labels are drawn at their original size, each moved to a
    spot beside the enlarged roads so they stay on the sheet and off the pavement.
All coordinates below are PDF points with the origin at the TOP-left (PyMuPDF convention); they are
converted to PDF user space when written.
"""
import sys
from pathlib import Path
import pikepdf

HERE = Path(__file__).resolve().parent
SRC = HERE / "data" / "41000079736_CollisionDiagram_VHB.pdf"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "maps" / "41000079736_CollisionDiagram_labeled.pdf"
PW, PH = 1224.0, 792.0                      # 17 x 11 in

# ---------------------------------------------------------------- geometry of the source sheet (top-left origin, points)
# The drawing (bbox 453-901 x 101-672) as non-overlapping rectangles that stop short of the legend (x >= 806 above
# y = 190). Drawn with the even-odd rule, so the NOTCHES - the parts of the label boxes that reach into the drawing
# rectangles - are cut out and those labels can be placed separately. Every notch lies inside one drawing rectangle.
CORE = [(448.0, 98.0, 804.0, 676.0), (804.0, 190.0, 910.0, 676.0)]
NOTCHES = [(620.0, 98.0, 724.0, 106.0),     # bottom of the "M&D Quick Stop" box
           (495.0, 98.0, 540.0, 108.0),     # "45 mph" line of the SR 1103 (Pleasant Dr) label
           (800.0, 208.0, 804.0, 268.0), (804.0, 208.0, 910.0, 268.0),   # NC 180/NC 226 north label (one notch per rectangle)
           (821.0, 604.0, 910.0, 640.0),    # SR 1103 (Pleasant Hill Church Rd) label, upper lines (clear of the parcel arch)
           (845.0, 640.0, 910.0, 676.0)]    # ... lower lines
FURNITURE = [(30.0, 35.0, 340.0, 140.0),    # title text
             (806.0, 18.0, 1215.0, 190.0),  # legend
             (1008.0, 636.0, 1215.0, 775.0),  # title block
             (0.0, 0.0, PW, 27.0), (0.0, 765.0, PW, PH), (0.0, 0.0, 20.0, PH), (1204.0, 0.0, PW, PH)]  # border + plot marks

# ---------------------------------------------------------------- enlargement
S = 1.20                                   # 1.264 would touch both border lines; 1.20 leaves a band above the
TOP_BAND = 48.0                            # drawing for the north-leg label
TX = (18.0 + 1206.0) / 2 - S * (453.0 + 876.0) / 2         # centre the drawing between the border lines
TY = 25.0 + TOP_BAND - S * 101.0

# labels drawn at their original size: box in the source -> top-left corner on the new sheet
LEG_LABELS = {                              # the author's lettering, values = AADT for the middle study year (2021);
    "SR 1103 (Pleasant Dr)":              ([(462.0, 41.0, 572.0, 97.0), (495.0, 97.0, 540.0, 109.0)], (338.0, 150.0)),
    "NC 180/NC 226 north":                ([(800.0, 212.0, 929.0, 266.0)], (590.0, 28.0)),
    "NC 180/NC 226 south":                ([(560.0, 684.0, 687.0, 737.0)], (622.0, 690.0)),
    "SR 1103 (Pleasant Hill Church Rd)":  ([(820.0, 607.0, 941.0, 640.0), (845.0, 640.0, 941.0, 674.0)], (845.0, 597.0)),
}   # clip boxes are shaped so that no road line next to a label in the source comes along with it
LANDUSE = {                                 # (clip boxes, top-left target, scale): the M&D label is drawn at 0.9 so it sits
    "M&D Quick Stop": ([(620.0, 66.0, 724.0, 106.0)], (572.0, 179.0), 0.9),   # between the frontage arc and the lane line
    "Dollar General": ([(290.0, 398.0, 394.0, 438.0)], (180.0, 432.0), 1.0),
    "Undeveloped":    ([(923.0, 363.0, 1027.0, 403.0)], (930.0, 392.0), 1.0),
    "Empty Lot":      ([(708.0, 714.0, 812.0, 754.0)], (852.0, 696.0), 1.0),
}


# ---------------------------------------------------------------- content stream helpers (PDF user space, origin bottom-left)
def f(v): return f"{v:.3f}".rstrip("0").rstrip(".")
def rect_path(x0, y0, x1, y1): return f"{f(x0)} {f(PH - y1)} {f(x1 - x0)} {f(y1 - y0)} re\n"
def matrix(s, tx, ty): return f"{f(s)} 0 0 {f(s)} {f(tx)} {f(PH * (1 - s) - ty)} cm\n"
def T(x, y): return (S * x + TX, S * y + TY)


def main():
    src = pikepdf.open(SRC); out = pikepdf.new()
    form = out.copy_foreign(src.pages[0].as_form_xobject())
    page = out.add_blank_page(page_size=(PW, PH))
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Fm0=form))
    c = []
    # 1. furniture, unmoved
    c.append("q\n" + "".join(rect_path(*r) for r in FURNITURE) + "W n\n/Fm0 Do\nQ\n")
    # 2. the drawing, enlarged: clip = CORE minus the notches (even-odd), in source coordinates under the matrix
    c.append("q\n" + matrix(S, TX, TY) + "".join(rect_path(*r) for r in CORE + NOTCHES) + "W* n\n/Fm0 Do\nQ\n")
    # 3. leg labels and land-use labels at their original size, each at its own spot
    for name, entry in list(LEG_LABELS.items()) + list(LANDUSE.items()):
        boxes, target = entry[0], entry[1]; sc = entry[2] if len(entry) > 2 else 1.0
        tx, ty = target[0] - sc * boxes[0][0], target[1] - sc * boxes[0][1]
        c.append("q\n" + matrix(sc, tx, ty) + "".join(rect_path(*b) for b in boxes) + "W n\n/Fm0 Do\nQ\n")
    page.Contents = out.make_stream("".join(c).encode("latin-1"))
    out.docinfo["/Title"] = "Collision Diagram - Order# 41000079736"
    out.save(OUT)
    print(f"scale {S:.3f}, drawing bbox -> ({T(453, 101)[0]:.0f}, {T(453, 101)[1]:.0f})-({T(901, 672)[0]:.0f}, {T(901, 672)[1]:.0f}); wrote {OUT}")
    for name, entry in list(LEG_LABELS.items()) + list(LANDUSE.items()):
        print(f"  {name:34} at ({entry[1][0]:.0f}, {entry[1][1]:.0f})" + (f" scale {entry[2]}" if len(entry) > 2 else ""))


if __name__ == "__main__":
    main()
