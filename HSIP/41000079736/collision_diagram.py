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
LOCATION = "NC 180/NC 226 (S Post Rd) at\nSR 1103 (Pleasant Dr /\nPleasant Hill Church Rd)"
PERIOD = "9/1/2016 - 8/31/2026"
PREPARED_BY = ""                   # fill in
DATE = "10/09/2026"
BEAR_MAIN = 22.0                   # NC 180/NC 226 axis, bearing toward the north leg
BEAR_SIDE = 333.0                  # SR 1103 axis, bearing toward the Pleasant Dr (northwest) leg
LEGS = {  # leg name -> (bearing from the intersection, label lines)
    # AADT for the middle year of the 10-yr study (2021); SR 1103 NW leg has no 2021 count -> straight-line estimate
    "N":  (BEAR_MAIN,        ["NC 180/NC 226", "(South Post Road)", "AADT (Year)", "11,000 (2021)", "45 mph"]),
    "S":  (BEAR_MAIN + 180,  ["NC 180/NC 226", "(South Post Road)", "AADT (Year)", "10,500 (2021)", "45 mph"]),
    "NW": (BEAR_SIDE,        ["SR 1103", "(Pleasant Drive)", "AADT (Year)", "1,400 (2021)", "(estimate)", "45 mph"]),
    "SE": (BEAR_SIDE + 180,  ["SR 1103", "(Pleasant Hill Church Road)", "AADT (Year)", "1,200 (2021)", "45 mph"]),
}
W_MAIN, W_SIDE, RADIUS = 24.0, 22.0, 40.0   # pavement widths and corner radii, feet (traced from aerial)

# ------------------------------------------------------------------ code tables (NCDOT crash data)
TYPE = {17: "Animal", 19: "Fixed object", 21: "Rear end, slow or stop", 23: "Left turn, same roadway",
        24: "Left turn, different roadways", 25: "Right turn, same roadway", 26: "Right turn, different roadways",
        27: "Head on", 28: "Sideswipe, same direction", 29: "Sideswipe, opposite direction", 30: "Angle"}
ROADCOND = {1: "D", 2: "W", 3: "O", 4: "I", 5: "I", 6: "I", 7: "O", 8: "O", 9: "O"}  # 1 dry 2 wet 3 water 4 ice 5 snow 6 slush 7 sand/mud 8 fuel/oil 9 other
NIGHT = {4, 5, 6}                     # LT_COND dark (lighted, not lighted, unknown lighting)
SEV = {1: "K", 2: "A", 3: "B", 4: "C", 5: "O", 6: "U"}
NOTES = {   # terse notes beside the glyph, as on the TSU sheets; the long form is in the sheet notes box and the listing
    "107037107": "ran off road R\nturning right;\nhit embankment",
    "107067627": "ran off road R\n0.009 mi S of\nSR 1103; ditch",
    "106423994": "3 units; unit 3\nstopped at stop",
    "107790631": "3 units",
    "106808749": "0.6 mi E of int.\n(not to scale)",
    "108502945": "both drivers\ncharged",
    "107960640": "unmileposted;\nlocated by\nDMV-349 coords",
}
PATH_F, PATH_O, STOP_ARROW, R_CIRC, TURN_R, TURN_S = 44.0, 40.0, 18.0, 6.5, 20.0, 22.0   # feet
TARGET = {23, 24, 25, 26, 27, 30}            # frontal impact crashes = HSIP warrant I-1r pattern -> red number circle
MAG, GRN, BLU, RED = "#ff00ff", "#008000", "#0000ff", "#ff0000"

# ------------------------------------------------------------------ geometry helpers (feet, x east, y north)
def unit(b):
    r = math.radians(b); return (math.sin(r), math.cos(r))
def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None
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
    def __init__(self, ax, lw=0.75):
        self.ax, self.lw = ax, lw

    def arrowhead(self, p, d, night, size=8.0):
        """notched (swallow-tail) TSU arrowhead; hollow = day, filled = night"""
        d = norm(d); n = right(d)
        a = add(add(p, d, -size), n, size * 0.4); b = add(add(p, d, -size), n, -size * 0.4); notch = add(p, d, -size * 0.55)
        self.ax.add_patch(Polygon([p, a, notch, b], closed=True, fc="black" if night else "white", ec="black", lw=self.lw, zorder=6))

    def speed_marks(self, pts, speed):
        """blue dots on the shaft from the tail: impact speed in tens; 70+ triple line; None -> blue X"""
        if speed is None:
            d = norm((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])); q = add(pts[0], d, 12)
            self.ax.plot(q[0], q[1], marker="x", ms=4, mew=1.0, color=BLU, zorder=7); return
        if speed >= 70:
            d = norm((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])); n = right(d)
            for k in (-1, 1):
                a, b = add(add(pts[0], d, 3), n, 1.6 * k), add(add(pts[0], d, 30), n, 1.6 * k)
                self.ax.plot([a[0], b[0]], [a[1], b[1]], color=BLU, lw=0.7, zorder=7)
            return
        n = min(int(speed // 10), 6)
        if n:
            dots, _ = resample(pts, 5.5)
            for x, y in dots[0:n]:
                self.ax.plot(x, y, "o", ms=2.2, color=BLU, zorder=7)

    def path(self, pts, night, speed, head=True):
        xs, ys = zip(*pts)
        self.ax.plot(xs, ys, color="black", lw=self.lw, solid_capstyle="round", zorder=5)
        if head:
            self.arrowhead(pts[-1], (pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]), night)
        self.speed_marks(pts, speed)

    def bar(self, p, d, half=5.5):
        n = right(norm(d)); a, b = add(p, n, half), add(p, n, -half)
        self.ax.plot([a[0], b[0]], [a[1], b[1]], color="black", lw=self.lw, zorder=6)

    def injury(self, p, sev):
        r = 3.6
        if sev in ("B", "C", "U"):
            self.ax.add_patch(Circle(p, r, fc="white", ec=RED, lw=1.0, zorder=8))
        elif sev == "A":
            self.ax.add_patch(Circle(p, r, fc="white", ec=RED, lw=1.0, zorder=8))
            self.ax.add_patch(Wedge(p, r, 0, 180, fc=RED, ec=RED, lw=0, zorder=8))
        elif sev == "K":
            self.ax.add_patch(Circle(p, r, fc=RED, ec=RED, lw=1.0, zorder=8))

    def number_circle(self, p, text, target=False):
        col = RED if target else "black"
        self.ax.add_patch(Circle(p, R_CIRC, fc="white", ec=col, lw=0.8, zorder=9))
        self.ax.text(p[0], p[1], text, ha="center", va="center", fontsize=7 if len(text) < 3 else 6, zorder=10, family="DejaVu Sans", color=col)

    def fault(self, p, h=3.2):
        """thin 8-spoke star, magenta (driver at fault)"""
        for a in (0, 45, 90, 135):
            d = (math.cos(math.radians(a)), math.sin(math.radians(a)))
            self.ax.plot([p[0] - d[0] * h, p[0] + d[0] * h], [p[1] - d[1] * h, p[1] + d[1] * h], color=MAG, lw=0.7, zorder=10)

    def roadcond(self, p, letter):
        self.ax.text(p[0], p[1], letter, ha="center", va="center", fontsize=8, color=GRN, zorder=10, family="DejaVu Sans")

    def zigzag_path(self, tail, d, side, L1=20.0, L2=26.0, amp=8.0):
        """ran-off-road: straight L1, zigzag, then straight L2 angled off to `side` (+1 right, -1 left)"""
        d = norm(d); n = right(d)
        a = add(tail, d, L1)
        z = [a, add(add(a, d, 5), n, amp * side), add(add(a, d, 12), n, -amp * side), add(add(a, d, 17), n, amp * side * 0.6), add(a, d, 21)]
        off = norm(rot(d, -35 * side))
        return [tail] + z + [add(z[-1], off, L2)]


# ------------------------------------------------------------------ crash -> glyph description
def speed_of(u):
    v = u.get("speed_impact")
    if v not in (None, ""): return float(v)
    v = u.get("speed_est")
    if v not in (None, ""): return float(v)
    return 0.0 if u.get("maneuver") == 1 else None


def at_fault_index(c):
    us = c["units"]
    cands = [i for i, u in enumerate(us) if u["violation"] not in (0, None)]
    return cands[0] if cands else 0


def charged(c):
    return [i for i, u in enumerate(c["units"]) if u["violation"] not in (0, None)]


def signature(c):
    us = c["units"]; f = at_fault_index(c)
    bins = tuple((u["direction"], u["maneuver"], None if speed_of(u) is None else min(int(speed_of(u) // 10), 7)) for u in us)
    return (c["acc_typ"], f, bins, c["lt_cond"] in NIGHT, ROADCOND.get(c["rd_cond"], "O"), SEV.get(c["severity_cd"], "U"))


def receiving_dir(t, left):
    """outward direction of the leg a vehicle travelling along t turns onto (left or right), on this skewed intersection"""
    best = None
    for leg, (bearing, _) in LEGS.items():
        u = unit(bearing); cross = t[0] * u[1] - t[1] * u[0]
        score = cross if left else -cross
        if best is None or score > best[0]: best = (score, u)
    return best[1]


def turn_path(P, t, left, R=TURN_R):
    """straight approach then a circular arc that ends at P heading along the receiving leg (49 or 131 deg sweep)"""
    u_r = receiving_dir(t, left)
    theta = math.degrees(math.atan2(t[0] * u_r[1] - t[1] * u_r[0], t[0] * u_r[0] + t[1] * u_r[1]))  # signed, CCW +
    nl = rot(t, 90 if theta > 0 else -90); v0 = (-nl[0] * R, -nl[1] * R)
    centre = add(P, rot(v0, theta), -1); start = add(centre, v0)
    steps = max(4, int(abs(theta) / 8))
    arc = [add(centre, rot(v0, theta * i / steps)) for i in range(steps + 1)]
    tail = add(start, t, -TURN_S)
    return [tail] + arc, tail, u_r


def draw_crash(g, P, c, numbers, key_pts, pending_notes=None):
    """Draw one glyph with impact point P for crash c (numbers = stacked crash numbers). Appends key points for the clearance check."""
    us = c["units"]; f = at_fault_index(c); night = c["lt_cond"] in NIGHT
    sev = SEV.get(c["severity_cd"], "U"); rc = ROADCOND.get(c["rd_cond"], "O"); typ = c["acc_typ"]
    tails = {}; pts_all = []; extra = []
    for i, u in enumerate(us):
        t = DIRV[u["direction"]]; sp = speed_of(u); m = u["maneuver"]; L = PATH_F if i == f else PATH_O
        if typ == 19:                                            # fixed object -> ran off road (after a turn if the unit was turning)
            if m in (7, 8):                                      # compact hook: tight turn, short zigzag off to the driver's right
                pts, tail, out = turn_path(P, t, m == 8, R=14.0); zz = g.zigzag_path(P, out, +1, L1=10.0, L2=14.0, amp=6.0)
                pts = pts + zz[1:]
            else:
                tail = add(P, t, -L); pts = g.zigzag_path(tail, t, +1)
            g.path(pts, night, sp); tails[i] = tail; pts_all += pts; continue
        if m == 1:                                               # stopped in travel lane: bar at the rear, short arrow ahead
            if typ == 21:
                q = P
            else:                                                # in an angle/turn crash the stopped unit sits in its own lane, short of the impact
                q = add(add(P, right(t), 8), t, -28)
            g.bar(q, t); pts = [q, add(q, t, STOP_ARROW)]; g.path(pts, night, sp); tails[i] = q; pts_all += pts
            extra += [add(q, right(t), 5.5), add(q, right(t), -5.5)]; continue
        if m in (7, 8):                                          # turning
            pts, tail, _ = turn_path(P, t, m == 8)
            g.path(pts, night, sp); tails[i] = tail; pts_all += pts; continue
        if typ == 21 and i != f and m in (4, 11):                # rear end lead vehicle (moving/slowing): bar at its rear
            g.bar(P, t); pts = [P, add(P, t, STOP_ARROW + 6)]; g.path(pts, night, sp); tails[i] = P; pts_all += pts; continue
        tail = add(P, t, -L)
        end = P if (i == f or typ == 21) else add(P, t, 12)       # struck unit continues a little past the impact point
        pts = [tail, add(end, t, -2) if (typ == 21 and i == f) else end]
        g.path(pts, night, sp); tails[i] = tail; pts_all += pts
    if sev in ("A", "B", "C", "K", "U"):
        g.injury(P if typ != 21 else add(P, DIRV[us[f]["direction"]], 6), sev)
    # number circle(s) side by side at the tail of the at-fault path; asterisk and road letter beside the first circle
    tf = DIRV[us[f]["direction"]]; tail = tails.get(f, add(P, tf, -PATH_F)); n = right(tf)
    base = add(tail, tf, -(R_CIRC + 1))
    circles = []
    for k, num in enumerate(numbers):
        cp = add(base, n, -k * (2 * R_CIRC + 2)); circles.append(cp)
        g.number_circle(cp, str(num), target=(typ in TARGET))
    if charged(c):
        q = add(add(base, n, R_CIRC + 4), tf, 2); g.fault(q); extra += [add(q, (1, 0), 3), add(q, (-1, 0), 3), add(q, (0, 1), 3), add(q, (0, -1), 3)]
    q = add(add(base, n, -(R_CIRC + 4) - (len(numbers) - 1) * (2 * R_CIRC + 2)), tf, 2); g.roadcond(q, rc)
    extra += [add(q, (1, 0), 3), add(q, (-1, 0), 3), add(q, (0, 1), 3), add(q, (0, -1), 3)]
    for i in charged(c):
        if i != f and i in tails:
            ti = DIRV[us[i]["direction"]]; q = add(add(tails[i], right(ti), 8), ti, -5); g.fault(q)
            extra += [add(q, (1, 0), 3), add(q, (-1, 0), 3), add(q, (0, 1), 3), add(q, (0, -1), 3)]
    for cp in circles:
        extra += [add(cp, unit(a), R_CIRC + 1) for a in range(0, 360, 45)]
    note = NOTES.get(c["crash_id"])
    if note and pending_notes is not None:
        pending_notes.append((c, note))
    key_pts.extend([P] + list(tails.values()) + circles + pts_all + extra)


def rect_dist(box, p):
    """distance from point p to the axis-aligned box (x0, y0, x1, y1); 0 inside"""
    dx = max(box[0] - p[0], 0.0, p[0] - box[2]); dy = max(box[1] - p[1], 0.0, p[1] - box[3])
    return math.hypot(dx, dy)


def seg_dist(p, a, b):
    ab = (b[0] - a[0], b[1] - a[1]); ap = (p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1]) / (ab[0] ** 2 + ab[1] ** 2)))
    return math.hypot(ap[0] - t * ab[0], ap[1] - t * ab[1])


def box_pts(box, k=3):
    (x0, y0, x1, y1) = box
    return [(x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * j / k) for i in range(k + 1) for j in range(k + 1) if i in (0, k) or j in (0, k)]


def place_notes(fig, ax, pending, glyph_pts, fontsize=6.0):
    """Put each crash note beside its glyph where it touches nothing: try outward / inward along the leg and laterally away
    from the road, with every text alignment, and keep the position with the largest clearance from the other glyphs,
    the pavement and the notes already placed. Returns [(name, corner points)] for the clearance report."""
    fig.canvas.draw(); rend = fig.canvas.get_renderer(); inv = ax.transData.inverted()
    pts_by_name = dict(glyph_pts); placed = []
    roads = [((0.0, 0.0), add((0.0, 0.0), unit(b), 700.0), (W_MAIN if leg in ("N", "S") else W_SIDE) / 2) for leg, (b, _) in LEGS.items()]
    for c, text in pending:
        name = next(nm for nm, _ in glyph_pts if nm.split(",")[0] == str(c["no"]) or str(c["no"]) in nm.split(","))
        own = pts_by_name[name]; leg = leg_of(c)
        ov = unit(LEGS[leg][0]); n = right((-ov[0], -ov[1])); lv = (n[0] * SIDE[leg], n[1] * SIDE[leg])
        probe = ax.text(0, 0, text, fontsize=fontsize, ha="left", va="bottom", linespacing=1.2, family="DejaVu Sans")
        bb = probe.get_window_extent(rend); (x0, y0), (x1, y1) = inv.transform([[bb.x0, bb.y0], [bb.x1, bb.y1]]); probe.remove()
        w, h = x1 - x0, y1 - y0
        others = [p for nm, pts in glyph_pts if nm != name for p in pts] + [p for _, pts in placed for p in pts]
        anchors = [add(max(own, key=lambda p: p[0] * ov[0] + p[1] * ov[1]), ov, 9.0),
                   add(min(own, key=lambda p: p[0] * ov[0] + p[1] * ov[1]), ov, -9.0),
                   add(max(own, key=lambda p: p[0] * lv[0] + p[1] * lv[1]), lv, 9.0)]
        best = None
        for a in anchors:
            for fx in (0.0, 0.5, 1.0):
                for fy in (0.0, 0.5, 1.0):
                    box = (a[0] - fx * w, a[1] - fy * h, a[0] + (1 - fx) * w, a[1] + (1 - fy) * h)
                    corners = box_pts(box)
                    d_other = min(rect_dist(box, p) for p in others)
                    d_own = min(rect_dist(box, p) for p in own)
                    d_road = min(seg_dist(q, s0, s1) - hw for q in corners for s0, s1, hw in roads)
                    score = min(d_other, d_road, d_own + 6.0)                      # own glyph may sit closer than the others
                    if best is None or score > best[0]: best = (score, box)
        score, box = best
        ax.text(box[0], box[1], text, fontsize=fontsize, ha="left", va="bottom", linespacing=1.2, family="DejaVu Sans", zorder=9,
                bbox=dict(fc="white", ec="none", pad=0.4))
        placed.append((f"note{c['no']}", box_pts(box)))
        if score < 6.0: print(f"  note for crash #{c['no']} placed with only {score:.0f} ft clearance")
    return placed


# ------------------------------------------------------------------ layout
SIDE = {"NW": +1, "SE": +1, "N": -1, "S": -1}     # +1 = driver's right of the approach; chosen so glyphs fall in the open (obtuse) wedges
ROW0, PITCH, COLS, ROWS = 95.0, 105.0, (32.0, 114.0, 196.0, 278.0), 4


def opposite(leg):
    return {"N": "S", "S": "N", "NW": "SE", "SE": "NW"}[leg]


def leg_of(c):
    u = c["units"][at_fault_index(c)]; leg = APPROACH[u["direction"]]
    if c["acc_typ"] == 19 and num(c.get("dist_from")) and num(c["dist_from"]) > 0 and c.get("dir_from"):
        return opposite(leg)                                    # single-vehicle run-off-road referenced past the intersection: departure leg
    return leg


def layout(crashes):
    """Group identical crashes, then stack each leg's glyphs back from the intersection in columns beside the approach lane."""
    groups = {}
    for c in crashes:
        groups.setdefault(signature(c), []).append(c)
    per_leg = {}
    for sig, cs in sorted(groups.items(), key=lambda kv: kv[1][0]["no"]):
        per_leg.setdefault(leg_of(cs[0]), []).append((cs, cs[0]))
    placed = []
    for leg, items in per_leg.items():
        u = unit(LEGS[leg][0]); t = (-u[0], -u[1]); n = right(t)
        half_w = W_MAIN / 2 if leg in ("N", "S") else W_SIDE / 2
        for k, (cs, c0) in enumerate(items):
            col, row = k // ROWS, k % ROWS
            P = add(add((0, 0), u, ROW0 + PITCH * row), n, SIDE[leg] * (half_w + COLS[col % len(COLS)]))
            placed.append((P, c0, [c["no"] for c in cs]))
    return placed


def clearance_report(glyph_pts, min_ft=22.0):
    """pairs of glyphs with any key points closer than min_ft (printed for QA)"""
    bad = []
    for i in range(len(glyph_pts)):
        for j in range(i + 1, len(glyph_pts)):
            a, pa = glyph_pts[i]; b, pb = glyph_pts[j]
            d = min(math.hypot(x[0] - y[0], x[1] - y[1]) for x in pa for y in pb)
            if d < min_ft: bad.append((a, b, round(d)))
    return bad


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
    for leg, half in (("N", W_SIDE / 2 + 12), ("S", W_SIDE / 2 + 12)):   # NC 180: double solid centreline (no-passing zone)
        u = legs[leg]; nn = right(u)
        for k in (-1, 1):
            a = add(add((0, 0), u, half), nn, 0.9 * k); b = add(add((0, 0), u, L), nn, 0.9 * k)
            ax.plot([a[0], b[0]], [a[1], b[1]], color="black", lw=0.5, zorder=2)
    for leg in ("NW", "SE"):
        u = legs[leg]; a = add((0, 0), u, W_MAIN / 2 + 2); b = add((0, 0), u, L)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="black", lw=0.6, ls=(0, (8, 6)), zorder=2)
        # stop bar across the approach lane and STOP sign on the right of the approach
        t = (-u[0], -u[1]); n = right(t); sb = add((0, 0), u, W_MAIN / 2 + 6)
        ax.plot([sb[0], add(sb, n, W_SIDE / 2)[0]], [sb[1], add(sb, n, W_SIDE / 2)[1]], color="black", lw=2.6, zorder=3)
        sp = add(add((0, 0), u, W_MAIN / 2 + 14), n, W_SIDE / 2 + 12)
        ax.add_patch(RegularPolygon(sp, 8, radius=9, orientation=math.radians(22.5), fc=RED, ec="black", lw=0.6, zorder=4))
        ax.text(sp[0], sp[1], "STOP", ha="center", va="center", fontsize=3.8, color="white", fontweight="bold", zorder=5)


# ------------------------------------------------------------------ sheet furniture (page axes, inches)
def legend(px, x0, y0, w=6.6, h=2.55):
    px.add_patch(Rectangle((x0, y0), w, h, fc="white", ec="black", lw=0.8, zorder=3))
    px.text(x0 + w / 2, y0 + h - 0.22, "LEGEND", ha="center", va="center", fontsize=12, style="italic", zorder=4)
    px.plot([x0 + w / 2 - 0.55, x0 + w / 2 + 0.55], [y0 + h - 0.36, y0 + h - 0.36], color="black", lw=0.6, zorder=4)
    def arrow(x, y, L=0.42, night=False, dots=0, tri=False, unk=False, head=True):
        px.plot([x, x + L], [y, y], color="black", lw=0.8, zorder=4)
        if head:
            px.add_patch(Polygon([(x + L, y), (x + L - 0.11, y + 0.045), (x + L - 0.06, y), (x + L - 0.11, y - 0.045)], fc="black" if night else "white", ec="black", lw=0.6, zorder=5))
        for i in range(dots):
            px.plot(x + 0.06 + i * 0.05, y, "o", ms=2.2, color=BLU, zorder=5)
        if tri:
            for dy in (-0.02, 0, 0.02): px.plot([x, x + L - 0.11], [y + dy, y + dy], color=BLU, lw=0.7, zorder=5)
        if unk: px.plot(x + 0.15, y, marker="x", ms=4, color=BLU, mew=1, zorder=5)
    fs = 5.6; cx = x0 + 0.15; cy = y0 + h - 0.6; dy = 0.212
    rows = [("MOVING VEHICLE", lambda x, y: arrow(x, y)),
            ("PARKED VEHICLE", lambda x, y: (px.add_patch(Rectangle((x, y - 0.07), 0.3, 0.14, fc="white", ec="black", lw=0.7, zorder=5)),
                                            px.plot([x, x + 0.3], [y - 0.07, y + 0.07], color="black", lw=0.6, zorder=5), px.plot([x, x + 0.3], [y + 0.07, y - 0.07], color="black", lw=0.6, zorder=5))),
            ("PARKING VEHICLE", lambda x, y: (px.add_patch(Rectangle((x, y - 0.07), 0.3, 0.14, fc="white", ec="black", lw=0.7, zorder=5)),
                                             px.plot([x, x + 0.3], [y - 0.07, y + 0.07], color="black", lw=0.6, zorder=5), px.plot([x, x + 0.3], [y + 0.07, y - 0.07], color="black", lw=0.6, zorder=5),
                                             px.plot([x + 0.3, x + 0.42], [y + 0.07, y + 0.17], color="black", lw=0.7, zorder=5),
                                             px.add_patch(Polygon([(x + 0.44, y + 0.19), (x + 0.36, y + 0.18), (x + 0.42, y + 0.11)], fc="white", ec="black", lw=0.6, zorder=5)))),
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
    px.text(base[0] - d[0] * 0.14, base[1] - d[1] * 0.14, "N", ha="center", va="center", fontsize=8, zorder=6)


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
    for leg, (xi, yi) in {"N": (9.55, 6.5), "S": (2.0, 0.95), "NW": (1.25, 9.85), "SE": (10.3, 1.15)}.items():
        px.text(xi, yi, "\n".join(LEGS[leg][1]), ha="center", va="center", fontsize=8, linespacing=1.25, zorder=4, family="DejaVu Sans")
    g = G(ax)
    placed = layout(CR); glyph_pts = []; pending = []
    for P, c, nums in placed:
        kp = []; draw_crash(g, P, c, nums, kp, pending); glyph_pts.append((",".join(map(str, nums)), kp))
    glyph_pts += place_notes(fig, ax, pending, glyph_pts)
    # furniture
    legend(px, 16.65 - 6.6, 10.65 - 2.55)
    px.add_patch(Rectangle((12.3, 7.45), 2.3, 0.42, fc="white", ec="black", lw=0.7, zorder=3))
    px.add_patch(Circle((12.55, 7.66), 0.11, fc="white", ec=RED, lw=0.9, zorder=4)); px.text(12.55, 7.66, "#", ha="center", va="center", fontsize=7, color=RED, zorder=5)
    px.text(12.75, 7.66, "Target Crashes (frontal impact)", va="center", fontsize=7, color=RED, zorder=5)
    title_block(px, 16.65 - 3.3, 0.3)
    north_arrow(px, 15.8, 5.0)
    px.text(2.0, 3.0, f"PH# {PH_NO}\nOrder# {STUDY}\n{COUNTY}\n{LOCATION}\n{PERIOD}", ha="center", va="center", fontsize=11, linespacing=1.3, zorder=5, family="DejaVu Sans")
    # notes box
    n_stack = sum(1 for _, _, nums in placed if len(nums) > 1)
    sev = [SEV[c["severity_cd"]] for c in CR]; night = sum(c["lt_cond"] in NIGHT for c in CR); wet = sum(c["rd_cond"] == 2 for c in CR)
    front = sum(c["acc_typ"] in TARGET for c in CR)
    notes = [f"NOTES: {len(CR)} crashes 9/1/2016-8/31/2026: {sev.count('K')} K, {sev.count('A')} A, {sev.count('B')} B, {sev.count('C')} C, {sev.count('O')} PDO; "
             f"{front} frontal impact (target), {night} dark, {wet} wet.",
             "Crash numbers follow the TEAAS Intersection Analysis Report (by date). Speed dots = impact speed. Red circle = frontal impact target crash.",
             "Crash 8 (106808749) is referenced on SR 1103 at MP 3.019, 0.1 mi W of SR 2205; included after fiche review. Crash 21 (107960640) is",
             "unmileposted (SR 1103 at SR 1103) and was located by DMV-349 coordinates 170 ft from the intersection. Crash 28: both drivers charged.",
             "Diagram not to scale. Fiche review excluded 7 crashes (3 animal, 2 fixed object, 1 sideswipe, 1 left turn) as not intersection related."]
    import textwrap
    wrapped = "\n".join(textwrap.fill(n, 96) for n in notes)
    px.text(10.1, 7.3, wrapped, fontsize=6.2, va="top", ha="left", zorder=5, family="DejaVu Sans", linespacing=1.3,
            bbox=dict(fc="white", ec="black", lw=0.6, pad=4))
    fig.savefig(OUT / "5_collision_diagram_NCDOT.png", dpi=150)
    fig.savefig(OUT / ".review_300dpi.png", dpi=300)
    # page 2: crash listing
    fig2 = plt.figure(figsize=(17, 11)); p2 = fig2.add_axes([0, 0, 1, 1]); p2.set_xlim(0, 17); p2.set_ylim(0, 11); p2.set_axis_off()
    p2.add_patch(Rectangle((0.25, 0.25), 16.5, 10.5, fc="white", ec="black", lw=1.2, zorder=1))
    p2.text(8.5, 10.3, f"Crash listing - Order# {STUDY}, {LOCATION.replace(chr(10), ' ')}, {PERIOD}", ha="center", va="center", fontsize=12, fontweight="bold")
    LIGHT = {1: "Daylight", 2: "Dusk", 3: "Dawn", 4: "Dark-lighted", 5: "Dark-not lighted", 6: "Dark-unknown"}
    ROAD = {1: "Dry", 2: "Wet", 3: "Water", 4: "Ice", 5: "Snow"}
    MAN = {1: "stopped", 4: "straight", 7: "right turn", 8: "left turn", 11: "slowing"}
    VIOL = {0: "", 2: "disregarded stop sign", 8: "failure to reduce speed", 14: "overcorrected", 19: "failed to yield ROW", 20: "inattention", 26: "erratic/reckless"}
    rows = [["No", "Crash ID", "Date", "Time", "Crash type", "Sev", "Light", "Road", "Units (dir / maneuver / impact mph / contributing circumstance)", "Target"]]
    import csv as _csv
    for c in CR:
        units = "; ".join(f"U{u['unit']} {u['direction']} {MAN.get(u['maneuver'], u['maneuver'])} {u['speed_impact']} mph{(' - ' + VIOL[u['violation']]) if u['violation'] else ''}" for u in c["units"])
        rows.append([str(c["no"]), c["crash_id"], c["date"], c["time"], TYPE[c["acc_typ"]], {"O": "PDO"}.get(SEV[c["severity_cd"]], SEV[c["severity_cd"]]),
                     LIGHT.get(c["lt_cond"], c["lt_cond"]), ROAD.get(c["rd_cond"], c["rd_cond"]), units, "yes" if c["acc_typ"] in TARGET else ""])
    with open(HERE / "review" / "collision_diagram_listing.csv", "w", newline="") as f:
        _csv.writer(f).writerows(rows)
    tbl = p2.table(cellText=rows[1:], colLabels=rows[0], loc="center", bbox=[0.03, 0.04, 0.94, 0.88],
                   colWidths=[0.03, 0.07, 0.07, 0.045, 0.16, 0.035, 0.08, 0.045, 0.42, 0.045], cellLoc="left")
    tbl.auto_set_font_size(False); tbl.set_fontsize(7); tbl.set_zorder(3)
    for (r, cidx), cell in tbl.get_celld().items():
        cell.set_edgecolor("#999"); cell.set_linewidth(0.4)
        if r == 0: cell.set_text_props(fontweight="bold"); cell.set_facecolor("#eeeeee")
    from matplotlib.backends.backend_pdf import PdfPages
    with PdfPages(OUT / "5_collision_diagram_NCDOT.pdf") as pdf:
        pdf.savefig(fig); pdf.savefig(fig2)
    fig2.savefig(OUT / "5b_collision_diagram_listing.png", dpi=150)
    plt.close(fig); plt.close(fig2)
    print(f"{len(CR)} crashes, {len(placed)} glyphs ({n_stack} stacked)")
    bad = clearance_report(glyph_pts)
    print("clearance (<22 ft between glyph key points):", bad if bad else "none")
    for P, c, nums in placed:
        print(f"  #{','.join(map(str, nums)):10} {TYPE.get(c['acc_typ'], c['acc_typ']):32} leg {leg_of(c):2} P=({P[0]:.0f},{P[1]:.0f})")


if __name__ == "__main__":
    main()
