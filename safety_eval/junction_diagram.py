"""Intersection collision diagram drawn on a measured junction.

The TSU sheets for a signalized or complex intersection are drawn on the
junction as it is: every lane, the raised medians and islands, stop bars,
ladder crosswalks and pavement arrows measured off the aerial, with each
crash's cell on the approach its units were travelling on, at the point
where their paths meet. This module renders that sheet from a junction
spec (a JSON file of legs, edges, islands, crosswalks and sheet
furniture; see ``studies/<WO>/junction_spec.json`` for a complete one)
and the TEAAS CollisionDiagramData export.

Geometry is a parametric model in ground feet, north up, origin at the
junction node. Each leg has a bearing and cross-section (curbs, lane
centres, medians) in its own frame; edges of pavement, islands and
crosswalks are digitized polylines. The sheet turns the model
``rotate`` degrees clockwise so the main road runs across the page.

Placement follows the office examples. Cells are rigid glyphs made of
segments and discs in page pixels; a cell may go where none of its
primitives comes within a clearance of any other cell, a crosswalk, a
stop bar, a pavement arrow, an island, the curb line or any sheet text.
Rear ends and same-direction sideswipes stack across the approach at the
stop bar; turning and angle crashes nest diagonally back from their
conflict point; run-off-road and object crashes sit on the shoulder;
pedestrian and bicycle crashes on the crosswalk. Whatever finds no room
within its search goes to a lettered inset with a matching circled
letter and leader at the spot, exactly as the sheets do it.
"""
from __future__ import annotations

import csv
import json
import math
import os
import textwrap

import numpy as np

from . import collision_diagram as cd

# ---------------------------------------------------------------- module state
SPEC: dict = {}
ROT = 0.0                       # sheet turn, degrees clockwise
PX = 2.8                        # px per ft
CX, CY = 800.0, 600.0           # junction node on the page
CS = 0.72                       # cell scale
FAR = 520.0                     # a leg's far end, ft
BOX_R = 45.0                    # the junction box: on pavement within this of the node
LEGS: dict = {}
ORDER: list = []
APPROACH: dict = {}             # "<leg>_in" -> (leg key, coded inbound heading)
ROAD_OF_LEG: dict = {}
ROAD_APPS: dict = {}
ROAD_CODES: dict = {}
ROADS: list = []
MAIN = ""
UNNAMED = None
SIGNAL = False

EDGE_SW = "1.3"
LINE_SW = "0.9"
QUEUE_PITCH = 7.5               # ft between stacked rear-end cells across an approach
NEST_STEP = 8.0                 # ft between nested turning and angle cells
ALONG_STEP = 8.0                # ft between successive stations back from the stop bar
CLEAR_CELL = 3.0                # px, cell to cell
CLEAR_OBS = 2.0                 # px, cell to linework
INSET_COLOURS = ["#1f3fd6", "#d61f1f", "#e08a00", "#1f9e1f", "#8a2be2", "#00a3c4", "#a0522d", "#555"]
DIR = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


# ---------------------------------------------------------------- geometry
def hv(h):
    """Compass heading -> ground unit vector (x east, y north)."""
    r = math.radians(h)
    return math.sin(r), math.cos(r)


def add(p, q, k=1.0):
    return p[0] + q[0] * k, p[1] + q[1] * k


def dot(p, q):
    return p[0] * q[0] + p[1] * q[1]


def page(p):
    """Ground ft -> page px (sheet turned ROT clockwise)."""
    r = math.radians(ROT)
    x = p[0] * math.cos(r) + p[1] * math.sin(r)
    y = -p[0] * math.sin(r) + p[1] * math.cos(r)
    return CX + x * PX, CY - y * PX


def page_ang(h):
    """Compass heading -> SVG degrees (0 = +x, clockwise positive)."""
    return h + ROT - 90.0


def adiff(a, b):
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def line_x(p, d, q, e):
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return p[0] + t * d[0], p[1] + t * d[1]


class Leg:
    """One leg out of the junction. ``n`` is right of outbound travel,
    ``along`` is distance out from the node."""

    def __init__(self, key, bearing, **kw):
        self.key = key
        self.b = bearing
        self.out = hv(bearing)
        self.right = hv(bearing + 90)
        self.origin = (0.0, 0.0)
        self.lines = []
        self.double = []
        self.lanes_in = {}
        self.lanes_out = {}
        self.in_edge = -12.0
        self.out_edge = 12.0
        self.stop = 40.0
        self.cw = None
        self.__dict__.update(kw)

    def pt(self, along, n):
        return (self.origin[0] + along * self.out[0] + n * self.right[0],
                self.origin[1] + along * self.out[1] + n * self.right[1])

    def frame(self, p):
        q = (p[0] - self.origin[0], p[1] - self.origin[1])
        return dot(q, self.out), dot(q, self.right)

    @property
    def hin(self):
        """True inbound heading (compass)."""
        return (self.b + 180.0) % 360.0


def fillet(pA, dA, pB, dB, r):
    """Arc tangent to line A (through pA, direction dA, pointing away from
    the corner) and line B; returns (tangent point A, arc points, tangent
    point B)."""
    X = line_x(pA, dA, pB, dB)
    ang = math.acos(max(-1.0, min(1.0, dot(dA, dB))))
    d = r / math.tan(ang / 2.0)
    tA = add(X, dA, d)
    tB = add(X, dB, d)
    bis = (dA[0] + dB[0], dA[1] + dB[1])
    bl = math.hypot(*bis) or 1.0
    bis = (bis[0] / bl, bis[1] / bl)
    C = add(X, bis, r / math.sin(ang / 2.0))
    a0 = math.atan2(tA[1] - C[1], tA[0] - C[0])
    a1 = math.atan2(tB[1] - C[1], tB[0] - C[0])
    while a1 - a0 > math.pi:
        a1 -= 2 * math.pi
    while a1 - a0 < -math.pi:
        a1 += 2 * math.pi
    n = 16
    arc = [(C[0] + r * math.cos(a0 + (a1 - a0) * k / n),
            C[1] + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]
    return tA, arc, tB


def chaikin(pts, passes=2, closed=False):
    for _ in range(passes):
        out = []
        n = len(pts)
        rng = range(n) if closed else range(n - 1)
        for i in rng:
            p, q = pts[i], pts[(i + 1) % n]
            out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        if not closed:
            out = [pts[0]] + out + [pts[-1]]
        pts = out
    return pts


def poly(pts, close=False, **attrs):
    d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in (page(p) for p in pts))
    if close:
        d += " Z"
    a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<path d="{d}" fill="none" {a}/>'


# ---------------------------------------------------------------- the spec
def _num(v):
    return FAR if isinstance(v, str) and v.upper() == "FAR" else float(v)


def _pt(item):
    """A spec point: [x, y] ground ft, or {"leg", "a", "n"} in a leg frame."""
    if isinstance(item, dict):
        return LEGS[item["leg"]].pt(_num(item["a"]), _num(item["n"]))
    return float(item[0]), float(item[1])


def _dir(name):
    if name.startswith("-"):
        v = LEGS[name[1:]].out
        return (-v[0], -v[1])
    return LEGS[name].out


def _path(items):
    out = []
    for it in items:
        if isinstance(it, dict) and "smooth" in it:
            out += chaikin([_pt(p) for p in it["smooth"]], passes=it.get("passes", 1))
        elif isinstance(it, dict) and "fillet" in it:
            f = it["fillet"]
            tA, arc, tB = fillet(_pt(f["a"]), _dir(f["da"]), _pt(f["b"]), _dir(f["db"]), float(f["r"]))
            out += [tA] + arc + [tB]
        else:
            out.append(_pt(it))
    return out


def configure(spec: dict):
    """Load a junction spec into the module state."""
    global SPEC, ROT, PX, CX, CY, CS, FAR, BOX_R, LEGS, ORDER, APPROACH, ROAD_OF_LEG
    global ROAD_APPS, ROAD_CODES, ROADS, MAIN, UNNAMED, SIGNAL
    global _PAVEMENT
    SPEC = spec
    _PAVEMENT = None
    ROT = float(spec.get("rotate", 0.0))
    PX = float(spec.get("px_per_ft", 2.8))
    CX, CY = (float(v) for v in spec.get("center", [800, 600]))
    CS = float(spec.get("cell_scale", 0.72))
    FAR = float(spec.get("far", 520.0))
    BOX_R = float(spec.get("box_radius", 45.0))
    SIGNAL = bool(spec.get("signal", False))
    LEGS = {}
    ROAD_OF_LEG, ROAD_APPS, ROAD_CODES, APPROACH = {}, {}, {}, {}
    UNNAMED = None
    for key, d in spec["legs"].items():
        attrs = {}
        for k, v in d.items():
            if k == "bearing":
                continue
            if k in ("lines",):
                attrs[k] = [(_num(n), _num(a0), _num(a1), sty) for n, a0, a1, sty in v]
            elif k in ("double",):
                attrs[k] = [(_num(n), _num(a0), _num(a1)) for n, a0, a1 in v]
            elif k in ("median_poly",):
                attrs[k] = [(_num(a), _num(n)) for a, n in v]
            elif k in ("gore", "tapers"):
                attrs[k] = [((_num(a0), _num(n0)), (_num(a1), _num(n1))) for (a0, n0), (a1, n1) in v]
            elif k in ("median", "cw"):
                attrs[k] = tuple(float(x) for x in v)
            elif k in ("lanes_in", "lanes_out"):
                attrs[k] = {lk: float(ln) for lk, ln in v.items()}
            else:
                attrs[k] = v
        L = Leg(key, float(d["bearing"]), **attrs)
        LEGS[key] = L
        road = d.get("road", key)
        ROAD_OF_LEG[key] = road
        ROAD_APPS.setdefault(road, []).append(f"{key}_in")
        ROAD_CODES.setdefault(road, set()).update(str(c) for c in d.get("codes", []))
        APPROACH[f"{key}_in"] = (key, float(d.get("in_heading", L.hin)))
        if d.get("unnamed"):
            UNNAMED = road
    ORDER = list(spec.get("order") or sorted(LEGS, key=lambda k: LEGS[k].b))
    ROADS = []
    for k in ORDER:
        if ROAD_OF_LEG[k] not in ROADS:
            ROADS.append(ROAD_OF_LEG[k])
    MAIN = spec.get("main_road") or max(ROADS, key=lambda r: (len(ROAD_APPS[r]), -ROADS.index(r)))
    return spec


# ---------------------------------------------------------------- linework
def pavement_edges():
    return [_path(e) for e in SPEC.get("edges", [])]


_PAVEMENT = None


def _is_far(item):
    return isinstance(item, dict) and isinstance(item.get("a"), str) and item["a"].upper() == "FAR"


def pavement_polygon():
    """The pavement as one polygon: the curb stretches that run from one
    leg's far end round a corner to the next leg's far end, taken in the
    order the spec lists them and closed across each leg's far end. Curb
    stubs (an island face, a median nose) are not part of the loop."""
    global _PAVEMENT
    if _PAVEMENT is None:
        pts = []
        for e in SPEC.get("edges", []):
            if _is_far(e[0]) and _is_far(e[-1]):
                pts += _path(e)
        _PAVEMENT = pts
    return _PAVEMENT


def islands():
    out = []
    for isl in SPEC.get("islands", []):
        pts = [_pt(p) for p in isl["pts"]]
        out.append(chaikin(pts, passes=isl.get("passes", 2), closed=True) if isl.get("passes", 2) else pts)
    return out


def crosswalks():
    """Painted crosswalks: p0..p1 the band's centreline in ground ft, the
    bars drawn along ``bar_brg`` across ``width``."""
    out = []
    for cw in SPEC.get("crosswalks", []):
        if "band" in cw:
            L = LEGS[cw["band"]]
            d = hv(float(cw["dir"]))
            c = tuple(cw["c"])
            p0 = line_x(c, d, L.pt(0, float(cw["n0"])), L.out)
            p1 = line_x(c, d, L.pt(0, float(cw["n1"])), L.out)
            leg = L
        else:
            p0, p1 = _pt(cw["p0"]), _pt(cw["p1"])
            leg = LEGS[cw["leg"]] if cw.get("leg") else None
        out.append({"p0": p0, "p1": p1, "width": float(cw["width"]), "bar_brg": float(cw["bar_brg"]),
                    "leg": leg, "pitch": float(cw.get("pitch", 4.0)), "bar_w": float(cw.get("bar_w", 2.0)),
                    "stop": cw.get("stop", True)})
    return out


def head_at(p, ang, h):
    a = math.radians(ang)
    c, s = math.cos(a), math.sin(a)
    pts = [(0, 0), (-h, h * 0.55), (-h * 0.7, 0), (-h, -h * 0.55)]
    q = " ".join(f"{p[0] + x * c - y * s:.1f},{p[1] + x * s + y * c:.1f}" for x, y in pts)
    return f'<polygon points="{q}" fill="#000"/>'


def pav_arrow(A, along, n, kind):
    """Lane use arrow: T straight, L hook left, R hook right. Returns the
    svg and its obstacle primitives."""
    tail = A.pt(along + 8, n)
    head = A.pt(along - 2, n)
    pts = [page(tail), page(head)]
    ang = page_ang(A.b + 180)
    sw = 1.3 * PX
    svg = [f'<line x1="{pts[0][0]:.1f}" y1="{pts[0][1]:.1f}" x2="{pts[1][0]:.1f}" '
           f'y2="{pts[1][1]:.1f}" stroke="#000" stroke-width="{sw:.1f}"/>']
    hs = 3.2 * PX
    prims = [("s", pts[0], pts[1], sw / 2)]
    if kind == "T":
        svg.append(head_at(pts[1], ang, hs))
        prims.append(("d", pts[1], hs * 0.6))
    else:
        turn = -90.0 if kind == "L" else 90.0
        hx, hy = pts[1]
        a = math.radians(ang)
        a2 = math.radians(ang + turn)
        r = 2.4 * PX
        cx_, cy_ = hx + r * math.cos(a), hy + r * math.sin(a)
        ex, ey = cx_ + r * math.cos(a2), cy_ + r * math.sin(a2)
        svg.append(f'<path d="M {hx:.1f},{hy:.1f} Q {cx_:.1f},{cy_:.1f} {ex:.1f},{ey:.1f}" '
                   f'fill="none" stroke="#000" stroke-width="{sw:.1f}"/>')
        svg.append(head_at((ex, ey), ang + turn, hs))
        prims += [("s", (hx, hy), (ex, ey), sw / 2), ("d", (ex, ey), hs * 0.6)]
    return "".join(svg), prims


def junction_svg():
    """The junction linework. Returns (svg list, obstacles) where each
    obstacle is (kind, prim) in page px; sets each leg's ``stop``."""
    out, obs = [], []
    for A in LEGS.values():
        for n, a0, a1, style in A.lines:
            if style == "dashed":
                out.append(poly([A.pt(a0, n), A.pt(a1, n)], stroke="#000", stroke_width=LINE_SW,
                                stroke_dasharray=f"{10 * PX:.0f} {30 * PX:.0f}"))
            else:
                out.append(poly([A.pt(a0, n), A.pt(a1, n)], stroke="#000", stroke_width=LINE_SW))
        for n, a0, a1 in A.double:
            for dn in (-0.5, 0.5):
                out.append(poly([A.pt(a0, n + dn), A.pt(a1, n + dn)], stroke="#000", stroke_width=LINE_SW))
        for (a0, n0), (a1, n1) in getattr(A, "gore", []):
            out.append(poly([A.pt(a0, n0), A.pt(a1, n1)], stroke="#000", stroke_width=LINE_SW))
        for (a0, n0), (a1, n1) in getattr(A, "tapers", []):
            out.append(poly([A.pt(a0, n0), A.pt(a1, n1)], stroke="#000", stroke_width=LINE_SW))
    for key, A in LEGS.items():
        mp = getattr(A, "median_poly", None)
        if mp:
            pts = chaikin([A.pt(a, n) for a, n in mp], passes=1, closed=True)
            out.append(poly(pts, close=True, fill="#fff", stroke="#000", stroke_width=EDGE_SW).replace('fill="none" ', ""))
            obs.append(("island", ("p", [page(p) for p in pts])))
    for isl in islands():
        out.append(poly(isl, close=True, fill="#fff", stroke="#000", stroke_width=EDGE_SW).replace('fill="none" ', ""))
        obs.append(("island", ("p", [page(p) for p in isl])))
    for e in pavement_edges():
        out.append(poly(e, stroke="#000", stroke_width=EDGE_SW, stroke_linejoin="round"))
        pp = [page(p) for p in e]
        for i in range(len(pp) - 1):
            obs.append(("edge", ("s", pp[i], pp[i + 1], 0.7)))
    for cw in crosswalks():
        p0, p1 = cw["p0"], cw["p1"]
        d = (p1[0] - p0[0], p1[1] - p0[1])
        ln = math.hypot(*d) or 1.0
        d = (d[0] / ln, d[1] / ln)
        nb = hv(cw["bar_brg"])
        w = cw["width"]
        corners = [add(p0, nb, -w / 2), add(p1, nb, -w / 2), add(p1, nb, w / 2), add(p0, nb, w / 2)]
        out.append(poly(corners, close=True, stroke="#000", stroke_width="0.7"))
        obs.append(("cw", ("p", [page(c) for c in corners])))
        k = cw["pitch"] / 2
        while k < ln:
            c = add(p0, d, k)
            out.append(poly([add(c, nb, -w / 2 + 0.5), add(c, nb, w / 2 - 0.5)], stroke="#000",
                            stroke_width=f"{cw['bar_w'] * PX * 0.9:.1f}"))
            k += cw["pitch"]
        A = cw["leg"]
        if A is None or not cw["stop"]:
            continue
        outward = nb if dot(nb, A.out) > 0 else (-nb[0], -nb[1])
        base = add(p0, outward, w / 2 + 4.0)
        stop_hi = A.median[0] if getattr(A, "median", None) else getattr(A, "centre", 0.0)
        qa = line_x(base, d, A.pt(0, A.in_edge + 0.8), A.out)
        qb = line_x(base, d, A.pt(0, stop_hi - 0.8), A.out)
        if qa and qb:
            out.append(poly([qa, qb], stroke="#000", stroke_width=f"{max(2.4, 1.5 * PX * 0.5):.1f}"))
            obs.append(("stop", ("s", page(qa), page(qb), 2.0)))
            A.stop = (A.frame(qa)[0] + A.frame(qb)[0]) / 2
    arrow_at = float(SPEC.get("arrow_at", 60.0))
    for A in LEGS.values():
        for lane, n in A.lanes_in.items():
            if lane in getattr(A, "no_arrow", ()):
                continue
            svg, prims = pav_arrow(A, A.stop + arrow_at, n, lane[0])
            out.append(svg)
            obs += [("arrow", p) for p in prims]
    return out, obs


def signal_symbol():
    x, y = page((0.0, 0.0))
    x, y = x - 7, y - 21
    out = [f'<rect x="{x - 7:.1f}" y="{y - 7:.1f}" width="14" height="42" fill="#fff" stroke="#e6c800" stroke-width="1"/>']
    for k, (c, t) in enumerate((("#d61f1f", "R"), ("#e6c800", "Y"), ("#1f9e1f", "G"))):
        out.append(f'<circle cx="{x:.1f}" cy="{y + k * 14:.1f}" r="5.2" fill="#fff" stroke="{c}" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{y + k * 14 + 3.2:.1f}" font-size="8" text-anchor="middle" fill="{c}" '
                   f'font-family="sans-serif">{t}</text>')
    return "".join(out), (x - 9, y - 9, x + 9, y + 37)


# ---------------------------------------------------------------- resolution
def road_of(code):
    code = str(code or "")
    for rd, codes in ROAD_CODES.items():
        if code and code in codes:
            return rd
    if not code and UNNAMED:
        return UNNAMED
    return None


def leg_of(code):
    """The specific leg a road code names, where it names one."""
    code = str(code or "")
    if not code:
        if UNNAMED:
            return APPROACH[ROAD_APPS[UNNAMED][0]][0]
        return None
    hits = [k for k in ORDER if code in set(str(c) for c in SPEC["legs"][k].get("codes", []))]
    return hits[0] if len(hits) == 1 else None


def cross_of(road):
    if road != MAIN:
        return MAIN
    for r in ROADS:
        if r != MAIN and r != UNNAMED:
            return r
    return UNNAMED or MAIN


def best_app(direction, roads, exclude=()):
    """Nearest approach (by coded inbound heading) among the roads'
    approaches for a coded direction; returns (app, misfit)."""
    h = DIR.get(direction)
    best = None
    for rd in roads:
        for app in ROAD_APPS.get(rd, []):
            if app in exclude:
                continue
            hd = APPROACH[app][1]
            m = adiff(h, hd) if h is not None else 60.0
            if best is None or m < best[1]:
                best = (app, m)
    return best


def app_road(app):
    return ROAD_OF_LEG[APPROACH[app][0]]


def opposite(app):
    apps = ROAD_APPS[app_road(app)]
    if len(apps) == 2:
        return apps[1] if apps[0] == app else apps[0]
    return None


def app_leg(app):
    return LEGS[APPROACH[app][0]]


def resolve(cr):
    """Assign every unit an approach. Returns (approach keys, turner index)."""
    r_on = road_of(cr.on_road) or MAIN
    r_from = road_of(cr.from_road)
    if r_from is None or r_from == r_on:
        r_from = cross_of(r_on)
        if not cr.from_road and UNNAMED and r_on != UNNAMED:
            r_from = UNNAMED
    units = cr.units
    typ = cr.acc_typ
    n = max(1, len(units))
    all_roads = list(ROADS)
    ms = [u.maneuver for u in units]
    turner = None
    cr.outbound = False
    if typ in (23, 24):
        turner = 0 if ms and ms[0] == 8 else (1 if len(ms) > 1 and ms[1] == 8 else (1 if typ == 23 else 0))
    elif typ in (25, 26):
        turner = 0 if ms and ms[0] == 7 else (1 if len(ms) > 1 and ms[1] == 7 else (1 if typ == 25 else 0))
    if typ == 30 and len(units) >= 2:
        a = best_app(units[0].direction, [r_on]), best_app(units[1].direction, [r_from])
        b = best_app(units[0].direction, [r_from]), best_app(units[1].direction, [r_on])
        pick = a if a[0][1] + a[1][1] <= b[0][1] + b[1][1] else b
        apps = [pick[0][0], pick[1][0]]
        if app_road(apps[0]) == app_road(apps[1]):
            other = [r for r in all_roads if r != app_road(apps[0])]
            apps[1] = best_app(units[1].direction, other)[0]
        for u in units[2:]:
            apps.append(best_app(u.direction, [r_on, r_from])[0])
        return apps, None
    if typ in (24, 26) and len(units) >= 2:
        t = turner
        ta, tm = best_app(units[t].direction, [r_on])
        if tm > 60:
            ta, tm = best_app(units[t].direction, all_roads)
        t_road = app_road(ta)
        o_roads = [r for r in (r_on, r_from) if r != t_road] or [r for r in all_roads if r != t_road]
        oa, om = best_app(units[1 - t].direction, o_roads, exclude=(ta,))
        if om > 75:
            oa, om = best_app(units[1 - t].direction, all_roads, exclude=(ta,))
        apps = [None, None]
        apps[t], apps[1 - t] = ta, oa
        for u in units[2:]:
            apps.append(best_app(u.direction, all_roads)[0])
        return apps, turner
    if typ in (23, 25) and len(units) >= 2:
        t = turner
        ta, tm = best_app(units[t].direction, [r_on])
        if tm > 50:
            ta, tm = best_app(units[t].direction, all_roads)
        opp = opposite(ta)
        oa, om = best_app(units[1 - t].direction, all_roads, exclude=(ta,))
        if typ == 23 and opp and adiff(DIR.get(units[1 - t].direction, APPROACH[opp][1]), APPROACH[opp][1]) <= 50:
            oa = opp
        if typ == 25:
            oa = ta                       # same roadway, same direction
        apps = [None, None]
        apps[t], apps[1 - t] = ta, oa
        for u in units[2:]:
            apps.append(oa)
        return apps, turner
    leg = leg_of(cr.on_road)
    if leg is None and len(ROAD_APPS.get(r_on, [])) > 1:
        votes = {}
        for u in units:
            app, m = best_app(u.direction, [r_on])
            votes[app] = votes.get(app, 0.0) + (90.0 - m)
        app = max(votes.items(), key=lambda kv: kv[1])[0] if votes else ROAD_APPS[r_on][0]
        if typ in (27, 29) and len(units) > 1:
            other = opposite(app)
            return [app] + [other] * (len(units) - 1), turner
        return [app] * n, turner
    if leg is None:
        leg = leg_of(cr.from_road) or APPROACH[ROAD_APPS[cross_of(r_on)][0]][0]
    app = f"{leg}_in"
    hin = APPROACH[app][1]
    out_votes = sum((1 if adiff(DIR.get(u.direction, hin), hin) > 90 else -1) for u in units)
    cr.outbound = out_votes > 0
    return [app] * n, turner


def leg_from_location(cr):
    """The leg and distance out a crash is coded on, from the fiche's
    from-road distance and direction. None when the crash is coded at
    the junction (or the from-road is not one of the junction's)."""
    if not cr.dist_mi or road_of(cr.from_road) is None or (not cr.from_road and not UNNAMED):
        return None
    ft = cr.dist_mi * 5280.0
    d = DIR.get((cr.dist_dir or "").upper())
    r_on = road_of(cr.on_road)
    if r_on is None or d is None:
        return None
    best = None
    for app in ROAD_APPS[r_on]:
        L = app_leg(app)
        m = adiff(d, L.b)
        if best is None or m < best[0]:
            best = (m, L.key)
    if best is None or best[0] > 70:
        return None
    return best[1], ft


def through_lanes(L):
    ks = [k for k in L.lanes_in if k.startswith("T")]
    return ks + [k for k in L.lanes_in if not k.startswith("T")]


def lane_line(app, lane):
    L = app_leg(app)
    n = L.lanes_in.get(lane, list(L.lanes_in.values())[0])
    return L.pt(L.stop, n), hv(L.hin)


def out_lane_line(leg_key, lane="T1"):
    L = LEGS[leg_key]
    n = L.lanes_out.get(lane, list(L.lanes_out.values())[0])
    return L.pt(L.stop, n), L.out


def turn_target(app, side, cr):
    """Leg a turn from ``app`` exits on: the leg whose bearing is nearest
    a 90 degree turn to that side from the inbound heading; the road the
    fiche names (from-road, else on-road) breaks near ties."""
    own = APPROACH[app][0]
    h = LEGS[own].hin
    want = road_of(cr.from_road)
    if want == ROAD_OF_LEG[own]:
        want = road_of(cr.on_road)
    best = None
    for k, L in LEGS.items():
        if k == own:
            continue
        turn = (L.b - h + 180.0) % 360.0 - 180.0
        if side == "R" and not (20 <= turn <= 160):
            continue
        if side == "L" and not (-160 <= turn <= -20):
            continue
        score = abs(abs(turn) - 90.0) - (25.0 if want and ROAD_OF_LEG[k] == want else 0.0)
        if best is None or score < best[0]:
            best = (score, k)
    if best is None:
        i = ORDER.index(own)
        return ORDER[(i - 1) % len(ORDER)] if side == "R" else ORDER[(i + 1) % len(ORDER)]
    return best[1]


class PathPts(list):
    def __init__(self, pts, arc_mid):
        super().__init__(pts)
        self.arc_mid = arc_mid


def turn_path(app, lane, exit_leg, side, exit_lane=None):
    """Path of a turn: the approach lane from the stop bar, a fillet arc,
    the exit lane out to 80 ft."""
    L = app_leg(app)
    Lx = LEGS[exit_leg]
    p0, d = lane_line(app, lane)
    if exit_lane is None:
        outs = sorted(Lx.lanes_out.items(), key=lambda kv: kv[1])
        exit_lane = outs[0][0] if side == "L" else outs[-1][0]
    q0, e = out_lane_line(exit_leg, exit_lane)
    X = line_x(p0, d, q0, e)
    if X is None:
        return PathPts([p0, add(p0, d, 60)], add(p0, d, 30))
    ang = math.acos(max(-1.0, min(1.0, dot((-d[0], -d[1]), e))))
    ta = dot(add(X, p0, -1.0), d)
    tb = dot(add(q0, X, -1.0), e)
    r = min(60.0, max(8.0, min(ta, tb) * math.tan(ang / 2.0)))
    dd = r / math.tan(ang / 2.0)
    T1 = add(X, d, -dd)
    T2 = add(X, e, dd)
    bis = (-d[0] + e[0], -d[1] + e[1])
    bl = math.hypot(*bis) or 1.0
    bis = (bis[0] / bl, bis[1] / bl)
    C = add(X, bis, r / math.sin(ang / 2.0))
    a0 = math.atan2(T1[1] - C[1], T1[0] - C[0])
    a1 = math.atan2(T2[1] - C[1], T2[0] - C[0])
    while a1 - a0 > math.pi:
        a1 -= 2 * math.pi
    while a1 - a0 < -math.pi:
        a1 += 2 * math.pi
    arc = [(C[0] + r * math.cos(a0 + (a1 - a0) * k / 24),
            C[1] + r * math.sin(a0 + (a1 - a0) * k / 24)) for k in range(25)]
    return PathPts([p0] + arc + [add(T2, e, 80)], arc[12])


def poly_x_line(pts, q, e, min_t=None):
    nrm = (-e[1], e[0])
    for i in range(len(pts) - 1):
        s0 = dot(add(pts[i], q, -1.0), nrm)
        s1 = dot(add(pts[i + 1], q, -1.0), nrm)
        if s0 == s1:
            continue
        if (s0 <= 0 <= s1) or (s1 <= 0 <= s0):
            f = s0 / (s0 - s1)
            p = (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f,
                 pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f)
            if min_t is not None and dot(add(p, q, -1.0), e) < min_t:
                continue
            tan = (pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            tl = math.hypot(*tan) or 1.0
            return p, (tan[0] / tl, tan[1] / tl)
    return None, None


def along_path(pts, s):
    acc = 0.0
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if acc + seg >= s or i == len(pts) - 2:
            f = 0.0 if seg == 0 else min(max((s - acc) / seg, 0.0), 1.0)
            t = ((pts[i + 1][0] - pts[i][0]) / (seg or 1), (pts[i + 1][1] - pts[i][1]) / (seg or 1))
            return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f,
                    pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f), t
        acc += seg
    return pts[-1], (1.0, 0.0)


def tangent_heading(v):
    return math.degrees(math.atan2(v[0], v[1])) % 360.0


def on_travel_side(p, heading, slack=1.0):
    """True when ground point p is in the junction box or on a leg's
    lanes for that direction of travel: a unit heading in on a leg sits
    on its approach side of the median or centreline, a unit heading out
    on its departure side."""
    if not on_pavement(p, slack):
        return False
    if math.hypot(*p) < BOX_R:
        return True
    for L in LEGS.values():
        a, n = L.frame(p)
        lo = min(getattr(L, "curb_in", L.in_edge), L.in_edge) - slack
        hi = L.out_edge + slack
        if a < 0 or not (lo <= n <= hi):
            continue
        med = getattr(L, "median", None)
        c = getattr(L, "centre", None)
        split_in = med[0] if med else (c if c is not None else 0.0)
        split_out = med[1] if med else (c if c is not None else 0.0)
        if adiff(heading, L.hin) <= 90:
            return n <= split_in + 2.0
        return n >= split_out - 2.0
    return False


def on_pavement(p, slack=1.0):
    """True when ground point p lies on the drawn pavement: inside the
    curb loop where the spec draws one, else inside a leg's curb-to-curb
    band or within the junction box."""
    loop = pavement_polygon()
    if len(loop) >= 3:
        return _inside(p, loop)
    if math.hypot(*p) < BOX_R:
        return True
    for L in LEGS.values():
        a, n = L.frame(p)
        lo = min(getattr(L, "curb_in", L.in_edge), L.in_edge) - slack
        hi = L.out_edge + slack
        if a >= 0 and lo <= n <= hi:
            return True
    return False


# ---------------------------------------------------------------- collision
def _d_ps(p, a, b):
    ab = (b[0] - a[0], b[1] - a[1])
    L2 = ab[0] ** 2 + ab[1] ** 2
    if L2 == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / L2))
    return math.hypot(p[0] - a[0] - t * ab[0], p[1] - a[1] - t * ab[1])


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _x_segs(p1, p2, q1, q2):
    d1, d2 = _orient(q1, q2, p1), _orient(q1, q2, p2)
    d3, d4 = _orient(p1, p2, q1), _orient(p1, p2, q2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


def _seg_seg(p1, p2, q1, q2):
    if _x_segs(p1, p2, q1, q2):
        return 0.0
    return min(_d_ps(p1, q1, q2), _d_ps(p2, q1, q2), _d_ps(q1, p1, p2), _d_ps(q2, p1, p2))


def _inside(p, pts):
    x, y = p
    n = len(pts)
    ins = False
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if xi > x:
                ins = not ins
    return ins


def gap(a, b):
    """Clear distance between two primitives (negative when they overlap).
    ("s", p, q, hw) is a stroked segment, ("d", c, r) a disc, ("p", pts) a
    filled polygon."""
    ka, kb = a[0], b[0]
    if ka == "p" and kb == "p":
        pa, pb = a[1], b[1]
        if any(_inside(p, pb) for p in pa) or any(_inside(p, pa) for p in pb):
            return -1.0
        return min(_seg_seg(pa[i], pa[(i + 1) % len(pa)], pb[j], pb[(j + 1) % len(pb)])
                   for i in range(len(pa)) for j in range(len(pb)))
    if ka == "p":
        return gap(b, a)
    if kb == "p":
        pts = b[1]
        if ka == "s":
            if _inside(a[1], pts) or _inside(a[2], pts):
                return -1.0
            return min(_seg_seg(a[1], a[2], pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))) - a[3]
        if _inside(a[1], pts):
            return -1.0
        return min(_d_ps(a[1], pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))) - a[2]
    if ka == "s" and kb == "s":
        return _seg_seg(a[1], a[2], b[1], b[2]) - a[3] - b[3]
    if ka == "s":
        return _d_ps(b[1], a[1], a[2]) - a[3] - b[2]
    if kb == "s":
        return _d_ps(a[1], b[1], b[2]) - a[2] - b[3]
    return math.hypot(a[1][0] - b[1][0], a[1][1] - b[1][1]) - a[2] - b[2]


def prim_bbox(p):
    if p[0] == "s":
        return (min(p[1][0], p[2][0]) - p[3], min(p[1][1], p[2][1]) - p[3],
                max(p[1][0], p[2][0]) + p[3], max(p[1][1], p[2][1]) + p[3])
    if p[0] == "d":
        return (p[1][0] - p[2], p[1][1] - p[2], p[1][0] + p[2], p[1][1] + p[2])
    xs = [q[0] for q in p[1]]
    ys = [q[1] for q in p[1]]
    return (min(xs), min(ys), max(xs), max(ys))


def prims_bbox(prims):
    bs = [prim_bbox(p) for p in prims]
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


class Cell:
    """A drawn crash: svg, primitives (page px) and the flags that exempt
    some of them from linework tests (a departure leg leaves the road)."""

    def __init__(self, cr, svg, prims, exempt=()):
        self.cr = cr
        self.svg = svg
        self.prims = prims                 # [(prim, exempt_flag)]
        self.exempt = set(exempt)          # obstacle kinds every primitive may touch
        self.bbox = prims_bbox([p for p, _ in prims])
        self.tag = ""

    def shifted(self, dx, dy):
        def mv(p):
            if p[0] == "s":
                return ("s", (p[1][0] + dx, p[1][1] + dy), (p[2][0] + dx, p[2][1] + dy), p[3])
            if p[0] == "d":
                return ("d", (p[1][0] + dx, p[1][1] + dy), p[2])
            return ("p", [(x + dx, y + dy) for x, y in p[1]])
        c = Cell(self.cr, f'<g transform="translate({dx:.1f},{dy:.1f})">{self.svg}</g>',
                 [(mv(p), f) for p, f in self.prims], self.exempt)
        c.tag = self.tag
        return c


class Scene:
    """Everything on the sheet a cell must keep clear of."""

    def __init__(self, obstacles, margin=30.0):
        self.obs = []                      # (kind, prim)
        self.obb = []                      # bboxes
        self.cells = []
        self.cbb = []
        self.margin = margin
        for kind, prim in obstacles:
            self.add_obstacle(kind, prim)
        self._arr = None

    def add_obstacle(self, kind, prim):
        self.obs.append((kind, prim))
        self.obb.append(prim_bbox(prim))
        self._arr = None

    def add_rect(self, kind, r):
        self.add_obstacle(kind, ("p", [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]))

    def add_cell(self, cell):
        self.cells.append(cell)
        self.cbb.append(cell.bbox)

    def _obs_near(self, bb, pad):
        if self._arr is None or len(self._arr) != len(self.obb):
            self._arr = np.array(self.obb, dtype=float).reshape(-1, 4)
        if not len(self._arr):
            return []
        a = self._arr
        m = (a[:, 0] < bb[2] + pad) & (a[:, 2] > bb[0] - pad) & (a[:, 1] < bb[3] + pad) & (a[:, 3] > bb[1] - pad)
        return np.nonzero(m)[0]

    def free(self, cell, clear_cell=CLEAR_CELL, clear_obs=CLEAR_OBS, soft=()):
        """True when the cell keeps clear of everything placed; obstacle
        kinds in ``soft`` are ignored."""
        bb = cell.bbox
        m = self.margin
        if not (m < bb[0] and bb[2] < cd.PAGE_W - m and m < bb[1] and bb[3] < cd.PAGE_H - m):
            return False
        for i in self._obs_near(bb, clear_obs):
            kind, prim = self.obs[i]
            if kind in cell.exempt or kind in soft:
                continue
            need = 0.5 if kind == "edge" else clear_obs
            for p, ex in cell.prims:
                if ex and kind in ("edge", "cw", "stop", "island"):
                    continue
                if gap(p, prim) < need:
                    return False
        for other, obb in zip(self.cells, self.cbb):
            if not (obb[0] < bb[2] + clear_cell and obb[2] > bb[0] - clear_cell
                    and obb[1] < bb[3] + clear_cell and obb[3] > bb[1] - clear_cell):
                continue
            for p, _ in cell.prims:
                for q, _ in other.prims:
                    if gap(p, q) < clear_cell:
                        return False
        return True

    def free_rect(self, r, clear=4.0):
        c = Cell(None, "", [(("p", [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]), False)])
        return self.free(c, clear, clear)


# ---------------------------------------------------------------- cell drawing
def _shaft():
    return cd.CELL_SHAFT * CS


def unit_svg(tip, heading, unit, night, kind="straight", exit_heading=None,
             shaft=None, zigzag=False, kink=0.0):
    """One unit ending at ``tip`` (page px) travelling ``heading``
    (compass). Returns (svg, tail, prims) where prims are [(prim, exempt)]
    and the leg past a run-off-road break is exempt from the curb test."""
    shaft = shaft or _shaft()
    ang = page_ang(heading)
    a = math.radians(ang)
    c, s = math.cos(a), math.sin(a)
    hw = 1.2
    if kind == "hook" and exit_heading is not None and adiff(exit_heading, heading) > 8:
        a2 = math.radians(page_ang(exit_heading))
        c2, s2 = math.cos(a2), math.sin(a2)
        hook = 15.0 * CS
        S = (tip[0] - hook * c2 - hook * c, tip[1] - hook * s2 - hook * s)
        Cp = (S[0] + hook * c, S[1] + hook * s)
        tail = (S[0] - (shaft - 2 * hook) * c, S[1] - (shaft - 2 * hook) * s)
        svg = [f'<path d="M {tail[0]:.1f},{tail[1]:.1f} L {S[0]:.1f},{S[1]:.1f} '
               f'Q {Cp[0]:.1f},{Cp[1]:.1f} {tip[0]:.1f},{tip[1]:.1f}" fill="none" '
               f'stroke="#000" stroke-width="{cd.CELL_SW}"/>']
        run = math.hypot(S[0] - tail[0], S[1] - tail[1])
        svg.append(cd._speed_run(tail[0], tail[1], c, s, 2.0, run - 2.0, unit.speed))
        svg.append(cd._arrowhead(tip[0], tip[1], a2, night))
        mid = (0.25 * S[0] + 0.5 * Cp[0] + 0.25 * tip[0], 0.25 * S[1] + 0.5 * Cp[1] + 0.25 * tip[1])
        prims = [(("s", tail, S, hw), False), (("s", S, mid, hw), False), (("s", mid, tip, hw), False),
                 (("d", tip, 3.6), False)]
        return "".join(svg), tail, prims
    tail = (tip[0] - shaft * c, tip[1] - shaft * s)
    svg, tip2, ink = cd._unit_cell(tail[0], tail[1], ang, unit, night, zigzag=zigzag,
                                   shaft=shaft, kink=kink)
    prims = []
    depart = bool(zigzag or kink)
    for i in range(len(ink) - 1):
        # the stretch past the break is the departure: it may leave the road
        ex = depart and i >= len(ink) - 2
        prims.append((("s", ink[i], ink[i + 1], hw), ex))
    prims.append((("d", tip2, 3.6), depart))
    return "".join(svg), tail, prims


def decor(tail, heading, cr):
    """Badge, at-fault asterisk and surface letter on one tail."""
    a = math.radians(page_ang(heading))
    c, s = math.cos(a), math.sin(a)
    lx, ly = s, -c
    br = cd.BUBBLE_R + (2.0 if len(str(cr.seq)) > 1 else 0.0)
    bx, by = tail[0] - (br + 1.0) * c, tail[1] - (br + 1.0) * s
    out = cd._badge(bx, by, cr.seq)
    ds, dn = cd.DECOR_S * CS, cd.DECOR_N * CS + 0.5
    sx, sy = tail[0] + ds * c + dn * lx, tail[1] + ds * s + dn * ly
    out += cd._stroke_text(sx, sy + 1.5, "*", size=11, color=cd.MAGENTA, sw=1.0)
    cx_, cy_ = tail[0] + ds * c - dn * lx, tail[1] + ds * s - dn * ly
    out += cd._stroke_text(cx_, cy_, cr.road_cond, size=8, color=cd.GREEN)
    prims = [(("d", (bx, by), br + 1.0), False), (("d", (sx, sy), 4.0), False), (("d", (cx_, cy_), 4.0), False)]
    return out, prims


def sev(tip, heading, cr):
    a = math.radians(page_ang(heading))
    x, y = tip[0] + cd.SEV_GAP * CS * math.cos(a), tip[1] + cd.SEV_GAP * CS * math.sin(a)
    if cr.severity in ("O", ""):
        return "", []
    return cd._severity_circle(x, y, cr.severity), [(("d", (x, y), cd.SEV_R + 1.0), False)]


def tick(p, heading):
    a = page_ang(heading)
    r = math.radians(a)
    nx, ny = -math.sin(r) * cd.TICK_H, math.cos(r) * cd.TICK_H
    return cd._impact_tick(p[0], p[1], a), [(("s", (p[0] - nx, p[1] - ny), (p[0] + nx, p[1] + ny), 0.8), False)]


def cell_single(cr, X, heading, tag=""):
    """A one-unit cell: run off road, fixed object, parked vehicle, animal,
    with the tip (point of rest or impact) at ground X."""
    u, typ, night = cr.units, cr.acc_typ, cr.night
    tipx = page(X)
    depart = typ in cd.ROR_TYPES or typ == 19
    side = {1: 1, 2: -1, 3: 0}.get(typ, 1)
    kink = side * cd.DEPART_KINK if depart else 0.0
    svg, tail, prims = unit_svg(tipx, heading, u[0] if u else cd.Unit(1), night, zigzag=depart, kink=kink)
    a = math.radians(page_ang(heading + (kink if depart else 0)))
    ca, sa = math.cos(a), math.sin(a)
    tip = tipx
    if typ == 18:
        ox, oy = tip[0] + 8 * ca, tip[1] + 8 * sa
        svg += (f'<rect x="{ox - 4:.1f}" y="{oy - 4:.1f}" width="8" height="8" fill="none" '
                f'stroke="#000" stroke-width="{cd.CELL_SW}" stroke-dasharray="2 1.6"/>')
        prims.append((("d", (ox, oy), 6.0), False))
        tip = (ox + 4 * ca, oy + 4 * sa)
    elif typ == 20:
        for _ in u[1:3] or [None]:
            ox, oy = tip[0] + 9 * ca, tip[1] + 9 * sa
            svg += (f'<rect x="{ox - 5:.1f}" y="{oy - 3:.1f}" width="10" height="6" fill="none" '
                    f'stroke="#000" stroke-width="{cd.CELL_SW}" '
                    f'transform="rotate({page_ang(heading):.1f} {ox:.1f} {oy:.1f})"/>')
            prims.append((("d", (ox, oy), 6.0), False))
            tip = (ox + 4 * ca, oy + 4 * sa)
    elif typ in (14, 15, 16, 17):
        ox, oy = tip[0] + 9 * ca, tip[1] + 9 * sa
        svg += cd._mode_mark(ox, oy, {14: "P", 15: "B", 16: "T", 17: "A"}[typ], h=10)
        prims.append((("d", (ox, oy), 6.0), False))
        tip = (ox + 4 * ca, oy + 4 * sa)
    s, sp = sev((tip[0] + 3 * ca, tip[1] + 3 * sa), heading + (kink if depart else 0), cr)
    d, dp = decor(tail, heading, cr)
    if depart:
        sp = [(p, True) for p, _ in sp]
    c = Cell(cr, svg + s + d, prims + sp + dp, exempt=("cw", "stop") if typ in (14, 15) else ())
    c.tag = tag
    return c


def cell_queue(cr, X, hq, lat_dir, tag=""):
    """Rear end (leader ahead, follower behind, impact tick), backing or
    same-direction sideswipe with the leader's tip at ground X. ``lat_dir``
    is the ground vector the sideswipe's second unit is offset along."""
    u, typ, night = cr.units, cr.acc_typ, cr.night
    tip = page(X)
    a = math.radians(page_ang(hq))
    if typ == 28:
        s1, tail1, prims = unit_svg(tip, hq, u[0], night)
        tip2 = page(add(add(X, lat_dir, 4.5), hv(hq), -1.5))
        s2, tail2, p2 = unit_svg(tip2, hq, u[1], night)
        sv, sp = sev(tip, hq, cr)
        d, dp = decor(tail1, hq, cr)
        c = Cell(cr, s1 + s2 + sv + d, prims + p2 + sp + dp)
        c.tag = tag
        return c
    if typ == 31:                                        # backing: leader reversing into the follower
        s2, tail2, prims = unit_svg(tip, hq + 180, u[1], night)
        imp = (tail2[0] + 0.8 * math.cos(a), tail2[1] + 0.8 * math.sin(a))
        s1, tail1, p1 = unit_svg(imp, hq, u[0], night)
        t, tp = tick(imp, hq)
        sv, sp = sev(tip, hq, cr)
        d, dp = decor(tail1, hq, cr)
        c = Cell(cr, s1 + s2 + t + sv + d, prims + p1 + tp + sp + dp)
        c.tag = tag
        return c
    s2, tail2, prims = unit_svg(tip, hq, u[1], night)
    imp = (tail2[0] - 0.8 * math.cos(a), tail2[1] - 0.8 * math.sin(a))
    s1, tail1, p1 = unit_svg(imp, hq, u[0], night)
    t, tp = tick(imp, hq)
    sv, sp = sev(tip, hq, cr)
    d, dp = decor(tail1, hq, cr)
    c = Cell(cr, s1 + s2 + t + sv + d, prims + p1 + tp + sp + dp)
    c.tag = tag
    return c


def cell_headon(cr, X, h1, tag=""):
    u, typ, night = cr.units, cr.acc_typ, cr.night
    mid = page(X)
    a = math.radians(page_ang(h1))
    ca, sa = math.cos(a), math.sin(a)
    lx, ly = sa, -ca
    if typ == 27:
        tip1 = (mid[0] - 1.5 * ca, mid[1] - 1.5 * sa)
        tip2 = (mid[0] + 1.5 * ca, mid[1] + 1.5 * sa)
        s1, tail1, prims = unit_svg(tip1, h1, u[0], night)
        s2, tail2, p2 = unit_svg(tip2, h1 + 180, u[1], night)
        t, tp = tick(mid, h1)
        px_, py_ = mid[0] + lx * 8, mid[1] + ly * 8
        sv = cd._severity_circle(px_, py_, cr.severity)
        sp = [(("d", (px_, py_), cd.SEV_R + 1.0), False)] if sv else []
        d, dp = decor(tail1, h1, cr)
        c = Cell(cr, s1 + s2 + t + sv + d, prims + p2 + tp + sp + dp)
    else:
        half = cd.LANE_SEP * CS / 2
        tip1 = (mid[0] + lx * half + 18 * ca, mid[1] + ly * half + 18 * sa)
        tip2 = (mid[0] - lx * half - 18 * ca, mid[1] - ly * half - 18 * sa)
        s1, tail1, prims = unit_svg(tip1, h1, u[0], night)
        s2, tail2, p2 = unit_svg(tip2, h1 + 180, u[1], night)
        sv, sp = sev(tip1, h1, cr)
        d, dp = decor(tail1, h1, cr)
        c = Cell(cr, s1 + s2 + sv + d, prims + p2 + sp + dp)
    c.tag = tag
    return c


def cell_angle(cr, X, h1, h2, tag=""):
    """Angle: unit 1's shaft runs through the impact, unit 2's head stops
    at its side (deck page 26). X is the impact point."""
    u, night = cr.units, cr.night
    shaft = _shaft()
    a1 = math.radians(page_ang(h1))
    Xp = page(X)
    tip1 = (Xp[0] + 0.62 * shaft * math.cos(a1), Xp[1] + 0.62 * shaft * math.sin(a1))
    s1, tail1, prims = unit_svg(tip1, h1, u[0], night)
    tip2 = page(add(X, hv(h2), -(3.5 / PX)))
    s2, tail2, p2 = unit_svg(tip2, h2, u[1], night, shaft=shaft - 12)
    sv, sp = sev(tip1, h1, cr)
    d, dp = decor(tail1, h1, cr)
    c = Cell(cr, s1 + s2 + sv + d, prims + p2 + sp + dp)
    c.tag = tag
    return c


def cell_turn(cr, X, spec, tag=""):
    """A turning cell with its conflict point at ground X."""
    u, typ, night = cr.units, cr.acc_typ, cr.night
    t_h, o_hd, exit_h, turner = spec["t_h"], spec["o_hd"], spec["exit_h"], spec["turner"]
    t_unit, o_unit = u[turner], u[1 - turner]
    tipx = page(X)
    if typ == 25:
        lat = spec["lat"]
        po = add(add(X, lat, 4.0), hv(o_hd), -(3 / PX))
    else:
        po = add(X, hv(o_hd), -(4 / PX))
    st, tailt, prims = unit_svg(tipx, t_h, t_unit, night, kind="hook", exit_heading=exit_h)
    so, tailo, po_ = unit_svg(page(po), o_hd, o_unit, night,
                              shaft=_shaft() - (8 if typ != 25 else 0))
    if turner == 0:
        sv, sp = sev(tipx, exit_h, cr)
        d, dp = decor(tailt, t_h, cr)
    else:
        sv, sp = sev(page(po), o_hd, cr)
        d, dp = decor(tailo, o_hd, cr)
    c = Cell(cr, st + so + sv + d, prims + po_ + sp + dp)
    c.tag = tag
    return c


# ---------------------------------------------------------------- placement
def _slots(band_lo, band_hi, prefer):
    """Lateral stations across an approach, nearest the preferred lane first."""
    lo, hi = band_lo - 1.5, band_hi + 1.5
    n = max(1, int(round((hi - lo) / QUEUE_PITCH)))
    pitch = (hi - lo) / n if n else 0.0
    vals = [lo + k * pitch for k in range(n + 1)]
    return sorted(vals, key=lambda v: abs(v - prefer))


def _nest_order(imax=12, jmax=8):
    """Grid offsets (i back along the travel line, j across it), nearest
    first; a tie goes to the cell behind and outside, the way the sheets
    nest a stack back from its conflict point."""
    pts = [(i, j) for i in range(-imax, imax + 1) for j in range(-jmax, jmax + 1)]
    return sorted(pts, key=lambda ij: (round(math.hypot(ij[0], ij[1]), 3), -ij[0], -ij[1]))


class Item:
    def __init__(self, cr, group, build, candidates, anchor, where, fwd=(0.0, 1.0), stack="diag"):
        self.cr = cr
        self.group = group             # inset grouping key
        self.build = build             # X -> Cell
        self.candidates = candidates   # iterable of ground X
        self.anchor = anchor           # ground point the inset marker points at
        self.where = where             # description for the review csv
        self.fwd = fwd                 # ground unit vector of the cell's travel line
        self.stack = stack             # how an inset stacks the group: lateral or diag


def plan(crashes):
    """One Item per crash: how to draw it and where it may go."""
    items = []
    loads = {}
    for cr in crashes:
        apps, turner = resolve(cr)
        u = cr.units
        typ = cr.acc_typ
        a1 = apps[0]
        L1 = app_leg(a1)
        m1 = u[0].maneuver if u else None
        m2 = u[1].maneuver if len(u) > 1 else None
        loc = leg_from_location(cr)
        single = len(u) < 2 or typ in cd.SINGLE_UNIT_TYPES

        def lane_pref(L, outbound=False):
            lanes = L.lanes_out if outbound else L.lanes_in
            if not outbound and (m1 == 8 or m2 == 8) and "L" in lanes:
                return lanes["L"]
            if not outbound and (m1 == 7 or m2 == 7) and "R" in lanes:
                return lanes["R"]
            ths = [k for k in lanes if k.startswith("T")] or list(lanes)
            k = min(ths, key=lambda k: (loads.get((L.key, outbound, k), 0), k))
            loads[(L.key, outbound, k)] = loads.get((L.key, outbound, k), 0) + 1
            return lanes[k]

        # ------------------------------------------------ coded away from the junction
        # a rear end coded a short way back on its own approach is part of
        # the stop-bar queue; anything else coded out a leg is placed there
        reach = float(SPEC.get("queue_reach", 150.0))
        fold = (loc and typ in (21, 22, 28, 31) and not single and loc[1] < reach
                and loc[0] == L1.key and not cr.outbound)
        if loc and loc[1] >= 60 and not fold:
            key_leg, ft = loc
            L = LEGS[key_leg]
            outbound = adiff(DIR.get(u[0].direction, L.hin), L.hin) > 90 if u else False
            hq = L.b if outbound else L.hin
            lanes = L.lanes_out if outbound else L.lanes_in
            band = sorted(lanes.values())
            lat = (L.right[0], L.right[1]) if outbound else (-L.right[0], -L.right[1])
            if single:
                edge = L.out_edge if outbound else L.in_edge
                pref = edge - 5.0 if outbound else edge + 5.0
                build = lambda X, cr=cr, L=L, hq=hq: cell_single(cr, X, hq, "")      # noqa: E731
            elif typ in (21, 22, 28, 31):
                pref = lane_pref(L, outbound)
                build = lambda X, cr=cr, L=L, hq=hq, lat=lat: cell_queue(cr, X, hq, lat)  # noqa: E731
            elif typ in (27, 29):
                c = getattr(L, "centre", None)
                pref = c if c is not None else (L.median[0] - 1.5 if getattr(L, "median", None) else 0.0)
                build = lambda X, cr=cr, hq=hq: cell_headon(cr, X, hq)              # noqa: E731
            elif typ in (23, 24, 25, 26) and turner is not None:
                side = "L" if typ in (23, 24) else "R"
                t_h = hq
                exit_h = t_h + (-80.0 if side == "L" else 80.0)
                o_hd = hq if typ in (25, 26, 23) else hq + 180.0
                pref = band[-1] if (side == "L") == outbound else band[0]
                spec = {"t_h": t_h, "o_hd": o_hd, "exit_h": exit_h, "turner": turner,
                        "lat": (-lat[0], -lat[1])}
                build = lambda X, cr=cr, spec=spec: cell_turn(cr, X, spec)          # noqa: E731
            else:
                h2 = DIR.get(u[1].direction, hq + 90) if len(u) > 1 else hq + 90
                if adiff(h2, hq) < 30:
                    h2 = hq + 90
                pref = band[0]
                build = lambda X, cr=cr, hq=hq, h2=h2: cell_angle(cr, X, hq, h2)    # noqa: E731
            slots = _slots(min(band[0], pref), max(band[-1], pref), pref)
            cands = [L.pt(ft + sh, n) for sh in (0, 8, -8, 16, -16, 24, -24, 32, -32, 40, -40, 48, -48, 56, -56, 64, -64)
                     for n in slots]
            items.append(Item(cr, ("remote", key_leg), build, cands, L.pt(ft, pref),
                              f"{key_leg} {'out' if outbound else 'in'} at {ft:.0f} ft",
                              fwd=hv(hq), stack="lateral" if typ in (21, 22, 28, 31) or single else "diag"))
            continue

        # ------------------------------------------------ single unit types
        if single:
            L = L1
            outbound = bool(cr.outbound)
            heading = L.b if outbound else L.hin
            if typ in (14, 15) and L.cw:
                c0, c1 = L.cw
                lanes = sorted(L.lanes_in.values())
                pref = lanes[min(1, len(lanes) - 1)]
                slots = _slots(lanes[0], lanes[-1], pref)
                cands = [L.pt((c0 + c1) / 2 + 2 + sh, n) for sh in (0, 10, 20, 30) for n in slots]
                items.append(Item(cr, ("cw", L.key), lambda X, cr=cr, L=L, h=heading: cell_single(cr, X, h),
                                  cands, L.pt((c0 + c1) / 2, pref), f"{a1} crosswalk",
                                  fwd=hv(heading), stack="lateral"))
                continue
            edge = L.out_edge if outbound else getattr(L, "curb_in", L.in_edge)
            inner = L.out_edge if outbound else L.in_edge
            shoulder = (edge + inner) / 2 if abs(edge - inner) >= 6 else (edge - 5 if outbound else edge + 5)
            lanes = sorted((L.lanes_out if outbound else L.lanes_in).values())
            ns = [shoulder] + (lanes[::-1] if outbound else lanes)
            start = L.cw[1] + 6 if (outbound and L.cw) else L.stop + 14
            cands = [L.pt(start + k * ALONG_STEP, n) for k in range(0, 40) for n in ns]
            items.append(Item(cr, ("shoulder", L.key, outbound),
                              lambda X, cr=cr, L=L, h=heading: cell_single(cr, X, h),
                              cands, L.pt(start + 10, shoulder), f"{L.key} shoulder",
                              fwd=hv(heading), stack="lateral"))
            continue

        # ------------------------------------------------ rear end, sideswipe same way
        if typ in (21, 22, 28, 31):
            L = L1
            outbound = bool(cr.outbound)
            hq = L.b if outbound else L.hin
            lanes = L.lanes_out if outbound else L.lanes_in
            band = sorted(lanes.values())
            pref = lane_pref(L, outbound)
            slots = _slots(band[0], band[-1], pref)
            lat = (L.right[0], L.right[1]) if outbound else (-L.right[0], -L.right[1])
            start = (L.cw[1] + 4.0 if L.cw else L.stop + 4.0) if outbound else L.stop + 5.0
            cands = [L.pt(start + k * ALONG_STEP, n) for k in range(0, 40) for n in slots]
            items.append(Item(cr, ("queue", L.key, outbound),
                              lambda X, cr=cr, hq=hq, lat=lat: cell_queue(cr, X, hq, lat),
                              cands, L.pt(start + 20, pref), f"queue {a1}{' out' if outbound else ''}",
                              fwd=hv(hq), stack="lateral"))
            continue

        # ------------------------------------------------ head on / opposite sideswipe
        if typ in (27, 29):
            L = L1
            c = getattr(L, "centre", None)
            if c is None:
                c = L.median[0] - 1.5 if getattr(L, "median", None) else 0.0
            h1 = L.hin
            cands = [L.pt(L.stop + 28 + k * ALONG_STEP, c + dn) for k in range(0, 24) for dn in (0, -8, 8)]
            items.append(Item(cr, ("centre", L.key), lambda X, cr=cr, h1=h1: cell_headon(cr, X, h1),
                              cands, L.pt(L.stop + 40, c), f"{L.key} centreline",
                              fwd=hv(h1), stack="lateral"))
            continue

        # ------------------------------------------------ angle and turning
        a2 = apps[1] if len(apps) > 1 else opposite(a1) or a1
        h1, h2 = L1.hin, app_leg(a2).hin
        side = "L" if typ in (23, 24) else ("R" if typ in (25, 26) else None)
        if turner is None or side is None:
            l1 = through_lanes(L1)
            l2 = through_lanes(app_leg(a2))
            p1, d1 = lane_line(a1, l1[0])
            p2, d2 = lane_line(a2, l2[0])
            X0 = line_x(p1, d1, p2, d2)
            if X0 is None or math.hypot(*X0) > 80:
                X0 = add(p1, d1, 25)
            fwd = hv(h1)
            rt = (fwd[1], -fwd[0])
            cands = [add(add(X0, fwd, -i * NEST_STEP), rt, j * NEST_STEP) for i, j in _nest_order()]
            cands = [X for X in cands if on_travel_side(X, h1)]
            items.append(Item(cr, ("angle", a1, a2), lambda X, cr=cr, h1=h1, h2=h2: cell_angle(cr, X, h1, h2),
                              cands, X0, f"angle {a1} {a2}", fwd=hv(h1)))
            continue
        t_app = apps[turner]
        o_app = apps[1 - turner]
        L = app_leg(t_app)
        t_h, o_h = L.hin, app_leg(o_app).hin
        lane = "L" if side == "L" and "L" in L.lanes_in else ("R" if side == "R" and "R" in L.lanes_in else
                                                             list(L.lanes_in)[-1 if side == "R" else 0])
        exit_leg = turn_target(t_app, side, cr)
        path = turn_path(t_app, lane, exit_leg, side)
        Lx = LEGS[exit_leg]
        other_out = typ in (24, 26) and adiff(o_h, Lx.b) <= 45
        inb = hv(t_h)
        lat_out = (-inb[1], inb[0]) if side == "L" else (inb[1], -inb[0])   # away from the turn's inside
        if typ == 25:
            X0 = path.arc_mid
            tan = hv(t_h + 40.0 if side == "R" else t_h - 40.0)
            o_hd = o_h
        elif other_out:
            outs = sorted(Lx.lanes_out.items(), key=lambda kv: kv[1])
            p2, d2 = out_lane_line(exit_leg, outs[0][0] if side == "L" else outs[-1][0])
            o_hd = Lx.b
            # the merge sits where the turn is complete, kept short of the
            # exit leg's crosswalk so the cell stays in the junction
            lim = (Lx.cw[0] if Lx.cw else Lx.stop) - 3.0
            k = len(path) - 2
            while k > 1 and Lx.frame(path[k])[0] >= lim:
                k -= 1
            X0 = path[k]
            v = add(path[k + 1], path[k], -1.0)
            vl = math.hypot(*v) or 1.0
            tan = (v[0] / vl, v[1] / vl)
        else:
            l2 = through_lanes(app_leg(o_app))
            p2, d2 = lane_line(o_app, l2[0])
            o_hd = o_h
            nrm = (-d2[1], d2[0])
            X0, tan = None, None
            for i in range(1, len(path) - 1):
                if abs(dot(add(path[i], p2, -1.0), nrm)) < 6.0:
                    X0 = path[i]
                    v = add(path[i + 1], path[i], -1.0)
                    vl = math.hypot(*v) or 1.0
                    tan = (v[0] / vl, v[1] / vl)
                    break
            if X0 is None:
                X0, tan = poly_x_line(path, p2, d2, min_t=-8.0)
            if X0 is None:
                X0, tan = along_path(path, 45)
        exit_h = tangent_heading(tan)
        spec = {"t_h": t_h, "o_hd": o_hd, "exit_h": exit_h, "turner": turner, "lat": lat_out}
        fwd = inb
        rt = lat_out
        cands = [add(add(X0, fwd, -i * NEST_STEP), rt, j * NEST_STEP) for i, j in _nest_order()]
        cands = [X for X in cands if on_travel_side(X, t_h)]
        items.append(Item(cr, ("turn", typ, t_app, exit_leg), lambda X, cr=cr, spec=spec: cell_turn(cr, X, spec),
                          cands, X0, f"turn {typ} {t_app} {exit_leg}", fwd=inb))
    return items


def place(items, scene):
    """Greedy placement: groups in sheet order, each member at its first
    free candidate. Returns (placed cells, overflow items)."""
    placed, overflow = [], []
    chosen = {}
    groups = {}
    for it in items:
        groups.setdefault(it.group, []).append(it)
    prio = {"turn": 0, "angle": 0, "shoulder": 1, "cw": 1, "centre": 1, "queue": 2}
    order = sorted(groups.values(), key=lambda g: (prio.get(g[0].group[0], 2), min(i.cr.seq for i in g)))
    for g in order:
        for it in sorted(g, key=lambda i: i.cr.seq):
            done = False
            cells = []
            for X in it.candidates:
                try:
                    cells.append(it.build(X))
                except Exception as exc:      # noqa: BLE001
                    print("build failed", it.cr.crash_id, exc)
                    break
            # a clean spot first; failing that the sheets let a cell lie
            # across a crosswalk or a stop bar rather than leave the road
            for soft in ((), ("cw", "stop")):
                for k, cell in enumerate(cells):
                    if scene.free(cell, soft=soft):
                        cell.tag = it.where + (" (over crosswalk)" if soft else "")
                        scene.add_cell(cell)
                        placed.append(cell)
                        chosen[it.cr.crash_id] = k
                        done = True
                        break
                if done:
                    break
            if not done:
                overflow.append(it)
    return placed, overflow, chosen


def inset_rows():
    rows = SPEC.get("inset_rows") or [[40, 700, 40, 272], [1040, 1260, 40, 790], [40, 260, 40, 745], [40, 700, 40, 300]]
    out = []
    for x0, x1, step, y in rows:
        out += [(x, y) for x in range(int(x0), int(x1), int(step))]
    return out


def draw_insets(overflow, scene):
    """Lettered insets for the overflow, one per group: the cells nested
    inside as they would be on the road, the letter circled and coloured
    at the group's conflict point with a leader. Returns (svg list,
    where dict, unplaced ids)."""
    out, where, unplaced = [], {}, []
    groups = {}
    for it in overflow:
        groups.setdefault(it.group, []).append(it)
    chunk = int(SPEC.get("inset_chunk", 8))
    batches = []
    for key, members in sorted(groups.items(), key=lambda kv: min(i.cr.seq for i in kv[1])):
        members = sorted(members, key=lambda i: i.cr.seq)
        for k in range(0, len(members), chunk):
            batches.append(members[k:k + chunk])
    gi = 0
    for members in batches:
        letter = chr(ord("A") + gi)
        col = INSET_COLOURS[gi % len(INSET_COLOURS)]
        # pack the cells against each other only: a queue side by side
        # across its travel line, turning and angle cells nested diagonally
        local = Scene([], margin=-1e9)
        cells = []
        for it in members:
            X0 = it.anchor
            fwd = it.fwd
            rt = (fwd[1], -fwd[0])
            if it.stack == "lateral":
                order = sorted([(i, j) for i in range(0, 6) for j in range(-8, 9)], key=lambda ij: (ij[0], abs(ij[1]), -ij[1]))
                step_i, step_j = ALONG_STEP * 6.0, QUEUE_PITCH
            else:
                order = _nest_order(8, 8)
                step_i, step_j = NEST_STEP, NEST_STEP
            cell = None
            for i, j in order:
                X = add(add(X0, fwd, -i * step_i), rt, j * step_j)
                c = it.build(X)
                if local.free(c, CLEAR_CELL, 0.0):
                    cell = c
                    break
            if cell is None:
                unplaced.append(it.cr.crash_id)
                continue
            local.add_cell(cell)
            cells.append((it, cell))
        if not cells:
            continue
        ub = prims_bbox([p for _, c in cells for p, _ in c.prims])
        w, h = ub[2] - ub[0] + 24, ub[3] - ub[1] + 40
        box = None
        for ax, ay in inset_rows():
            cand = (ax, ay, ax + w, ay + h)
            if scene.free_rect((cand[0] - 6, cand[1] - 6, cand[2] + 6, cand[3] + 6)):
                box = cand
                break
        if box is None:
            for it, _ in cells:
                unplaced.append(it.cr.crash_id)
            continue
        scene.add_rect("inset", box)
        dx, dy = box[0] + 12 - ub[0], box[1] + 30 - ub[1]
        out.append(f'<rect x="{box[0]}" y="{box[1]}" width="{w:.0f}" height="{h:.0f}" fill="#fff" stroke="{col}" stroke-width="1.2"/>')
        out.append(f'<text x="{box[0] + 8}" y="{box[1] + 18}" font-size="15" font-style="italic" font-weight="bold" '
                   f'fill="{col}" font-family="serif">{letter}</text>')
        for it, c in cells:
            out.append(f'<g data-crash="{it.cr.crash_id}" data-seq="{it.cr.seq}" data-at="inset {letter}">'
                       f'<g transform="translate({dx:.1f},{dy:.1f})">{c.svg}</g></g>')
            where[it.cr.crash_id] = f"inset {letter} ({it.where})"
        # the marker at the group's spot
        anchors = [page(it.anchor) for it, _ in cells]
        ax = sum(a[0] for a in anchors) / len(anchors)
        ay = sum(a[1] for a in anchors) / len(anchors)
        spot = None
        for r in range(26, 120, 6):
            for ang in range(0, 360, 20):
                cx_ = ax + r * math.cos(math.radians(ang))
                cy_ = ay + r * math.sin(math.radians(ang))
                if scene.free_rect((cx_ - 9, cy_ - 9, cx_ + 9, cy_ + 9), 2.0):
                    spot = (cx_, cy_)
                    break
            if spot:
                break
        spot = spot or (ax + 30, ay - 30)
        scene.add_rect("marker", (spot[0] - 9, spot[1] - 9, spot[0] + 9, spot[1] + 9))
        vx, vy = ax - spot[0], ay - spot[1]
        vl = math.hypot(vx, vy) or 1.0
        ex, ey = ax - vx / vl * 3, ay - vy / vl * 3
        sx, sy = spot[0] + vx / vl * 8, spot[1] + vy / vl * 8
        out.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{col}" stroke-width="1.0"/>')
        scene.add_obstacle("marker", ("s", (sx, sy), (ex, ey), 1.0))
        hd = math.degrees(math.atan2(vy, vx))
        out.append(head_at((ex, ey), hd, 6.0).replace('fill="#000"', f'fill="{col}"'))
        out.append(f'<circle cx="{spot[0]:.1f}" cy="{spot[1]:.1f}" r="8" fill="#fff" stroke="{col}" stroke-width="1.1"/>')
        out.append(f'<text x="{spot[0]:.1f}" y="{spot[1] + 4.5:.1f}" font-size="11" font-style="italic" font-weight="bold" '
                   f'fill="{col}" text-anchor="middle" font-family="serif">{letter}</text>')
        gi += 1
    return out, where, unplaced


def crash_notes(scene, cells, notes):
    """Short notes beside unusual crashes (``crash_notes`` in the spec:
    crash id -> text), set at the nearest clear spot to the cell."""
    out = []
    by_id = {c.cr.crash_id: c for c in cells}
    for cid, text in (notes or {}).items():
        c = by_id.get(cid)
        if c is None:
            continue
        lines = textwrap.wrap(f"Crash #{c.cr.seq}: {text}", 26)
        w = max(cd._text_width(t, cd.NOTE_SIZE) for t in lines) + 8
        h = cd.NOTE_LEAD * len(lines) + 4
        bx, by = (c.bbox[0] + c.bbox[2]) / 2, (c.bbox[1] + c.bbox[3]) / 2
        spot = None
        for r in range(50, 220, 10):
            for ang in range(0, 360, 20):
                x = bx + r * math.cos(math.radians(ang))
                y = by + r * math.sin(math.radians(ang))
                rect = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
                if scene.free_rect(rect, 3.0):
                    spot = (x, y, rect)
                    break
            if spot:
                break
        if not spot:
            continue
        x, y, rect = spot
        scene.add_rect("note", rect)
        for k, line in enumerate(lines):
            out.append(cd._stroke_text(x, rect[1] + cd.NOTE_SIZE + k * cd.NOTE_LEAD, line, size=cd.NOTE_SIZE))
    return out


# ---------------------------------------------------------------- the sheet
def furniture(note_lines):
    """Sheet furniture svg and its keep-out rects."""
    svg, rects = [], []
    title = SPEC.get("title", [])
    tx, ty = float(SPEC.get("title_x", 335)), 54
    if title:
        bb = cd._text_bbox(tx, ty, title, cd.TITLE_SIZE, cd.TITLE_LEAD)
        svg.append(f'<rect x="{bb[0]:.1f}" y="{bb[1]:.1f}" width="{bb[2] - bb[0]:.1f}" '
                   f'height="{bb[3] - bb[1]:.1f}" fill="#fff"/>')
        for i, line in enumerate(title):
            svg.append(cd._stroke_text(tx, ty + i * cd.TITLE_LEAD, line, size=cd.TITLE_SIZE, sw=1.15))
        rects.append(bb)
    svg.append(f'<rect x="{cd.LEGEND_X - 2}" y="{cd.LEGEND_Y - 2}" width="{cd.LEGEND_W + 4}" '
               f'height="{cd.LEGEND_H + 4}" fill="#fff"/>')
    svg.append(cd.legend_block(cd.LEGEND_X, cd.LEGEND_Y))
    rects.append((cd.LEGEND_X - 8, cd.LEGEND_Y - 8, cd.LEGEND_X + cd.LEGEND_W + 8, cd.LEGEND_Y + cd.LEGEND_H + 8))
    nx, ny = SPEC.get("north", [655, 40])
    svg.append(cd.north_needle(nx, ny, rot=ROT))
    rects.append((nx - 60, ny - 6, nx + 60, ny + 176))
    svg.append('<rect x="1310" y="834" width="316" height="210" fill="#fff"/>')
    svg.append(cd.tsu_block(1318, 842, SPEC.get("prepared_by", ""), SPEC.get("date", ""),
                            cd.load_logo(SPEC.get("logo")) if SPEC.get("logo") else ""))
    rects.append((1300, 826, 1632, 1056))
    for lab in SPEC.get("labels", []):
        lx, ly = lab["xy"]
        lines = lab["lines"]
        bb = cd._text_bbox(lx, ly, lines, cd.ROUTE_SIZE, cd.ROUTE_LEAD, pad=4)
        svg.append(f'<rect x="{bb[0]:.1f}" y="{bb[1]:.1f}" width="{bb[2] - bb[0]:.1f}" '
                   f'height="{bb[3] - bb[1]:.1f}" fill="#fff" fill-opacity="0.9"/>')
        for k, line in enumerate(lines):
            svg.append(cd._stroke_text(lx, ly + k * cd.ROUTE_LEAD, line, size=cd.ROUTE_SIZE, sw=1.05))
        rects.append(bb)
    if note_lines:
        y0 = 1032 - (len(note_lines) - 1) * cd.NOTE_LEAD
        w = max(cd._text_width(t, cd.NOTE_SIZE) for t in note_lines)
        for i, line in enumerate(note_lines):
            svg.append(cd._stroke_text(30, y0 + i * cd.NOTE_LEAD, line, size=cd.NOTE_SIZE, anchor="start"))
        rects.append((24, y0 - cd.NOTE_SIZE - 4, 34 + w, 1040))
    for r in SPEC.get("keep_out", []):
        rects.append(tuple(float(v) for v in r))
    return svg, rects


def sheet(roads, body, furniture_svg):
    svg = [f'<rect x="14" y="14" width="{cd.PAGE_W - 28}" height="{cd.PAGE_H - 28}" '
           'fill="#fff" stroke="#000" stroke-width="2"/>',
           '<clipPath id="frame"><rect x="14" y="14" width="1604" height="1028"/></clipPath>',
           '<g clip-path="url(#frame)">'] + roads + ['</g>'] + furniture_svg + body
    return cd._wrap_html(svg)


def crash_type_names(analysis_csv):
    """Crash id -> crash type text from a TEAAS crash analysis export."""
    names = {}
    if not analysis_csv or not os.path.exists(analysis_csv):
        return names
    with open(analysis_csv, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.reader(fh):
            if len(row) > 3 and row[1].isdigit() and len(row[1]) == 9:
                names[row[1]] = row[3].capitalize()
    return names


def render(spec, data_csv, out_html, exclude=(), note=None, names=None):
    """Render the sheet. Writes ``out_html`` plus ``<stem>_index.csv`` (sheet
    number to crash) and ``<stem>_review.csv`` (how each crash was placed).
    Returns a summary dict."""
    configure(spec)
    crashes = cd.read_data_csv(data_csv)
    if exclude:
        crashes = [c for c in crashes if c.crash_id not in set(exclude)]
    for i, c in enumerate(crashes, 1):
        c.seq = i
    roads, obstacles = junction_svg()
    note_lines = [w for n_ in list(spec.get("notes", [])) + list(note or []) for w in textwrap.wrap(n_, 58)]
    furn_svg, rects = furniture(note_lines)
    scene = Scene(obstacles)
    for r in rects:
        scene.add_rect("furniture", r)
    sig_svg = ""
    if SIGNAL:
        sig_svg, sb = signal_symbol()
        scene.add_rect("signal", sb)
    items = plan(crashes)
    placed, overflow, chosen = place(items, scene)
    inset_svg, where_inset, unplaced = draw_insets(overflow, scene)
    where = {c.cr.crash_id: c.tag for c in placed}
    where.update(where_inset)
    for cid in unplaced:
        where[cid] = "not placed (no room on the sheet)"
    if unplaced:
        note_lines += textwrap.wrap("Not plotted (no room on the sheet): "
                                    + ", ".join(str(c.seq) for c in crashes if c.crash_id in unplaced) + ".", 58)
        furn_svg, _ = furniture(note_lines)
    notes_svg = crash_notes(scene, placed, spec.get("crash_notes"))
    body = inset_svg + [f'<g data-crash="{c.cr.crash_id}" data-seq="{c.cr.seq}" data-at="{c.tag}">{c.svg}</g>'
                        for c in placed] + notes_svg + [sig_svg]
    html = sheet(roads, body, furn_svg)
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)
    stem = out_html[:-5] if out_html.lower().endswith(".html") else out_html
    names = names or {}
    with open(stem + "_index.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_no", "crash_id", "date", "severity", "crash_type", "night", "surface",
                    "units", "placed_at"])
        for c in crashes:
            w.writerow([c.seq, c.crash_id, c.dt, c.severity, names.get(c.crash_id, c.acc_typ),
                        "night" if c.night else "day", c.road_cond, len(c.units),
                        where.get(c.crash_id, "not placed")])
    rows = []
    by_id = {it.cr.crash_id: it for it in items}
    with open(stem + "_review.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["seq", "crash_id", "type", "units", "on", "from", "approaches", "turner",
                    "anchor_xy", "candidate", "placed_at"])
        for c in crashes:
            apps, turner = resolve(c)
            it = by_id.get(c.crash_id)
            row = (c.seq, c.crash_id, c.acc_typ, " ".join(f"{x.direction}/m{x.maneuver}" for x in c.units),
                   c.on_road[-4:], c.from_road[-4:] or "-", "/".join(a.replace("_in", "") for a in apps),
                   turner if turner is not None else "-",
                   f"({it.anchor[0]:.0f},{it.anchor[1]:.0f})" if it else "-",
                   chosen.get(c.crash_id, "inset" if c.crash_id in where_inset else "-"),
                   where.get(c.crash_id, "not placed"))
            w.writerow(row)
            rows.append(row)
    return {"crashes": len(crashes), "placed": len(placed), "inset": len(where_inset),
            "unplaced": [c.seq for c in crashes if c.crash_id in unplaced], "rows": rows, "where": where}


def _chrome_path():
    env = os.environ.get("SAFETY_EVAL_CHROME")
    if env and os.path.exists(env):
        return env
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if root and os.path.isdir(root):
        for d in sorted(os.listdir(root), reverse=True):
            for rel in ("chrome-linux64/chrome", "chrome-linux/chrome", "chrome-win/chrome.exe"):
                p = os.path.join(root, d, rel)
                if os.path.exists(p):
                    return p
    return None


def print_pdf(html, pdf, png=None):
    """Print the sheet with headless Chromium (Playwright), 17x11 in."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        exe = _chrome_path()
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        pg = b.new_page(viewport={"width": cd.PAGE_W, "height": cd.PAGE_H})
        pg.goto("file://" + os.path.abspath(html))
        pg.wait_for_timeout(500)
        pg.pdf(path=pdf, width="17in", height="11in", print_background=True, prefer_css_page_size=True)
        if png:
            pg.screenshot(path=png, full_page=True)
        b.close()


def build(spec_path, data_csv, out_html, exclude_path=None, note=None, analysis_csv=None, pdf=False):
    """CLI entry: spec + data -> html (+ csvs, optional pdf/png)."""
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    exclude = ()
    if exclude_path:
        with open(exclude_path) as fh:
            exclude = tuple(line.strip() for line in fh if line.strip())
    res = render(spec, data_csv, out_html, exclude=exclude, note=note, names=crash_type_names(analysis_csv))
    if pdf:
        stem = out_html[:-5] if out_html.lower().endswith(".html") else out_html
        print_pdf(out_html, stem + ".pdf", stem + ".png")
    return res
