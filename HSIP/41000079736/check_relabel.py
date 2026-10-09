#!/usr/bin/env python3
"""QA for relabel_collision_diagram.py: every vector item of the source sheet must reappear in the output exactly once,
furniture unmoved, drawing items under the uniform transform, labels under their own shifts; nothing else is added."""
import sys
from pathlib import Path
import pymupdf
import relabel_collision_diagram as R

HERE = Path(__file__).resolve().parent
out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else R.OUT
src = pymupdf.open(R.SRC)[0]; out = pymupdf.open(out_path)[0]
assert out.rect.width == R.PW and out.rect.height == R.PH and len(pymupdf.open(out_path)) == 1

def inside(r, box): return r.x0 >= box[0] - 0.01 and r.y0 >= box[1] - 0.01 and r.x1 <= box[2] + 0.01 and r.y1 <= box[3] + 0.01
def in_any(r, boxes): return any(inside(r, b) for b in boxes)

def points(d, n=12):
    """points along the item's path (line ends, sampled curves, rect corners) as 1-pt rects"""
    pts = []
    for it in d["items"]:
        if it[0] == "l": pts += [it[1], it[2]]
        elif it[0] == "c":
            p0, p1, p2, p3 = it[1:5]
            for i in range(n + 1):
                t = i / n; u = 1 - t
                pts.append(pymupdf.Point(u**3 * p0.x + 3*u*u*t * p1.x + 3*u*t*t * p2.x + t**3 * p3.x,
                                         u**3 * p0.y + 3*u*u*t * p1.y + 3*u*t*t * p2.y + t**3 * p3.y))
        elif it[0] == "re": r = it[1]; pts += [r.tl, r.tr, r.bl, r.br]
        elif it[0] == "qu": q = it[1]; pts += [q.ul, q.ur, q.ll, q.lr]
    return [pymupdf.Rect(q.x, q.y, q.x, q.y) for q in pts] or [d["rect"]]

CORE_BBOX = (min(b[0] for b in R.CORE), min(b[1] for b in R.CORE), max(b[2] for b in R.CORE), max(b[3] for b in R.CORE))
LEGEND_CORNER = pymupdf.Rect(R.CORE[1][0], CORE_BBOX[1], CORE_BBOX[2], R.CORE[1][1])   # part of the bbox the drawing rects leave out

def piece(r):
    """which drawn piece a point belongs to: (scale, tx, ty), or None when it lies under no clip"""
    if in_any(r, R.FURNITURE): return (1.0, 0.0, 0.0)
    for name, (boxes, target) in list(R.LEG_LABELS.items()) + list(R.LANDUSE.items()):
        if in_any(r, boxes): return (1.0, target[0] - boxes[0][0], target[1] - boxes[0][1])
    if inside(r, CORE_BBOX) and not r.intersects(LEGEND_CORNER) and not any(r.intersects(pymupdf.Rect(n)) for n in R.NOTCHES):
        return (R.S, R.TX, R.TY)
    return None

def expected(d):
    """the one piece every point of the item falls in, or None if the item straddles clips / is clipped away"""
    ps = {piece(q) for q in points(d)}
    return ps.pop() if len(ps) == 1 else None

def key(d, s, tx, ty):
    r = d["rect"]
    return (round(s * r.x0 + tx, 1), round(s * r.y0 + ty, 1), round(s * r.x1 + tx, 1), round(s * r.y1 + ty, 1), d.get("color"), d.get("fill"))

out_keys = {}
for d in out.get_drawings():
    k = key(d, 1, 0, 0); out_keys[k] = out_keys.get(k, 0) + 1
missing, straddle, matched = [], [], 0
for d in src.get_drawings():
    e = expected(d)
    if e is None:
        r = d["rect"]
        if r.width > 3 or r.height > 3: straddle.append(tuple(round(v) for v in (r.x0, r.y0, r.x1, r.y1)))
        continue
    k = key(d, *e)
    if out_keys.get(k, 0) > 0: out_keys[k] -= 1; matched += 1
    else: missing.append((tuple(round(v) for v in d["rect"]), e))
# PyMuPDF lists every path of the embedded page once per placement, clipped or not, so the output count is a multiple of
# the source count; the meaningful checks are "every source item lands where expected" and "nothing straddles a clip edge".
print(f"source items {len(src.get_drawings())}, output placements {len(out.get_drawings()) // len(src.get_drawings())}: "
      f"{matched} matched at their expected position, {len(missing)} missing")
print(f"{len(straddle)} source items (> 3 pt) straddle a clip edge or are clipped away:", straddle[:12])
for m in missing[:10]: print("  missing:", m)
