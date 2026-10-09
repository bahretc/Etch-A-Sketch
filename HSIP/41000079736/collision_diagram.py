#!/usr/bin/env python3
"""NCDOT Traffic Safety Unit style intersection collision diagram for TEAAS study 41000079736.

Drawn from the unit-level TEAAS collision diagram export (data/collision_diagram_crashes.json, built from
data/41000079736_CollisionDiagramData.csv) following the NCDOT TSU collision diagram conventions
(Collision Diagrams training, TSU, 1/18/2013) and the example diagrams in the Training/Checking Drive folder:

  * numbered circle at the tail of the at-fault vehicle's path, magenta asterisk beside it (driver at fault),
    green road-condition letter (D dry, W wet, I icy/snowy, O other) beside the circle;
  * blue dots on each vehicle path = impact speed in tens (none <10 mph, 1 dot 10-19 ... 6 dots 60-69,
    triple line 70+, blue X unknown);
  * hollow arrowhead = daylight, filled arrowhead = dark;
  * red circle at the impact point for injury crashes: hollow = non-severe (B, C), half-filled = severe (A),
    filled = fatality (K);
  * crash-type glyphs: angle, turning (curved path), rear end (bar at the rear of the stopped/lead vehicle),
    ran off road (zigzag) for fixed-object crashes;
  * crashes with identical type, fault, light, road condition, speed bins and severity are stacked on one glyph.

Output: maps/5_collision_diagram_NCDOT.png and .pdf (17 x 11 in landscape).
"""
import json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Rectangle, RegularPolygon, Wedge, FancyBboxPatch
from matplotlib.lines import Line2D

HERE = Path(__file__).resolve().parent
OUT = HERE / "maps"
CR = json.loads((HERE / "data" / "collision_diagram_crashes.json").read_text())

# ------------------------------------------------------------------ site facts
STUDY = "41000079736"
PH_NO = "________"                 # fill in when the PH number is assigned
COUNTY = "Cleveland County"
LOCATION = "NC 180/NC 226 (S Post Rd) at\nSR 1103 (Pleasant Dr/Pleasant Hill Church Rd)"
PERIOD = "9/1/2016 - 8/31/2026"
PREPARED_BY = ""                   # fill in
DATE = "10/09/2026"
BEAR_MAIN = 22.0                   # NC 180/NC 226 axis, bearing toward the north leg
BEAR_SIDE = 333.0                  # SR 1103 axis, bearing toward the Pleasant Dr (northwest) leg
LEGS = {  # leg name -> (bearing from the intersection, label lines)
    "N":  (BEAR_MAIN,        ["NC 180/NC 226", "(S Post Rd)", "AADT (Year)", "10,500 (2025)", "45 mph"]),
    "S":  (BEAR_MAIN + 180,  ["NC 180/NC 226", "(S Post Rd)", "AADT (Year)", "10,000 (2025)", "45 mph"]),
    "NW": (BEAR_SIDE,        ["SR 1103", "(Pleasant Dr)", "AADT (Year)", "1,500 (2024)", "45 mph"]),
    "SE": (BEAR_SIDE + 180,  ["SR 1103", "(Pleasant Hill Church Rd)", "AADT (Year)", "1,200 (2025)", "45 mph"]),
}
W_MAIN, W_SIDE, RADIUS = 24.0, 22.0, 40.0   # pavement widths and corner radii, feet (traced from aerial)

# ------------------------------------------------------------------ code tables (NCDOT crash data)
TYPE = {17: "Animal", 19: "Fixed object", 21: "Rear end, slow or stop", 23: "Left turn, same roadway",
        24: "Left turn, different roadways", 25: "Right turn, same roadway", 26: "Right turn, different roadways",
        27: "Head on", 28: "Sideswipe, same direction", 29: "Sideswipe, opposite direction", 30: "Angle"}
ROADCOND = {1: "D", 2: "W", 3: "O", 4: "I", 5: "I", 6: "I", 7: "O", 8: "O", 9: "O"}  # 1 dry 2 wet 3 water 4 ice 5 snow 6 slush 7 sand/mud 8 fuel/oil 9 other
NIGHT = {4, 5, 6}                     # LT_COND dark (lighted, not lighted, unknown lighting)
SEV = {1: "K", 2: "A", 3: "B", 4: "C", 5: "O", 6: "U"}
OBJECT_NOTE = {"107037107": "struck embankment", "107067627": "struck ditch"}
TARGET = {23, 24, 25, 26, 27, 30}            # frontal impact crashes = HSIP warrant I-1r pattern -> red number circle
MAG, GRN, BLU, RED = "#ff00ff", "#008000", "#0000ff", "#ff0000"

# ------------------------------------------------------------------ geometry helpers (feet, x east, y north)
def unit(b):
    r = math.radians(b); return (math.sin(r), math.cos(r))
def add(a, b, s=1.0): return (a[0] + b[0] * s, a[1] + b[1] * s)
def rot(v, deg):
    r = math.radians(deg); return (v[0] * math.cos(r) - v[1] * math.sin(r), v[0] * math.sin(r) + v[1] * math.cos(r))
def right(v): return (v[1], -v[0])
def norm(v):
    L = math.hypot(*v); return (v[0] / L, v[1] / L)
DIRV = {"N": unit(BEAR_MAIN), "NE": unit(BEAR_MAIN), "S": unit(BEAR_MAIN + 180), "SW": unit(BEAR_MAIN + 180),
        "W": unit(BEAR_SIDE), "NW": unit(BEAR_SIDE), "E": unit(BEAR_SIDE + 180), "SE": unit(BEAR_SIDE + 180)}
APPROACH = {"N": "S", "NE": "S", "S": "N", "SW": "N", "E": "NW", "SE": "NW", "W": "SE", "NW": "SE"}  # travel dir -> leg it came from


def bezier(p0, p1, p2, n=24):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in [i / n for i in range(n + 1)]]


def cubic(p0, c1, c2, p3, n=30):
    out = []
    for i in range(n + 1):
        t = i / n; a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0[0] + b * c1[0] + c * c2[0] + d * p3[0], a * p0[1] + b * c1[1] + c * c2[1] + d * p3[1]))
    return out


def resample(pts, step):
    """points along polyline every `step` feet, plus cumulative length"""
    out, acc, total = [], 0.0, 0.0
    segs = list(zip(pts[:-1], pts[1:]))
    L = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs)
    d = step
    for a, b in segs:
        sl = math.hypot(b[0] - a[0], b[1] - a[1])
        while d <= acc + sl and sl > 0:
            f = (d - acc) / sl; out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)); d += step
        acc += sl
    return out, L


# ------------------------------------------------------------------ glyph primitives (drawn in the feet axes)
class G:
    def __init__(self, ax, lw=1.1):
        self.ax, self.lw = ax, lw

    def arrowhead(self, p, d, night, size=9.0):
        d = norm(d); n = right(d)
        tip = p; a = add(add(p, d, -size), n, size * 0.42); b = add(add(p, d, -size), n, -size * 0.42)
        self.ax.add_patch(Polygon([tip, a, b], closed=True, fc="black" if night else "white", ec="black", lw=self.lw, zorder=6))

    def speed_marks(self, pts, speed):
        """blue dots along the first part of the path: impact speed in tens; 70+ triple line; None -> X"""
        if speed is None:
            (x, y), = resample(pts, 14)[0][:1] if resample(pts, 14)[0] else [pts[0]]
            self.ax.plot(x, y, marker="x", ms=4.5, mew=1.2, color=BLU, zorder=7); return
        if speed >= 70:
            d = norm((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])); n = right(d)
            for k in (-1, 1):
                a, b = add(add(pts[0], d, 4), n, 1.8 * k), add(add(pts[0], d, 34), n, 1.8 * k)
                self.ax.plot([a[0], b[0]], [a[1], b[1]], color=BLU, lw=0.9, zorder=7)
            return
        n = min(int(speed // 10), 6)
        if n:
            dots, _ = resample(pts, 6.0)
            for x, y in dots[1:1 + n]:
                self.ax.plot(x, y, "o", ms=3.0, color=BLU, zorder=7)

    def path(self, pts, night, speed, head=True, lw=None):
        xs, ys = zip(*pts)
        self.ax.plot(xs, ys, color="black", lw=lw or self.lw, solid_capstyle="round", zorder=5)
        if head:
            self.arrowhead(pts[-1], (pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]), night)
        self.speed_marks(pts, speed)

    def bar(self, p, d, half=6.0):
        n = right(norm(d)); a, b = add(p, n, half), add(p, n, -half)
        self.ax.plot([a[0], b[0]], [a[1], b[1]], color="black", lw=self.lw, zorder=6)

    def injury(self, p, sev):
        if sev in ("B", "C", "U"):
            self.ax.add_patch(Circle(p, 3.2, fc="white", ec=RED, lw=1.1, zorder=8))
        elif sev == "A":
            self.ax.add_patch(Circle(p, 3.2, fc="white", ec=RED, lw=1.1, zorder=8))
            self.ax.add_patch(Wedge(p, 3.2, 0, 180, fc=RED, ec=RED, lw=0, zorder=8))
        elif sev == "K":
            self.ax.add_patch(Circle(p, 3.2, fc=RED, ec=RED, lw=1.1, zorder=8))

    def number_circle(self, p, text, r=7.0, target=False):
        col = RED if target else "black"
        self.ax.add_patch(Circle(p, r, fc="white", ec=col, lw=1.0, zorder=9))
        self.ax.text(p[0], p[1], text, ha="center", va="center", fontsize=7.5 if len(text) < 3 else 6.5, zorder=10, family="DejaVu Sans", color=col)

    def fault(self, p):
        self.ax.text(p[0], p[1], "∗", ha="center", va="center", fontsize=13, color=MAG, zorder=10, fontweight="bold")

    def roadcond(self, p, letter):
        self.ax.text(p[0], p[1], letter, ha="center", va="center", fontsize=8.5, color=GRN, zorder=10, family="DejaVu Sans")

    def zigzag_path(self, tail, d, side, L1=28.0, L2=30.0, amp=9.0):
        """ran-off-road: straight L1, zigzag, then straight L2 angled off to `side` (+1 right, -1 left)"""
        d = norm(d); n = right(d)
        a = add(tail, d, L1)
        z = [a, add(add(a, d, 6), n, amp * side), add(add(a, d, 14), n, -amp * side), add(add(a, d, 20), n, amp * side * 0.6), add(a, d, 24)]
        off = norm(rot(d, -35 * side))   # veer to the side
        end = add(z[-1], off, L2)
        return [tail] + z + [end]


# ------------------------------------------------------------------ crash -> glyph description
def speed_of(u):
    for k in ("speed_impact", "speed_est"):
        v = u.get(k)
        if v not in (None, "", 0) or (v == 0 and k == "speed_impact" and u.get("speed_est") in (None, "", 0)):
            return float(v)
    return 0.0 if u.get("maneuver") == 1 else None


def at_fault_index(c):
    us = c["units"]
    cands = [i for i, u in enumerate(us) if u["violation"] not in (0, None)]
    return cands[0] if cands else 0


def signature(c):
    us = c["units"]; f = at_fault_index(c)
    bins = tuple((u["direction"], u["maneuver"], None if speed_of(u) is None else min(int(speed_of(u) // 10), 7)) for u in us)
    return (c["acc_typ"], f, bins, c["lt_cond"] in NIGHT, ROADCOND.get(c["rd_cond"], "O"), SEV.get(c["severity_cd"], "U"))


def draw_crash(g, P, c, numbers):
    """Draw one glyph with impact point P for crash c (and stacked crash numbers)."""
    us = c["units"]; f = at_fault_index(c); night = c["lt_cond"] in NIGHT
    sev = SEV.get(c["severity_cd"], "U"); rc = ROADCOND.get(c["rd_cond"], "O"); typ = c["acc_typ"]
    tails = {}
    # paths per unit
    for i, u in enumerate(us):
        t = DIRV[u["direction"]]; sp = speed_of(u); m = u["maneuver"]
        if typ == 19:                                            # fixed object -> ran off road
            tail = add(P, t, -62); pts = g.zigzag_path(tail, t, +1)
            g.path(pts, night, sp); tails[i] = tail
            end = pts[-1]; d = norm((end[0] - pts[-2][0], end[1] - pts[-2][1])); nn = right(d)
            g.ax.text(end[0] + d[0] * 10 + nn[0] * 16, end[1] + d[1] * 10 + nn[1] * 16, OBJECT_NOTE.get(c["crash_id"], ""), fontsize=5.5, ha="center", va="center", zorder=9,
                      bbox=dict(fc="white", ec="none", pad=0.5))
            continue
        if m == 1:                                               # stopped in travel lane: bar at the rear, short arrow forward
            g.bar(P, t); pts = [P, add(P, t, 26)]; g.path(pts, night, sp); tails[i] = P; continue
        if m == 8 or m == 7:                                     # turning: straight approach then a quarter-circle ending at P on the turned heading
            left = (m == 8); out = norm(rot(t, 90 if left else -90)); R, Ls = 22.0, 32.0
            start = add(add(P, t, -R), out, -R); tail = add(start, t, -Ls); centre = add(start, out, R)
            arc = [add(add(centre, out, -R * math.cos(math.radians(a))), t, R * math.sin(math.radians(a))) for a in range(0, 91, 6)]
            pts = [tail] + arc
            g.path(pts, night, sp); tails[i] = tail; continue
        if typ == 21 and i != f and m in (4, 11):                # rear end lead vehicle (moving/slowing)
            g.bar(P, t); pts = [P, add(P, t, 30)]; g.path(pts, night, sp); tails[i] = P; continue
        # straight path ending at the impact point
        tail = add(P, t, -56); pts = [tail, P]
        if typ == 21 and i == f:
            pts = [tail, add(P, t, -2)]
        g.path(pts, night, sp); tails[i] = tail
    # impact / injury marker
    if sev in ("A", "B", "C", "K", "U"):
        g.injury(P if typ != 21 else add(P, DIRV[us[f]["direction"]], 8), sev)
    # numbered circle(s) at the tail of the at-fault vehicle, asterisk + road condition beside
    tf = DIRV[us[f]["direction"]]; tail = tails.get(f, add(P, tf, -56)); n = right(tf)
    base = add(tail, tf, -8)
    for k, num in enumerate(numbers):
        g.number_circle(add(base, tf, -k * 15), str(num), target=(typ in TARGET))
    g.fault(add(add(base, n, 11), tf, 5))
    g.roadcond(add(add(base, n, -11), tf, 5), rc)


# ------------------------------------------------------------------ layout
def layout(crashes):
    """Group identical crashes, assign each glyph to a slot on its approach leg. Returns [(P, crash, numbers)]."""
    groups = {}
    for c in crashes:
        groups.setdefault(signature(c), []).append(c)
    per_leg = {}
    for sig, cs in sorted(groups.items(), key=lambda kv: kv[1][0]["no"]):
        c0 = cs[0]; leg = APPROACH[c0["units"][at_fault_index(c0)]["direction"]]
        per_leg.setdefault(leg, []).append((cs, c0))
    placed = []
    for leg, items in per_leg.items():
        bearing = LEGS[leg][0]; u = unit(bearing); t = (-u[0], -u[1]); n = right(t)   # t: travel toward intersection
        half_w = W_MAIN / 2 if leg in ("N", "S") else W_SIDE / 2
        cols = [half_w / 2 + 2, half_w + 68, -(half_w + 68), half_w + 136, half_w + 204]      # lane, right, left, far right, farther right
        rows_per_col = 3
        for k, (cs, c0) in enumerate(items):
            col, row = k // rows_per_col, k % rows_per_col
            dist = 115 + 92 * row
            P = add(add((0, 0), u, dist), n, cols[col % len(cols)])
            placed.append((P, c0, [c["no"] for c in cs]))
    return placed


# ------------------------------------------------------------------ base map
def base_map(ax):
    legs = {k: unit(v[0]) for k, v in LEGS.items()}
    L = 520
    def edge(a_leg, b_leg, side):
        pass
    # pavement edges per leg as straight lines, corners rounded with fillets between adjacent legs
    pairs = [("N", "NW"), ("NW", "S"), ("S", "SE"), ("SE", "N")]
    widths = {"N": W_MAIN / 2, "S": W_MAIN / 2, "NW": W_SIDE / 2, "SE": W_SIDE / 2}
    for a, b in pairs:
        ua, ub = legs[a], legs[b]
        # edge of leg a on the side toward leg b, and edge of leg b on the side toward leg a
        na = right(ua); na = na if (na[0] * ub[0] + na[1] * ub[1]) > 0 else (-na[0], -na[1])
        nb = right(ub); nb = nb if (nb[0] * ua[0] + nb[1] * ua[1]) > 0 else (-nb[0], -nb[1])
        # fillet: circle tangent to both edge lines, radius R, in the wedge between legs a and b
        bis = norm(add(ua, ub)); half = math.acos(max(-1, min(1, ua[0] * ub[0] + ua[1] * ub[1]))) / 2
        R = RADIUS if half > math.radians(50) else 22.0
        # distance from corner intersection of the two offset edge lines along bisector to circle centre
        # offset lines: points x with x.na = wa, x.nb = wb ; corner point solves both
        wa, wb = widths[a], widths[b]
        det = na[0] * nb[1] - na[1] * nb[0]
        corner = ((wa * nb[1] - wb * na[1]) / det, (na[0] * wb - nb[0] * wa) / det)
        centre = add(corner, bis, R / math.sin(half))
        # tangent points
        ta = add(centre, na, -R); tb = add(centre, nb, -R)
        # straight edges from tangent points outward along each leg
        ea = add(ta, ua, L); eb = add(tb, ub, L)
        ax.plot([ta[0], ea[0]], [ta[1], ea[1]], color="black", lw=1.0, zorder=2)
        ax.plot([tb[0], eb[0]], [tb[1], eb[1]], color="black", lw=1.0, zorder=2)
        a0 = math.degrees(math.atan2(-na[1], -na[0])); a1 = math.degrees(math.atan2(-nb[1], -nb[0]))
        d = (a1 - a0 + 540) % 360 - 180
        arc = [add(centre, (math.cos(math.radians(a0 + d * i / 16)), math.sin(math.radians(a0 + d * i / 16))), R) for i in range(17)]
        ax.plot([p[0] for p in arc], [p[1] for p in arc], color="black", lw=1.0, zorder=2)
    # centerlines (dashed) stopping at the mainline edge for the side street
    for leg, half in (("N", W_SIDE / 2 + 12), ("S", W_SIDE / 2 + 12)):
        u = legs[leg]; a = add((0, 0), u, half); b = add((0, 0), u, L)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="black", lw=0.6, ls=(0, (8, 6)), zorder=2)
    for leg in ("NW", "SE"):
        u = legs[leg]; a = add((0, 0), u, W_MAIN / 2 + 2); b = add((0, 0), u, L)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="black", lw=0.6, ls=(0, (8, 6)), zorder=2)
        # stop bar across the approach lane and STOP sign on the right of the approach
        t = (-u[0], -u[1]); n = right(t); sb = add((0, 0), u, W_MAIN / 2 + 6)
        ax.plot([sb[0], add(sb, n, W_SIDE / 2)[0]], [sb[1], add(sb, n, W_SIDE / 2)[1]], color="black", lw=2.6, zorder=3)
        sp = add(add((0, 0), u, W_MAIN / 2 + 34), n, W_SIDE / 2 + 30)
        ax.add_patch(RegularPolygon(sp, 8, radius=11, orientation=math.radians(22.5), fc=RED, ec="black", lw=0.6, zorder=4))
        ax.text(sp[0], sp[1], "STOP", ha="center", va="center", fontsize=4.5, color="white", fontweight="bold", zorder=5)


# ------------------------------------------------------------------ sheet furniture (page axes, inches)
def legend(px, x0, y0, w=6.6, h=2.55):
    px.add_patch(Rectangle((x0, y0), w, h, fc="white", ec="black", lw=0.8, zorder=3))
    px.text(x0 + w / 2, y0 + h - 0.22, "LEGEND", ha="center", va="center", fontsize=12, style="italic", zorder=4)
    px.plot([x0 + w / 2 - 0.55, x0 + w / 2 + 0.55], [y0 + h - 0.36, y0 + h - 0.36], color="black", lw=0.6, zorder=4)
    def arrow(x, y, L=0.42, night=False, dots=0, tri=False, unk=False, head=True):
        px.plot([x, x + L], [y, y], color="black", lw=0.8, zorder=4)
        if head:
            px.add_patch(Polygon([(x + L, y), (x + L - 0.11, y + 0.045), (x + L - 0.11, y - 0.045)], fc="black" if night else "white", ec="black", lw=0.7, zorder=5))
        for i in range(dots):
            px.plot(x + 0.06 + i * 0.05, y, "o", ms=2.2, color=BLU, zorder=5)
        if tri:
            for dy in (-0.02, 0, 0.02): px.plot([x, x + L - 0.11], [y + dy, y + dy], color=BLU, lw=0.7, zorder=5)
        if unk: px.plot(x + 0.15, y, marker="x", ms=4, color=BLU, mew=1, zorder=5)
    fs = 5.6; cx = x0 + 0.15; cy = y0 + h - 0.62; dy = 0.235
    rows = [("MOVING VEHICLE", lambda x, y: arrow(x, y)),
            ("PARKED VEHICLE", lambda x, y: (px.add_patch(Rectangle((x, y - 0.07), 0.3, 0.14, fc="white", ec="black", lw=0.7, zorder=5)),
                                            px.plot([x, x + 0.3], [y - 0.07, y + 0.07], color="black", lw=0.6, zorder=5), px.plot([x, x + 0.3], [y + 0.07, y - 0.07], color="black", lw=0.6, zorder=5))),
            ("MOVABLE OBJECT", lambda x, y: (arrow(x, y, 0.36), px.plot([x + 0.4, x + 0.48, x + 0.48], [y + 0.08, y + 0.08, y - 0.08], color="black", lw=0.7, zorder=5))),
            ("HEAD ON", lambda x, y: (arrow(x, y, 0.22), px.plot([x + 0.44, x + 0.22], [y, y], color="black", lw=0.8, zorder=4),
                                     px.add_patch(Polygon([(x + 0.22, y), (x + 0.33, y + 0.045), (x + 0.33, y - 0.045)], fc="white", ec="black", lw=0.7, zorder=5)),
                                     px.plot([x + 0.22, x + 0.22], [y - 0.09, y + 0.09], color="black", lw=0.7, zorder=5))),
            ("REAR END", lambda x, y: (arrow(x, y, 0.2), px.plot([x + 0.2, x + 0.2], [y - 0.09, y + 0.09], color="black", lw=0.7, zorder=5), arrow(x + 0.2, y, 0.28))),
            ("RAN OFF ROAD", lambda x, y: (px.plot([x, x + 0.1, x + 0.16, x + 0.24, x + 0.3], [y, y, y + 0.09, y - 0.09, y], color="black", lw=0.8, zorder=4), arrow(x + 0.3, y, 0.2))),
            ("DAYLIGHT CRASH", lambda x, y: arrow(x, y)),
            ("NIGHT CRASH", lambda x, y: arrow(x, y, night=True))]
    for i, (lab, fn) in enumerate(rows):
        fn(cx, cy - i * dy); px.text(cx + 0.72, cy - i * dy, lab, fontsize=fs, va="center", zorder=5)
    cx2 = x0 + 2.25; cy2 = y0 + h - 0.75; dy2 = 0.33
    def angle(x, y):
        px.plot([x + 0.3, x + 0.3], [y + 0.25, y + 0.03], color="black", lw=0.8, zorder=4)
        px.add_patch(Polygon([(x + 0.3, y + 0.02), (x + 0.26, y + 0.12), (x + 0.34, y + 0.12)], fc="white", ec="black", lw=0.7, zorder=5)); arrow(x, y, 0.3)
    def turning(x, y):
        pts = bezier((x, y), (x + 0.3, y), (x + 0.45, y + 0.2)); px.plot([p[0] for p in pts], [p[1] for p in pts], color="black", lw=0.8, zorder=4)
        px.add_patch(Polygon([(x + 0.45, y + 0.2), (x + 0.33, y + 0.17), (x + 0.4, y + 0.08)], fc="white", ec="black", lw=0.7, zorder=5))
    def backing(x, y):
        arrow(x, y, 0.22); px.plot([x + 0.22, x + 0.22], [y - 0.09, y + 0.09], color="black", lw=0.7, zorder=5)
        px.plot([x + 0.22, x + 0.5], [y, y], color="black", lw=0.8, zorder=4)
        px.add_patch(Polygon([(x + 0.22, y), (x + 0.32, y + 0.045), (x + 0.32, y - 0.045)], fc="white", ec="black", lw=0.7, zorder=5)); arrow(x + 0.32, y, 0.18)
    def sideswipe(x, y):
        arrow(x, y + 0.05, 0.5); px.plot([x, x + 0.22, x + 0.3, x + 0.5], [y - 0.05, y - 0.05, y + 0.05, y - 0.05], color="black", lw=0.8, zorder=4)
        px.add_patch(Polygon([(x + 0.5, y - 0.05), (x + 0.39, y - 0.005), (x + 0.39, y - 0.095)], fc="white", ec="black", lw=0.7, zorder=5))
    def inj(x, y, kind):
        arrow(x, y, 0.4); c = (x + 0.46, y)
        if kind == "non": px.add_patch(Circle(c, 0.04, fc="white", ec=RED, lw=0.8, zorder=5))
        elif kind == "sev": px.add_patch(Circle(c, 0.04, fc="white", ec=RED, lw=0.8, zorder=5)); px.add_patch(Wedge(c, 0.04, 0, 180, fc=RED, ec=RED, zorder=5))
        else: px.add_patch(Circle(c, 0.04, fc=RED, ec=RED, lw=0.8, zorder=5))
    rows2 = [("ANGLE", angle), ("TURNING", turning), ("BACKING", backing), ("SIDESWIPE", sideswipe),
             ("NON-SEVERE INJURY", lambda x, y: inj(x, y, "non")), ("SEVERE INJURY", lambda x, y: inj(x, y, "sev")), ("FATALITY", lambda x, y: inj(x, y, "fat"))]
    for i, (lab, fn) in enumerate(rows2):
        yy = cy2 - i * (dy2 if i < 4 else 0.22) - (0 if i < 4 else 0.35)
        fn(cx2, yy); px.text(cx2 + 0.78, yy + (0.08 if i < 2 else 0), lab, fontsize=fs, va="center", zorder=5)
    cx3 = x0 + 4.2; cy3 = y0 + h - 0.62; dy3 = 0.225
    rows3 = ["9 MPH OR LESS", "10 MPH TO 19", "20 MPH TO 29", "30 MPH TO 39", "40 MPH TO 49", "50 MPH TO 59", "60 MPH TO 69", "70 AND UP", "SPEED UNKNOWN"]
    for i, lab in enumerate(rows3):
        y = cy3 - i * dy3
        arrow(cx3, y, 0.42, dots=i if i < 7 else 0, tri=(i == 7), unk=(i == 8)); px.text(cx3 + 0.55, y, lab, fontsize=fs, va="center", zorder=5)
    cx4 = x0 + 5.55; cy4 = y0 + h - 0.62; dy4 = 0.225
    rows4 = [("A", "ANIMAL", "black"), ("P", "PEDESTRIAN", "black"), ("B", "BICYCLE", "black"), ("T", "TRAIN", "black"), ("∗", "DRIVER AT FAULT", MAG),
             ("D", "DRY", "black"), ("W", "WET", "black"), ("I", "ICY OR SNOWY", "black"), ("O", "Other", "black")]
    for i, (sym, lab, col) in enumerate(rows4):
        y = cy4 - i * dy4
        px.text(cx4, y, sym, fontsize=9 if sym != "∗" else 13, va="center", ha="center", color=col, zorder=5, fontweight="bold" if sym == "∗" else "normal")
        px.text(cx4 + 0.2, y, lab, fontsize=fs, va="center", zorder=5)


def title_block(px, x0, y0, w=3.3, h=2.0):
    px.add_patch(Rectangle((x0, y0), w, h, fc="white", ec="black", lw=0.8, zorder=3))
    for frac in (0.62, 0.42, 0.24):
        px.plot([x0, x0 + w], [y0 + h * frac, y0 + h * frac], color="black", lw=0.8, zorder=4)
    px.plot([x0 + w / 2, x0 + w / 2], [y0 + h * 0.24, y0 + h * 0.42], color="black", lw=0.8, zorder=4)
    px.text(x0 + w / 2, y0 + h * 0.93, "N.C. DEPARTMENT of TRANSPORTATION", ha="center", va="center", fontsize=8.5, fontweight="bold", style="italic", family="DejaVu Serif", zorder=5)
    px.text(x0 + w / 2, y0 + h * 0.82, "DIVISION of HIGHWAYS", ha="center", va="center", fontsize=8.5, fontweight="bold", style="italic", family="DejaVu Serif", zorder=5)
    px.text(x0 + w / 2, y0 + h * 0.70, "TRANSPORTATION MOBILITY and\nSAFETY DIVISION", ha="center", va="center", fontsize=7.5, fontweight="bold", style="italic", family="DejaVu Serif", linespacing=1.1, zorder=5)
    px.text(x0 + w / 2, y0 + h * 0.52, "TRAFFIC  SAFETY  UNIT", ha="center", va="center", fontsize=12, fontweight="bold", style="italic", family="DejaVu Serif", zorder=5)
    px.text(x0 + w / 4, y0 + h * 0.33, f"Date: {DATE}", ha="center", va="center", fontsize=7, fontweight="bold", style="italic", family="DejaVu Serif", zorder=5)
    px.text(x0 + 3 * w / 4, y0 + h * 0.33, f"Prepared By: {PREPARED_BY}", ha="center", va="center", fontsize=7, fontweight="bold", style="italic", family="DejaVu Serif", zorder=5)


def north_arrow(px, x, y, bearing_up=0.0, L=1.3):
    """slender needle pointing to true north (page up = north here)"""
    d = (math.sin(math.radians(bearing_up)), math.cos(math.radians(bearing_up))); n = right(d)
    tip = (x + d[0] * L / 2, y + d[1] * L / 2); base = (x - d[0] * L / 2, y - d[1] * L / 2)
    px.add_patch(Polygon([tip, add(base, n, 0.07), base], fc="black", ec="black", lw=0.6, zorder=5))
    px.add_patch(Polygon([tip, add(base, n, -0.07), base], fc="white", ec="black", lw=0.6, zorder=5))
    px.text(x - d[0] * 0.05 - n[0] * 0.0, y + 0.02, "N", ha="center", va="center", fontsize=7, zorder=6,
            bbox=dict(boxstyle="circle,pad=0.15", fc="white", ec="black", lw=0.5))


# ------------------------------------------------------------------ main
def main():
    OUT.mkdir(exist_ok=True)
    fig = plt.figure(figsize=(17, 11))
    px = fig.add_axes([0, 0, 1, 1]); px.set_xlim(0, 17); px.set_ylim(0, 11); px.set_axis_off()
    px.add_patch(Rectangle((0.25, 0.25), 16.5, 10.5, fc="white", ec="black", lw=1.2, zorder=1))
    # drawing axes: feet, north up; the intersection sits at page point (CXI, CYI) inches, FPI feet per inch
    FPI, CXI, CYI = 90.0, 6.6, 5.5
    ax = fig.add_axes([0.3 / 17, 0.3 / 11, 16.4 / 17, 10.4 / 11]); ax.set_axis_off(); ax.set_aspect("equal")
    ax.set_xlim(-(CXI - 0.3) * FPI, (16.7 - CXI) * FPI); ax.set_ylim(-(CYI - 0.3) * FPI, (10.7 - CYI) * FPI)
    ax.patch.set_alpha(0)
    base_map(ax)
    for leg, (xi, yi) in {"N": (9.55, 7.7), "S": (3.3, 1.15), "NW": (1.9, 8.75), "SE": (10.4, 1.2)}.items():
        px.text(xi, yi, "\n".join(LEGS[leg][1]), ha="center", va="center", fontsize=8, linespacing=1.25, zorder=4, family="DejaVu Sans")
    g = G(ax)
    placed = layout(CR)
    for P, c, nums in placed:
        draw_crash(g, P, c, nums)
    # furniture
    legend(px, 16.65 - 6.6, 10.65 - 2.55)
    px.add_patch(Rectangle((12.3, 7.45), 2.3, 0.42, fc="white", ec="black", lw=0.7, zorder=3))
    px.add_patch(Circle((12.55, 7.66), 0.11, fc="white", ec=RED, lw=0.9, zorder=4)); px.text(12.55, 7.66, "#", ha="center", va="center", fontsize=7, color=RED, zorder=5)
    px.text(12.75, 7.66, "Target Crashes (frontal impact)", va="center", fontsize=7, color=RED, zorder=5)
    title_block(px, 16.65 - 3.3, 0.3)
    north_arrow(px, 15.6, 5.9)
    px.text(2.0, 5.3, f"PH# {PH_NO}\nOrder# {STUDY}\n{COUNTY}\n{LOCATION}\n{PERIOD}", ha="center", va="center", fontsize=9, linespacing=1.35, zorder=5, family="DejaVu Sans")
    # crash summary note (stacking key)
    n_stack = sum(1 for _, _, nums in placed if len(nums) > 1)
    fig.savefig(OUT / "5_collision_diagram_NCDOT.png", dpi=150)
    fig.savefig(OUT / ".review_300dpi.png", dpi=300)
    fig.savefig(OUT / "5_collision_diagram_NCDOT.pdf")
    plt.close(fig)
    print(f"{len(CR)} crashes, {len(placed)} glyphs ({n_stack} stacked)")
    for P, c, nums in placed:
        print(f"  #{','.join(map(str, nums)):10} {TYPE.get(c['acc_typ'], c['acc_typ']):32} leg {APPROACH[c['units'][at_fault_index(c)]['direction']]:2} P=({P[0]:.0f},{P[1]:.0f})")


if __name__ == "__main__":
    main()
