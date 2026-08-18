"""NCDOT Traffic Safety Unit collision diagram, mimicking the MicroStation format.

The TSU workflow pairs a seed DGN (``Template.CollisionDiagram 11x17.dgn``)
with a per-unit CSV (``<WO>_CollisionDiagramData.txt``) whose columns follow
the TEAAS database schema: CRSH_ID, CNTY_NBR, MLPST_NBR, NBR_UNT_CNT,
FRM_RD_CD, RD_ON_CD, DSTNC_MILE_FRM_RD_QTY, DRCTN_FRM_RD_CD, ACDNT_DT_TM,
SVRTY_CD, ACC_TYP, RD_CONFIG, RD_COND, LT_COND, TRFC_CTRL, SPD_LMT_NBR,
SPD_EST_NBR, SPD_AT_IMPCT_NBR, MANEUVER, VIOLATION, DIRECT, UNT_NBR.
One row per unit, two rows for a two-unit crash.

This module reads (and writes) that CSV and renders the finished sheet the
way the completed deliverables look (verified against 41000077084 and
41000077748): 11x17 landscape, LEGEND box top right, study title block,
schematic roadway, per-crash arrow assemblies with the standard symbology
(open arrowhead daylight / filled night, speed dots by 10 mph band with the
70-and-up bar, severity circles open/half/filled at the point of impact,
green surface letter, magenta at-fault asterisk, numbered circle badge),
the needle north arrow, and the NCDOT / TRAFFIC SAFETY UNIT / VHB title
block bottom right.

Glyph semantics come from the TEAAS accident type codes (docs/09):
1 ROR-R, 2 ROR-L, 3 ROR-T, 4 jackknife, 5 overturn, 13 other, 14 pedestrian,
15 cyclist, 16 railroad, 17 animal, 18 movable object, 19 fixed object,
20 parked vehicle, 21 rear end, 22 rear end turning, 23 LTSR, 24 LTDR,
25 RTSR, 26 RTDR, 27 head on, 28 SSSD, 29 SSOD, 30 angle, 31 backing.

Severity codes 1..5 map K/A/B/C/O; light condition 1 is daylight and
everything else prints the filled night arrowhead; road condition prints
D (1), W (2, 3), I (4, 5, 6), O otherwise.

Output is a single-file HTML page (inline SVG) printed to PDF by the same
Playwright step the package maps use, at a 17in x 11in page.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import math
import os
from dataclasses import dataclass, field

PAGE_W, PAGE_H = 1632, 1056

RED = "#E10000"
MAGENTA = "#FF00C8"
GREEN = "#007A00"
BLUE = "#2222CC"

try:
    from HersheyFonts import HersheyFonts as _HersheyFonts
    _HFONT = _HersheyFonts()
    _HFONT.load_default_font("futural")
except Exception:                                    # pragma: no cover
    _HFONT = None


def _stroke_text(x, y, text, size=14, anchor="middle", color="#000",
                 sw=None, slant=0.0):
    """Lettering as pen strokes (Hershey simplex), the plotter look of
    MicroStation font 3 on the TSU sheets. ``y`` is the vertical center
    of the rendered line. Falls back to plain SVG text without the
    optional HersheyFonts dependency."""
    text = str(text)
    if _HFONT is None or not text.strip():
        return (f'<text x="{x:.1f}" y="{y + size * 0.36:.1f}" '
                f'font-size="{size}" fill="{color}" '
                f'text-anchor="{anchor}">{text}</text>')
    _HFONT.normalize_rendering(size * 1.28)
    segs = list(_HFONT.lines_for_text(text))
    if not segs:
        return ""
    segs = [((x1, -y1), (x2, -y2)) for (x1, y1), (x2, y2) in segs]
    xs = [c for sg in segs for c in (sg[0][0], sg[1][0])]
    ys = [c for sg in segs for c in (sg[0][1], sg[1][1])]
    w = max(xs) - min(xs)
    dx = -min(xs) + (-w / 2 if anchor == "middle"
                     else -w if anchor == "end" else 0)
    dy = -(min(ys) + max(ys)) / 2
    d = " ".join(f"M{x1 + dx:.1f} {y1 + dy:.1f} L{x2 + dx:.1f} "
                 f"{y2 + dy:.1f}" for (x1, y1), (x2, y2) in segs)
    sk = f" skewX({-slant})" if slant else ""
    return (f'<g transform="translate({x:.1f},{y:.1f}){sk}">'
            f'<path d="{d}" stroke="{color}" '
            f'stroke-width="{sw if sw is not None else max(0.8, size / 15):.2f}" '
            'stroke-linecap="round" fill="none"/></g>')


ROR_TYPES = {1, 2, 3, 4, 5}
SINGLE_UNIT_TYPES = ROR_TYPES | {13, 17, 18, 19, 20, 32}
TURN_TYPES = {22, 23, 24, 25, 26}


@dataclass
class Unit:
    number: int
    direction: str = ""
    speed: int | None = None
    maneuver: int | None = None


@dataclass
class DiagramCrash:
    crash_id: str
    seq: int = 0
    mp: float | None = None
    dt: str = ""
    severity: str = "O"          # K A B C O
    acc_typ: int = 0
    road_cond: str = "D"         # D W I O
    night: bool = False
    units: list[Unit] = field(default_factory=list)
    note: str = ""


def severity_from_code(code) -> str:
    try:
        return {1: "K", 2: "A", 3: "B", 4: "C"}.get(int(code), "O")
    except (TypeError, ValueError):
        return "O"


def road_cond_letter(code) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "D"
    if c == 1:
        return "D"
    if c in (2, 3):
        return "W"
    if c in (4, 5, 6):
        return "I"
    return "O"


def read_data_csv(path: str) -> list[DiagramCrash]:
    """Read a CollisionDiagramData CSV (one row per unit) into crashes."""
    by_id: dict[str, DiagramCrash] = {}
    order: list[str] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("CRSH_ID") or "").strip()
            if not cid:
                continue
            cr = by_id.get(cid)
            if cr is None:
                mp_raw = (row.get("MLPST_NBR") or "").strip()
                mp = float(mp_raw) if mp_raw not in ("", "999.999") else None
                cr = DiagramCrash(
                    crash_id=cid, mp=mp,
                    dt=(row.get("ACDNT_DT_TM") or "").strip(),
                    severity=severity_from_code(row.get("SVRTY_CD")),
                    acc_typ=int(row.get("ACC_TYP") or 0),
                    road_cond=road_cond_letter(row.get("RD_COND")),
                    night=(row.get("LT_COND") or "1").strip() != "1",
                )
                by_id[cid] = cr
                order.append(cid)
            spd = (row.get("SPD_EST_NBR") or "").strip()
            cr.units.append(Unit(
                number=int(row.get("UNT_NBR") or len(cr.units) + 1),
                direction=(row.get("DIRECT") or "").strip().upper(),
                speed=int(spd) if spd.isdigit() else None,
                maneuver=int(row.get("MANEUVER") or 0) or None,
            ))
    crashes = [by_id[c] for c in order]
    crashes.sort(key=lambda c: (c.dt and _sortable_dt(c.dt)) or "")
    for i, cr in enumerate(crashes, start=1):
        cr.seq = i
        cr.units.sort(key=lambda u: u.number)
    return crashes


def _sortable_dt(dt: str) -> str:
    try:
        from datetime import datetime
        return datetime.strptime(dt, "%m/%d/%Y %H:%M").isoformat()
    except ValueError:
        return dt


def write_data_csv(path: str, crashes: list[DiagramCrash], county_nbr="",
                   on_road_cd="", from_road_cd="") -> None:
    cols = ["CRSH_ID", "CNTY_NBR", "MLPST_NBR", "NBR_UNT_CNT", "FRM_RD_CD",
            "RD_ON_CD", "DSTNC_MILE_FRM_RD_QTY", "DRCTN_FRM_RD_CD",
            "ACDNT_DT_TM", "SVRTY_CD", "ACC_TYP", "RD_CONFIG", "RD_COND",
            "LT_COND", "TRFC_CTRL", "SPD_LMT_NBR", "SPD_EST_NBR",
            "SPD_AT_IMPCT_NBR", "MANEUVER", "VIOLATION", "DIRECT", "UNT_NBR"]
    sev_code = {"K": 1, "A": 2, "B": 3, "C": 4, "O": 5}
    cond_code = {"D": 1, "W": 2, "I": 4, "O": 9}
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(cols)
    for cr in crashes:
        for u in cr.units or [Unit(1)]:
            w.writerow([
                cr.crash_id, county_nbr,
                f"{cr.mp:.3f}" if cr.mp is not None else "999.999",
                len(cr.units) or 1, from_road_cd, on_road_cd, "0", "",
                cr.dt, sev_code.get(cr.severity, 5), cr.acc_typ, "2",
                cond_code.get(cr.road_cond, 1), "1" if not cr.night else "5",
                "1", "", u.speed if u.speed is not None else "",
                "", u.maneuver or "", "", u.direction, u.number])
    with open(path, "w", newline="") as fh:
        fh.write(buf.getvalue())


# ------------------------------------------------------------------ TEAAS
_TYPE_TEXT = [
    ("RAN OFF ROAD - RIGHT", 1), ("RAN OFF ROAD - LEFT", 2),
    ("RAN OFF ROAD - STRAIGHT", 3), ("JACKKNIFE", 4),
    ("OVERTURN", 5), ("PEDESTRIAN", 14), ("PEDALCYCLIST", 15),
    ("RAIL", 16), ("ANIMAL", 17), ("MOVABLE OBJECT", 18),
    ("FIXED OBJECT", 19), ("PARKED MOTOR VEHICLE", 20),
    ("REAR END, TURN", 22), ("REAR END", 21),
    ("LEFT TURN, SAME", 23), ("LEFT TURN, DIFFERENT", 24),
    ("RIGHT TURN, SAME", 25), ("RIGHT TURN, DIFFERENT", 26),
    ("HEAD ON", 27), ("SIDESWIPE, SAME", 28), ("SIDESWIPE, OPPOSITE", 29),
    ("ANGLE", 30), ("BACKING", 31),
]


def acc_type_code(text: str) -> int:
    t = (text or "").upper()
    for key, code in _TYPE_TEXT:
        if key in t:
            return code
    return 13


def crashes_from_initial_study(path: str) -> list[DiagramCrash]:
    """Build crashes from a TEAAS strip Initial Study CSV.

    Crash rows carry Acc No, Crash ID, Milepost, Date, Accident Type, damage,
    injury counts F A B C, then the code columns where Condition is the light
    code (1 daylight) and W is the weather code (3 and 5 print as wet).
    ``Unit`` continuation rows carry per-unit speed, direction and maneuver.
    """
    crashes: list[DiagramCrash] = []
    cur: DiagramCrash | None = None
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for cells in csv.reader(fh):
            cells = [c.strip() for c in cells]
            if len(cells) > 4 and cells[0].isdigit() and \
                    len(cells[1]) == 9 and cells[1].isdigit():
                dmg_i = 6 if cells[5] == "$" else 5
                f, a, b, c = (int(x or 0) for x in
                              cells[dmg_i + 1:dmg_i + 5])
                sev = ("K" if f else "A" if a else "B" if b else
                       "C" if c else "O")
                light = cells[dmg_i + 6] if len(cells) > dmg_i + 6 else "1"
                weather = cells[dmg_i + 8] if len(cells) > dmg_i + 8 else "1"
                cur = DiagramCrash(
                    crash_id=cells[1],
                    mp=float(cells[2]) if cells[2] else None,
                    dt=cells[3], severity=sev,
                    acc_typ=acc_type_code(cells[4]),
                    road_cond="W" if weather in ("3", "5") else "D",
                    night=light != "1")
                crashes.append(cur)
            elif cells and cells[0] == "Unit" and cur is not None:
                rec = {}
                for i, cell in enumerate(cells):
                    if cell in ("Speed:", "Dir:", "Veh Mnvr/Ped Actn:"):
                        rec[cell] = cells[i + 1] if i + 1 < len(cells) else ""
                spd = rec.get("Speed:", "")
                cur.units.append(Unit(
                    number=len(cur.units) + 1,
                    direction=rec.get("Dir:", "").upper(),
                    speed=int(spd) if spd.isdigit() else None,
                    maneuver=int(rec.get("Veh Mnvr/Ped Actn:") or 0) or None))
    return crashes


# -------------------------------------------------------------------- SVG
# ------------------------------------------------------------ cell sizes
# Every crash is drawn from the same rigid parts, the way the TSU cell
# library places them (NCDOT "Collision Diagrams" training deck, rev
# 1/18/2013, Breakdown of Plotted Crash Components): one shaft length per
# unit, one arrowhead, one bubble, one decor offset, one severity circle.
# Only the cell's rotation and which parts are present change with the
# crash type, so a sheet reads as one drafted set.
CELL_SHAFT = 50.0        # tail start to arrow tip, identical for every unit
CELL_HEAD = 8.6          # arrowhead length, measured inside the shaft
BUBBLE_R = 8.0           # crash number circle
BUBBLE_GAP = 1.0         # bubble edge to tail start, near enough to touch
DECOR_S = 9.0            # station along the shaft for the asterisk/letter
DECOR_N = 7.2            # offset off the shaft for the asterisk/letter
SEV_GAP = 5.0            # arrow tip to severity circle center
SEV_R = 3.9
LANE_SEP = 11.0          # lateral separation of two units drawn side by side
TICK_H = 5.2             # half length of the point of impact tick
DEPART_ANG = 26.0        # cell rotation off the travel line for a departure
ROAD_GAP = 13.0          # clear space between the centerline and any ink
DOT_R = 1.35
DOT_PITCH = 7.4


def _arrowhead(x, y, ang, night):
    """Vehicle head: open for a daylight crash, filled for a night one."""
    fill = "#000" if night else "#fff"
    h = CELL_HEAD
    pts = [(0, 0), (-h, 3.0), (-h * 0.80, 0), (-h, -3.0)]
    cos, sin = math.cos(ang), math.sin(ang)
    p = " ".join(f"{x + px * cos - py * sin:.1f},{y + px * sin + py * cos:.1f}"
                 for px, py in pts)
    return (f'<polygon points="{p}" fill="{fill}" stroke="#000" '
            'stroke-width="1.1"/>')


def _speed_run(x0, y0, cos, sin, s_lo, s_hi, speed):
    """Speed band marks on a shaft: one dot per full 10 mph and none
    under 10, the triple line at 70 and up, a blue x when the speed is
    unknown. Dots keep one pitch and one radius on every cell and center
    themselves in the run they are given (training deck page 25)."""
    mid = (s_lo + s_hi) / 2.0
    if speed is None:
        return _stroke_text(x0 + mid * cos, y0 + mid * sin, "x", size=9,
                            color=BLUE)
    try:
        spd = int(speed)
    except (TypeError, ValueError):
        return ""
    if spd >= 70:
        nx, ny = -sin * 2.1, cos * 2.1
        out = []
        for k in (-1, 0, 1):
            out.append(
                f'<line x1="{x0 + s_lo * cos + nx * k:.1f}" '
                f'y1="{y0 + s_lo * sin + ny * k:.1f}" '
                f'x2="{x0 + s_hi * cos + nx * k:.1f}" '
                f'y2="{y0 + s_hi * sin + ny * k:.1f}" '
                f'stroke="{BLUE}" stroke-width="1.4"/>')
        return "".join(out)
    n = min(6, spd // 10)
    if n < 1:
        return ""
    pitch = DOT_PITCH
    if n > 1:                       # a short run tightens the pitch rather
        pitch = min(pitch, (s_hi - s_lo) / (n - 1))    # than spilling out
        pitch = max(pitch, 3.4)
    first = mid - (n - 1) * pitch / 2.0
    return "".join(
        f'<circle cx="{x0 + (first + k * pitch) * cos:.1f}" '
        f'cy="{y0 + (first + k * pitch) * sin:.1f}" '
        f'r="{DOT_R}" fill="{BLUE}"/>' for k in range(n))


def _speed_marks(x0, y0, x1, y1, speed):
    """Speed marks along a drawn segment (used by the legend rows)."""
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy) or 1.0
    return _speed_run(x0, y0, dx / ln, dy / ln, 0.0, ln, speed)


def _unit_cell(tx, ty, ang_deg, unit, night, zigzag=False,
               shaft=CELL_SHAFT, swerve=0.0):
    """One vehicle drawn from its tail start toward ``ang_deg``.

    The shaft is always ``shaft`` long tail to tip, so cells of different
    crash types stack the same. ``zigzag`` breaks the middle of the shaft
    for a run off road without changing its length, and ``swerve`` jogs
    the shaft sideways near the head for a sideswipe. Returns the svg,
    the tip point, and the ink points the caller needs for its bounds.
    """
    a = math.radians(ang_deg)
    c, s = math.cos(a), math.sin(a)
    nx, ny = -s, c                      # right of travel, page coordinates

    def P(u, v=0.0):
        return (tx + u * c + v * nx, ty + u * s + v * ny)

    out = []
    ink = [P(0.0)]
    mark_lo, mark_hi = 2.0, shaft - CELL_HEAD - 2.0
    if zigzag:
        # the break sits late on the shaft, the way the drawn sheets put
        # it, so the speed marks keep a clean run off the tail
        z0 = shaft - CELL_HEAD - 15.0
        pts = [P(0.0), P(z0), P(z0 + 4, -6.5), P(z0 + 9, 6.5),
               P(z0 + 13), P(shaft)]
        ink += [P(z0 + 4, -6.5), P(z0 + 9, 6.5)]
        mark_hi = z0 - 2.5
        d = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        out.append(f'<polyline points="{d}" fill="none" stroke="#000" '
                   'stroke-width="1.1"/>')
        tip = P(shaft)
    elif swerve:
        pts = [P(0.0), P(shaft * 0.5), P(shaft * 0.66, swerve),
               P(shaft, swerve)]
        ink.append(P(shaft * 0.66, swerve))
        mark_hi = shaft * 0.46
        d = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        out.append(f'<polyline points="{d}" fill="none" stroke="#000" '
                   'stroke-width="1.1"/>')
        tip = P(shaft, swerve)
    else:
        tip = P(shaft)
        out.append(f'<line x1="{tx:.1f}" y1="{ty:.1f}" x2="{tip[0]:.1f}" '
                   f'y2="{tip[1]:.1f}" stroke="#000" stroke-width="1.1"/>')
    if mark_hi - mark_lo > 4:
        out.append(_speed_run(tx, ty, c, s, mark_lo, mark_hi, unit.speed))
    out.append(_arrowhead(tip[0], tip[1], a, night))
    ink.append(tip)
    return "".join(out), tip, ink


def _unit_arrow(x, y, ang_deg, length, unit, night, zigzag=False):
    """Back compatible wrapper: svg and tip for one unit."""
    svg, tip, _ = _unit_cell(x, y, ang_deg, unit, night, zigzag=zigzag,
                             shaft=length)
    return svg, tip


def _severity_circle(x, y, sev):
    """Injury indicator at the front of the cell: open for a non severe
    injury, half filled for a severe one, solid for a fatality."""
    if sev == "O":
        return ""
    if sev == "K":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{SEV_R}" fill="{RED}"/>'
    if sev == "A":
        return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{SEV_R}" fill="#fff" '
                f'stroke="{RED}" stroke-width="1.5"/>'
                f'<path d="M {x - SEV_R:.1f} {y:.1f} A {SEV_R} {SEV_R} 0 0 0 '
                f'{x + SEV_R:.1f} {y:.1f} Z" fill="{RED}"/>')
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{SEV_R}" fill="#fff" '
            f'stroke="{RED}" stroke-width="1.5"/>')


def _badge(x, y, n):
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{BUBBLE_R}" fill="#fff" '
            'stroke="#000" stroke-width="1.0"/>'
            + _stroke_text(x, y, n, size=8.5))


def _impact_tick(x, y, ang_deg):
    """Point of impact bar, drawn across the travel line."""
    a = math.radians(ang_deg)
    nx, ny = -math.sin(a) * TICK_H, math.cos(a) * TICK_H
    return (f'<line x1="{x - nx:.1f}" y1="{y - ny:.1f}" '
            f'x2="{x + nx:.1f}" y2="{y + ny:.1f}" stroke="#000" '
            'stroke-width="1.1"/>')


_DIR_ANG = {"E": 0, "NE": -45, "N": -90, "NW": -135,
            "W": 180, "SW": 135, "S": 90, "SE": 45}


def crash_glyph(cr: DiagramCrash, base_ang: float = 0.0,
                route_forward: str = "E",
                throw: float = 0.0) -> tuple[str, tuple, tuple]:
    """Assemble one crash from the standard parts in the roadway's frame.

    ``base_ang`` is the road tangent in page degrees at this crash's
    milepost and ``route_forward`` names the compass direction that
    tangent represents, so a unit coded E travels along the drawn road
    and a unit coded N crosses it, the way the TSU sheets read.

    The cell is rigid. Unit one always runs CELL_SHAFT from its tail
    start to its tip; the numbered bubble always sits on the tail axis
    one gap behind that tail; the at fault asterisk always sits DECOR_S
    along the shaft and DECOR_N to the left of travel with the road
    surface letter opposite it; the injury circle always sits SEV_GAP
    past the front of the assembly. Text stays upright. The local origin
    is the point of impact or rest. Returns (svg, box, normal_extents).
    """
    u1 = cr.units[0] if cr.units else Unit(1, route_forward)
    u2 = cr.units[1] if len(cr.units) > 1 else None
    base = base_ang - _DIR_ANG.get(route_forward, 0)

    def conv(d, fallback):
        return base + _DIR_ANG.get(d, fallback - base)

    a1 = conv(u1.direction, base)
    parts: list[str] = []
    kp: list[tuple[float, float, float]] = []      # (x, y, pad)

    def K(x, y, pad=4.0):
        kp.append((x, y, pad))

    def vec(deg):
        r = math.radians(deg)
        return math.cos(r), math.sin(r)

    def extents_of():
        rb = math.radians(base_ang)
        nx_, ny_ = math.sin(rb), -math.cos(rb)
        box = (min(px - pad for px, py, pad in kp),
               max(px + pad for px, py, pad in kp),
               min(py - pad for px, py, pad in kp),
               max(py + pad for px, py, pad in kp))
        projs = [(px * nx_ + py * ny_, pad) for px, py, pad in kp]
        return box, (min(pr - pad for pr, pad in projs),
                     max(pr + pad for pr, pad in projs))

    def draw(tail, ang, uu, **kw):
        svg, tip, ink = _unit_cell(tail[0], tail[1], ang, uu, cr.night, **kw)
        for px, py in ink:
            K(px, py, 4.0)
        return svg, tip

    def decor(tail, ang, right_extra=0.0):
        """Bubble, at fault asterisk and surface letter on one tail.

        ``right_extra`` pushes the surface letter past a second vehicle
        drawn alongside on that side, so the pair keeps the asterisk left
        of travel and the letter right of it without either landing on
        the other vehicle.
        """
        c, s = vec(ang)
        lx, ly = s, -c                       # left of travel, page frame
        bx = tail[0] - (BUBBLE_R + BUBBLE_GAP) * c
        by = tail[1] - (BUBBLE_R + BUBBLE_GAP) * s
        out = _badge(bx, by, cr.seq)
        K(bx, by, BUBBLE_R + 1)
        sx = tail[0] + DECOR_S * c + DECOR_N * lx
        sy = tail[1] + DECOR_S * s + DECOR_N * ly
        out += _stroke_text(sx, sy + 1.5, "*", size=12.5, color=MAGENTA,
                            sw=1.05)
        K(sx, sy, 6)
        cx = tail[0] + DECOR_S * c - (DECOR_N + right_extra) * lx
        cy = tail[1] + DECOR_S * s - (DECOR_N + right_extra) * ly
        out += _stroke_text(cx, cy, cr.road_cond, size=9, color=GREEN)
        K(cx, cy, 6)
        return out

    def sev_at(x, y, ang):
        c, s = vec(ang)
        px, py = x + SEV_GAP * c, y + SEV_GAP * s
        K(px, py, SEV_R + 2)
        return _severity_circle(px, py, cr.severity)

    # ------------------------------------------------ one unit involved
    if u2 is None or cr.acc_typ in SINGLE_UNIT_TYPES:
        depart = cr.acc_typ in ROR_TYPES or cr.acc_typ == 19
        side = -1 if cr.acc_typ == 2 else 1          # ROR left leaves left
        ang = a1 + (side * DEPART_ANG if depart else 0.0)
        c, s = vec(ang)
        tail = (-CELL_SHAFT * c, -CELL_SHAFT * s)
        svg, tip = draw(tail, ang, u1, zigzag=depart)
        parts.append(svg)
        mark = {14: "P", 15: "B", 17: "A", 16: "T"}.get(cr.acc_typ)
        front = 0.0
        if cr.acc_typ == 18:                          # movable object struck
            ox, oy = tip[0] + 10 * c, tip[1] + 10 * s
            parts.append(f'<rect x="{ox - 5.5:.1f}" y="{oy - 5.5:.1f}" '
                         'width="11" height="11" fill="none" stroke="#000" '
                         'stroke-width="1.0" stroke-dasharray="2.4 2"/>')
            K(ox, oy, 8)
            front = 16.0
        elif mark:                                    # ped, bike, animal
            ox, oy = tip[0] + 9 * c, tip[1] + 9 * s
            parts.append(_stroke_text(ox, oy, mark, size=12, color=BLUE))
            K(ox, oy, 7)
            front = 15.0
        parts.append(sev_at(tip[0] + front * c, tip[1] + front * s, ang))
        parts.append(decor(tail, ang))
        return ("".join(parts),) + extents_of()

    a2 = conv(u2.direction, a1 + 90 if cr.acc_typ == 30 else a1)
    c1, s1 = vec(a1)
    lx, ly = s1, -c1

    # ------------------------------------------------ rear end / backing
    if cr.acc_typ in (21, 22, 31):
        back = cr.acc_typ == 31
        gap = 3.0                                # the bar stands clear
        tail1 = (-(CELL_SHAFT + gap) * c1, -(CELL_SHAFT + gap) * s1)
        svg1, tip1 = draw(tail1, a1, u1)
        lead_ang = a1 + 180 if back else a1
        if back:
            far = (CELL_SHAFT + gap) * c1, (CELL_SHAFT + gap) * s1
            svg2, tip2 = draw(far, lead_ang, u2)
            front = far
        else:
            svg2, tip2 = draw((gap * c1, gap * s1), lead_ang, u2)
            front = tip2
        parts += [svg1, svg2, _impact_tick(0, 0, a1)]
        K(0, 0, TICK_H + 1)
        parts.append(sev_at(front[0], front[1], a1))
        parts.append(decor(tail1, a1))
        return ("".join(parts),) + extents_of()

    # ------------------------------------------------ head on
    if cr.acc_typ == 27:
        tail1 = (-(CELL_SHAFT + 3) * c1, -(CELL_SHAFT + 3) * s1)
        svg1, _ = draw(tail1, a1, u1)
        svg2, _ = draw(((CELL_SHAFT + 3) * c1, (CELL_SHAFT + 3) * s1),
                       a1 + 180, u2)
        parts += [svg1, svg2, _impact_tick(0, 0, a1)]
        K(0, 0, TICK_H + 1)
        px, py = lx * (TICK_H + SEV_R + 3), ly * (TICK_H + SEV_R + 3)
        parts.append(_severity_circle(px, py, cr.severity))
        K(px, py, SEV_R + 2)
        parts.append(decor(tail1, a1))
        return ("".join(parts),) + extents_of()

    # ------------------------------------------------ sideswipes
    if cr.acc_typ == 28:                             # sideswipe, same way
        half = LANE_SEP / 2
        tail1 = (-CELL_SHAFT * c1 + lx * half, -CELL_SHAFT * s1 + ly * half)
        svg1, tip1 = draw(tail1, a1, u1)
        tail2 = (-CELL_SHAFT * c1 - lx * half, -CELL_SHAFT * s1 - ly * half)
        svg2, _ = draw(tail2, a1, u2, swerve=-LANE_SEP * 0.55)
        parts += [svg1, svg2]
        parts.append(sev_at(tip1[0], tip1[1], a1))
        parts.append(decor(tail1, a1, right_extra=LANE_SEP + 2))
        return ("".join(parts),) + extents_of()

    if cr.acc_typ == 29:                             # sideswipe, opposing
        # the two run alongside each other over the same stretch and pass,
        # one drifting into the other. They do not meet head to head; that
        # is the head on cell, which carries the point of impact bar.
        half = LANE_SEP / 2
        h2 = CELL_SHAFT / 2
        tail1 = (-h2 * c1 + lx * half, -h2 * s1 + ly * half)
        svg1, tip1 = draw(tail1, a1, u1, swerve=LANE_SEP * 0.55)
        stag = 7.0                       # they pass staggered, not level
        tail2 = ((h2 + stag) * c1 - lx * half, (h2 + stag) * s1 - ly * half)
        svg2, _ = draw(tail2, a1 + 180, u2)
        parts += [svg1, svg2]
        parts.append(sev_at(tip1[0], tip1[1], a1))
        parts.append(decor(tail1, a1, right_extra=LANE_SEP + 2))
        return ("".join(parts),) + extents_of()

    # ------------------------------------------------ angle and turning
    c2, s2 = vec(a2)
    tail1 = (-CELL_SHAFT * c1, -CELL_SHAFT * s1)
    tail2 = (-CELL_SHAFT * c2, -CELL_SHAFT * s2)
    svg1, tip1 = draw(tail1, a1, u1)
    svg2, _ = draw(tail2, a2, u2)
    parts += [svg1, svg2]
    bis = a1 + ((a2 - a1 + 540) % 360 - 180) / 2.0
    bc, bs = vec(bis)
    px, py = (SEV_GAP + 3) * bc, (SEV_GAP + 3) * bs
    parts.append(_severity_circle(px, py, cr.severity))
    K(px, py, SEV_R + 2)
    parts.append(decor(tail1, a1))
    return ("".join(parts),) + extents_of()


def _rot(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


# ----------------------------------------------------------------- blocks
def legend_block(x, y, w=700, h=305):
    def arrow(ax, ay, ln=42, night=False, extra=""):
        return (f'<line x1="{ax}" y1="{ay}" x2="{ax + ln - 14}" y2="{ay}" '
                'stroke="#000" stroke-width="1.1"/>' + extra +
                _arrowhead(ax + ln, ay, 0, night))
    rows1 = ["MOVING VEHICLE", "PARKED VEHICLE", "PARKING VEHICLE",
             "MOVABLE OBJECT", "HEAD ON", "REAR END", "RAN OFF ROAD",
             "DAYLIGHT CRASH", "NIGHT CRASH"]
    rows2 = ["ANGLE", "TURNING", "BACKING", "SIDESWIPE",
             "NON-SEVERE INJURY", "SEVERE INJURY", "FATALITY"]
    rows3 = ["9 MPH OR LESS", "10 MPH TO 19", "20 MPH TO 29", "30 MPH TO 39",
             "40 MPH TO 49", "50 MPH TO 59", "60 MPH TO 69", "70 AND UP",
             "SPEED UNKNOWN"]
    rows4 = [("A", "ANIMAL", GREEN), ("P", "PEDESTRIAN", GREEN),
             ("B", "BICYCLE", GREEN), ("T", "TRAIN", GREEN),
             ("*", "DRIVER AT FAULT", MAGENTA), ("D", "DRY", GREEN),
             ("W", "WET", GREEN), ("I", "ICY OR SNOWY", GREEN),
             ("O", "Other", GREEN)]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" '
           'stroke="#000" stroke-width="1.6"/>',
           _stroke_text(x + w / 2, y + 24, "LEGEND", size=24, slant=10,
                        sw=1.3)
           + f'<line x1="{x + w / 2 - 68}" y1="{y + 40}" '
             f'x2="{x + w / 2 + 68}" y2="{y + 40}" stroke="#000" '
             'stroke-width="1.2"/>']
    yy = y + 62
    for i, label in enumerate(rows1):
        ay = yy + i * 27
        ax = x + 18
        if label == "PARKED VEHICLE":
            g = (f'<rect x="{ax}" y="{ay - 6}" width="26" height="12" '
                 'fill="none" stroke="#000"/>'
                 f'<line x1="{ax}" y1="{ay - 6}" x2="{ax + 26}" '
                 f'y2="{ay + 6}" stroke="#000"/><line x1="{ax}" '
                 f'y1="{ay + 6}" x2="{ax + 26}" y2="{ay - 6}" '
                 'stroke="#000"/>')
        elif label == "PARKING VEHICLE":
            g = (f'<rect x="{ax}" y="{ay - 6}" width="22" height="12" '
                 'fill="none" stroke="#000"/>'
                 f'<line x1="{ax}" y1="{ay - 6}" x2="{ax + 22}" '
                 f'y2="{ay + 6}" stroke="#000"/><line x1="{ax}" '
                 f'y1="{ay + 6}" x2="{ax + 22}" y2="{ay - 6}" '
                 'stroke="#000"/>' +
                 f'<line x1="{ax + 24}" y1="{ay + 2}" x2="{ax + 34}" '
                 f'y2="{ay - 4}" stroke="#000"/>' +
                 _arrowhead(x + 18 + 38, ay - 6, -0.5, False))
        elif label == "MOVABLE OBJECT":
            g = arrow(ax, ay, 34) + (
                f'<path d="M {ax + 40} {ay - 6} h 10 v 12 h -10" '
                'fill="none" stroke="#000"/>')
        elif label == "HEAD ON":
            g = (arrow(ax, ay, 26) +
                 f'<line x1="{ax + 28}" y1="{ay - 8}" x2="{ax + 28}" '
                 f'y2="{ay + 8}" stroke="#000"/>' +
                 f'<line x1="{ax + 56}" y1="{ay}" x2="{ax + 34}" '
                 f'y2="{ay}" stroke="#000"/>' +
                 _arrowhead(ax + 30, ay, math.pi, False))
        elif label == "REAR END":
            g = (arrow(ax, ay, 26) +
                 f'<line x1="{ax + 30}" y1="{ay}" x2="{ax + 52}" y2="{ay}" '
                 'stroke="#000"/>' + _arrowhead(ax + 66, ay, 0, False))
        elif label == "RAN OFF ROAD":
            pts = " ".join(f"{ax + i * 7},{ay + (7 if i % 2 else -7)}"
                           for i in range(4))
            g = (f'<polyline points="{ax},{ay} {pts} {ax + 32},{ay}" '
                 'fill="none" stroke="#000"/>'
                 f'<line x1="{ax + 32}" y1="{ay}" x2="{ax + 46}" y2="{ay}" '
                 'stroke="#000"/>' + _arrowhead(ax + 58, ay, 0, False))
        elif label == "NIGHT CRASH":
            g = arrow(ax, ay, 42, night=True)
        else:
            g = arrow(ax, ay, 42)
        out.append(g)
        out.append(_stroke_text(x + 92, ay, label, size=8.6,
                                anchor="start"))
    for i, label in enumerate(rows2):
        ay = yy + 10 + i * 34
        ax = x + 228
        if label == "ANGLE":
            g = (f'<line x1="{ax + 22}" y1="{ay - 22}" x2="{ax + 22}" '
                 f'y2="{ay - 4}" stroke="#000"/>' +
                 _arrowhead(ax + 22, ay + 4, math.pi / 2, False) +
                 f'<line x1="{ax}" y1="{ay + 6}" x2="{ax + 12}" '
                 f'y2="{ay + 6}" stroke="#000"/>' +
                 _arrowhead(ax + 20, ay + 6, 0, False))
        elif label == "TURNING":
            g = (f'<path d="M {ax} {ay + 10} C {ax + 16} {ay + 10} '
                 f'{ax + 14} {ay - 2} {ax + 30} {ay - 4}" fill="none" '
                 'stroke="#000"/>' + _arrowhead(ax + 40, ay - 5, -0.1, False))
        elif label == "BACKING":
            g = (f'<line x1="{ax}" y1="{ay}" x2="{ax + 20}" y2="{ay}" '
                 'stroke="#000"/>'
                 f'<line x1="{ax + 22}" y1="{ay - 8}" x2="{ax + 22}" '
                 f'y2="{ay + 8}" stroke="#000"/>'
                 f'<line x1="{ax + 46}" y1="{ay}" x2="{ax + 26}" y2="{ay}" '
                 'stroke="#000"/>' + _arrowhead(ax + 54, ay, 0, False))
        elif label == "SIDESWIPE":
            g = (f'<line x1="{ax}" y1="{ay + 5}" x2="{ax + 30}" '
                 f'y2="{ay + 5}" stroke="#000"/>'
                 f'<path d="M {ax} {ay - 5} L {ax + 14} {ay - 5} '
                 f'L {ax + 20} {ay - 9}" fill="none" stroke="#000"/>' +
                 _arrowhead(ax + 42, ay + 5, 0, False) +
                 _arrowhead(ax + 30, ay - 11, -0.25, False))
        else:
            sev = {"NON-SEVERE INJURY": "B", "SEVERE INJURY": "A",
                   "FATALITY": "K"}[label]
            g = (f'<line x1="{ax}" y1="{ay}" x2="{ax + 26}" y2="{ay}" '
                 'stroke="#000"/>' + _arrowhead(ax + 38, ay, 0, False) +
                 _severity_circle(ax + 46, ay, sev))
        out.append(g)
        out.append(_stroke_text(x + 288, ay, label, size=8.6,
                                anchor="start"))
    for i, label in enumerate(rows3):
        ay = yy + i * 27
        ax = x + 396
        spd = (None if label == "SPEED UNKNOWN"
               else 75 if label == "70 AND UP" else i * 10 + 5)
        u = Unit(1, speed=spd)
        svg, _ = _unit_arrow(ax, ay, 0, 40, u, False)
        out.append(svg)
        out.append(_stroke_text(x + 458, ay, label, size=8.2,
                                anchor="start"))
    for i, (letter, label, color) in enumerate(rows4):
        ay = yy + i * 27
        out.append(_stroke_text(x + 576, ay + (2 if letter == "*" else 0),
                                letter, size=13 if letter == "*" else 11,
                                color=color))
        out.append(_stroke_text(x + 592, ay, label, size=8.2,
                                anchor="start"))
    return "".join(out)


def tsu_block(x, y, prepared_by, date_str, logo_b64, w=300, h=200):
    lines = ["N.C. DEPARTMENT of TRANSPORTATION", "DIVISION of HIGHWAYS",
             "TRANSPORTATION MOBILITY and", "SAFETY DIVISION"]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" '
           'stroke="#000" stroke-width="1.6"/>']
    for i, t in enumerate(lines):
        out.append(f'<text x="{x + w / 2}" y="{y + 22 + i * 17}" '
                   'font-size="13" font-family="Times New Roman, serif" '
                   'font-weight="bold" font-style="italic" '
                   f'text-anchor="middle">{t}</text>')
    y2 = y + 82
    out.append(f'<line x1="{x}" y1="{y2}" x2="{x + w}" y2="{y2}" '
               'stroke="#000" stroke-width="1.3"/>')
    out.append(f'<text x="{x + w / 2}" y="{y2 + 26}" font-size="19" '
               'font-family="Times New Roman, serif" font-weight="bold" '
               'font-style="italic" text-anchor="middle">'
               'TRAFFIC SAFETY UNIT</text>')
    y3 = y2 + 38
    out.append(f'<line x1="{x}" y1="{y3}" x2="{x + w}" y2="{y3}" '
               'stroke="#000" stroke-width="1.3"/>')
    out.append(f'<line x1="{x + w / 2}" y1="{y3}" x2="{x + w / 2}" '
               f'y2="{y3 + 34}" stroke="#000"/>')
    out.append(f'<text x="{x + 12}" y="{y3 + 21}" font-size="11" '
               'font-family="Times New Roman, serif" font-weight="bold" '
               f'font-style="italic">Date: {date_str}</text>')
    out.append(f'<text x="{x + w * 0.75}" y="{y3 + 15}" font-size="10.5" '
               'font-family="Times New Roman, serif" font-weight="bold" '
               'font-style="italic" text-anchor="middle">Prepared By:'
               '</text>')
    out.append(f'<text x="{x + w * 0.75}" y="{y3 + 28}" font-size="10.5" '
               'font-family="Times New Roman, serif" font-weight="bold" '
               f'font-style="italic" text-anchor="middle">{prepared_by}'
               '</text>')
    y4 = y3 + 34
    out.append(f'<line x1="{x}" y1="{y4}" x2="{x + w}" y2="{y4}" '
               'stroke="#000" stroke-width="1.3"/>')
    if logo_b64:
        out.append(f'<image x="{x + 10}" y="{y4 + 6}" height="34" '
                   f'href="data:image/png;base64,{logo_b64}"/>')
    for i, t in enumerate(["940 Main Campus Drive, Suite 500",
                           "Raleigh, NC 27606",
                           "VHB Engineering NC, P.C. (C-3705)"]):
        out.append(f'<text x="{x + 112}" y="{y4 + 16 + i * 11}" '
                   f'font-size="8">{t}</text>')
    return "".join(out)


def north_needle(x, y, h=170, rot=0.0):
    """The needle tilts with the schematic so it stays true north
    relative to the drawn roadway bearing."""
    g = (f'<polygon points="{x},{y} {x + 5},{y + h * 0.62} '
         f'{x},{y + h} {x - 5},{y + h * 0.62}" fill="#fff" '
         'stroke="#000" stroke-width="1.2"/>'
         f'<polygon points="{x},{y} {x + 5},{y + h * 0.62} {x},{y + h}" '
         'fill="#000"/>'
         f'<circle cx="{x}" cy="{y + h * 0.62}" r="7" fill="#fff" '
         'stroke="#000"/>'
         + _stroke_text(x, y + h * 0.62, "N", size=9))
    if rot:
        return (f'<g transform="rotate({rot:.1f} {x} {y + h / 2})">'
                f'{g}</g>')
    return g


# ------------------------------------------------------------------ sheet
def render_section(crashes: list[DiagramCrash], layout: dict) -> str:
    """Render a section (strip) sheet: one schematic road line, crashes
    stacked near their milepost, the standard furniture around it."""
    lo, hi = layout["begin_mp"], layout["end_mp"]
    p0 = (80, 870)
    p1 = (860, 690)
    p2 = (1560, 430)

    def road_pt(t):
        x = ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0])
        y = ((1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
        return x, y

    def road_ang(t):
        dx = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
        dy = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
        return math.atan2(dy, dx)

    svg = [f'<path d="M {p0[0]} {p0[1]} Q {p1[0]} {p1[1]} {p2[0]} {p2[1]}" '
           'fill="none" stroke="#000" stroke-width="1.3"/>']
    for t, mp in ((0.0, lo), (1.0, hi)):
        x, y = road_pt(t)
        a = road_ang(t) + math.pi / 2
        svg.append(f'<line x1="{x - 14 * math.cos(a):.1f}" '
                   f'y1="{y - 14 * math.sin(a):.1f}" '
                   f'x2="{x + 14 * math.cos(a):.1f}" '
                   f'y2="{y + 14 * math.sin(a):.1f}" stroke="#000" '
                   'stroke-width="1.2"/>')
        lbl = "Begin MP:" if t == 0 else "End MP:"
        lx = max(x, 74) if t == 0 else x - 24
        ly = y + 46 if t == 0 else y - 62
        svg.append(_stroke_text(lx, ly - 5, lbl, size=15.5, sw=1.05))
        svg.append(_stroke_text(lx, ly + 15, f"{mp:.2f}", size=15.5,
                                sw=1.05))
    jn_keep = []
    for jn in layout.get("junctions", []):
        t = (jn["mp"] - lo) / (hi - lo) if hi > lo else 0.5
        if not 0.0 <= t <= 1.0:
            continue
        x, y = road_pt(t)
        a = road_ang(t) + math.pi / 2
        up = jn.get("side", -1)
        ex = x + up * 52 * math.cos(a)
        ey = y + up * 52 * math.sin(a)
        svg.append(f'<line x1="{x:.1f}" y1="{y:.1f}" '
                   f'x2="{ex:.1f}" y2="{ey:.1f}" stroke="#000" '
                   'stroke-width="1.1"/>')
        lx = ex + 8
        ly = ey + (14 if up > 0 else -12)
        svg.append(_stroke_text(lx, ly, jn["label"], size=11.5,
                                anchor="start"))
        jn_keep.append((lx - 6, ly - 10,
                        lx + 8.4 * len(jn["label"]), ly + 10))
        jn_keep.append((min(x, ex) - 16, min(y, ey) - 6,
                        max(x, ex) + 16, max(y, ey) + 6))

    if "north_rot" not in layout:
        layout["north_rot"] = math.degrees(road_ang(0.5))
    # furniture keep-outs, measured off what the sheet actually draws so
    # a block that moves or gains a line still holds its own space
    def text_box(cx, cy, lines, size, lead, anchor="middle"):
        w = max((len(t) for t in lines), default=0) * size * 0.60
        x0 = cx - w / 2 if anchor == "middle" else cx
        return (x0 - 12, cy - size, x0 + w + 12,
                cy + lead * (len(lines) - 1) + size)

    keep_out = [(904, 18, 1620, 345),                    # legend
                (1300, 826, 1632, 1056),                 # TSU title block
                (0, 830, 200, 1056),                     # begin MP label
                (1440, 356, 1632, 452),                  # end MP label
                (784, 18, 928, 232)]                     # north needle
    keep_out.append(text_box(layout.get("title_x", 760), 52,
                             layout.get("title", []), 19.5, 27))
    rlx, rly = layout.get("route_label_xy", (520, 940))
    keep_out.append(text_box(rlx, rly, layout.get("route_label", []),
                             16, 25))
    for note in layout.get("notes", []):
        keep_out.append(text_box(note["x"], note["y"], note["text"], 12.5,
                                 18, anchor="middle"))
    keep_out += jn_keep
    keep_out += [tuple(r) for r in layout.get("keep_out", [])]

    def clear(x0, y0, x1, y1):
        if x0 < 26 or x1 > PAGE_W - 26 or y0 < 26 or y1 > PAGE_H - 26:
            return False
        return not any(x0 < kx1 and x1 > kx0 and y0 < ky1 and y1 > ky0
                       for kx0, ky0, kx1, ky1 in keep_out)

    # crashes stand at their own milepost, one uniform standoff off the
    # centerline for the whole side, and spread along the road only as
    # far as they must to keep their ink apart. That is how the drawn
    # sheets read: same standoff, same pitch, bubbles in crash order, and
    # nothing wandering away from the station it happened at.
    route_fwd = layout.get("route_forward", "E")
    items = []
    for cr in sorted([c for c in crashes if c.mp is not None],
                     key=lambda c: (c.mp, c.seq)):
        t = min(1.0, max(0.0, (cr.mp - lo) / (hi - lo) if hi > lo else 0.5))
        bx, by = road_pt(t)
        ang = math.degrees(road_ang(t))
        nx, ny = _rot(0, -1, ang)
        g, box, n_ext = crash_glyph(cr, base_ang=ang,
                                    route_forward=route_fwd)
        pref, hard = 1, False
        if cr.acc_typ in ROR_TYPES or cr.acc_typ == 19:
            base = ang - _DIR_ANG.get(route_fwd, 0)
            ua = base + _DIR_ANG.get(cr.units[0].direction, -base) \
                if cr.units else base
            side = -1 if cr.acc_typ == 2 else 1
            fa = math.radians(ua + side * DEPART_ANG)
            pref = 1 if math.cos(fa) * nx + math.sin(fa) * ny > 0 else -1
            hard = True
        items.append({"cr": cr, "t": t, "bx": bx, "by": by, "g": g,
                      "box": box, "n": n_ext, "pref": pref, "hard": hard})

    clusters: list[list[dict]] = []
    for it in items:
        if clusters and it["bx"] - clusters[-1][-1]["bx"] < 150:
            clusters[-1].append(it)
        else:
            clusters.append([it])
    all_boxes: list[tuple[float, float, float, float]] = []

    road_pts = [road_pt(i / 240.0) for i in range(241)]

    def road_far(bb):
        """True when no part of the box comes inside ROAD_GAP of the road."""
        for rx, ry in road_pts:
            dx = max(bb[0] - rx, 0.0, rx - bb[2])
            dy = max(bb[1] - ry, 0.0, ry - bb[3])
            if dx * dx + dy * dy < ROAD_GAP * ROAD_GAP:
                return False
        return True

    def open_spot(bb):
        return clear(*bb) and road_far(bb) and not any(
            bb[0] < r[2] and bb[2] > r[0] and bb[1] < r[3] and bb[3] > r[1]
            for r in all_boxes)

    for cl in clusters:
        above = [it for it in cl if it["hard"] and it["pref"] > 0]
        below = [it for it in cl if it["hard"] and it["pref"] < 0]
        for it in cl:
            if not it["hard"]:
                (below if len(below) < len(above) else above).append(it)
        tm = sum(it["t"] for it in cl) / len(cl)
        ax, ay = road_pt(tm)
        angm = math.degrees(road_ang(tm))
        nx, ny = _rot(0, -1, angm)
        fx, fy = _rot(1, 0, angm)
        for sd, members in ((1, above), (-1, below)):
            if not members:
                continue
            members.sort(key=lambda it: (it["cr"].mp, it["cr"].seq))
            # one standoff for the whole side. n_lo/n_hi are the assembly's
            # signed ink extents along the road normal measured from its
            # own origin, so the origin has to stand this far out for the
            # nearest ink to clear the centerline by ROAD_GAP.
            d0 = max(max(24.0, (ROAD_GAP - it["n"][0]) if sd > 0
                         else (ROAD_GAP + it["n"][1])) for it in members)
            rowh = max(it["n"][1] - it["n"][0] for it in members) + 10

            def along(it):
                """Ink extents along the road, measured from the origin."""
                bx0, bx1, by0, by1 = it["box"]
                ps = [x * fx + y * fy for x in (bx0, bx1) for y in (by0, by1)]
                return min(ps), max(ps)

            want = [(it["bx"] - ax) * fx + (it["by"] - ay) * fy
                    for it in members]
            st = list(want)
            for i in range(1, len(st)):          # keep the ink from touching
                lo_i = along(members[i])[0]
                hi_p = along(members[i - 1])[1]
                need = st[i - 1] + hi_p + 12 - lo_i
                if st[i] < need:
                    st[i] = need
            drift = sum(st) / len(st) - sum(want) / len(want)
            st = [v - drift for v in st]         # back onto their mileposts

            def place(it, s_at, rank, sd2, base=None):
                dist = (d0 if base is None else base) + rank * rowh
                tx = ax + fx * s_at + nx * sd2 * dist
                ty = ay + fy * s_at + ny * sd2 * dist
                return tx, ty, (tx + it["box"][0] - 4, ty + it["box"][2] - 4,
                                tx + it["box"][1] + 4, ty + it["box"][3] + 4)

            for _ in range(14):              # the road curves away from the
                if all(road_far(place(it, s_i, 0, sd, d0)[2])
                       for it, s_i in zip(members, st)):
                    break                        # tangent; step the rank out
                d0 += 4.0                        # until the whole side clears

            for it, s_i in zip(members, st):
                spot = None
                for rank in (0, 1, 2, 3):
                    for dsh in (0, -24, 24, -48, 48, -76, 76, -108, 108,
                                -144, 144, -190, 190):
                        tx, ty, bb = place(it, s_i + dsh, rank, sd)
                        if open_spot(bb):
                            spot = (tx, ty, bb)
                            break
                    if spot:
                        break
                if spot is None and not it["hard"]:      # try the far side
                    for rank in (0, 1, 2):
                        for dsh in (0, -32, 32, -64, 64, -96, 96):
                            tx, ty, bb = place(it, s_i + dsh, rank, -sd)
                            if open_spot(bb):
                                spot = (tx, ty, bb)
                                break
                        if spot:
                            break
                if spot is None:
                    spot = place(it, s_i, 3, sd)
                ox, oy, bb = spot
                all_boxes.append(bb)
                dxn, dyn = layout.get("nudges", {}).get(
                    it["cr"].crash_id, (0, 0))
                svg.append(
                    f'<g data-crash="{it["cr"].crash_id}" '
                    f'data-seq="{it["cr"].seq}" '
                    f'transform="translate({ox + dxn:.1f},'
                    f'{oy + dyn:.1f})">{it["g"]}</g>')

    return _sheet(svg, layout, crashes)


def _sheet(body_svg: list, layout: dict, crashes) -> str:
    svg = [f'<rect x="14" y="14" width="{PAGE_W - 28}" '
           f'height="{PAGE_H - 28}" fill="#fff" stroke="#000" '
           'stroke-width="2"/>']
    tx = layout.get("title_x", 760)
    for i, line in enumerate(layout.get("title", [])):
        svg.append(_stroke_text(tx, 52 + i * 27, line, size=19.5, sw=1.15))
    svg.append(legend_block(912, 26))
    svg.append(north_needle(layout.get("north_x", 856), 40,
                            rot=layout.get("north_rot", 0.0)))
    rl = layout.get("route_label", [])
    rx, ry = layout.get("route_label_xy", (520, 940))
    for i, line in enumerate(rl):
        svg.append(_stroke_text(rx, ry + i * 25, line, size=16, sw=1.05))
    for note in layout.get("notes", []):
        for i, line in enumerate(note["text"]):
            svg.append(_stroke_text(note["x"], note["y"] + i * 18, line,
                                    size=12.5))
    svg.append(tsu_block(1318, 842, layout.get("prepared_by", ""),
                         layout.get("date", ""),
                         layout.get("logo_b64", "")))
    svg.extend(body_svg)
    return ('<!doctype html><html><head><meta charset="utf-8"><style>'
            'html,body{margin:0;padding:0}'
            f'body{{width:{PAGE_W}px;height:{PAGE_H}px}}'
            'text{font-family:Arial,Helvetica,sans-serif;fill:#000}'
            '</style></head><body>'
            f'<svg width="{PAGE_W}" height="{PAGE_H}" '
            f'viewBox="0 0 {PAGE_W} {PAGE_H}" '
            'xmlns="http://www.w3.org/2000/svg">'
            + "".join(svg) + '</svg>'
            '<script>window._map=1;</script></body></html>')


def load_logo(path: str | None) -> str:
    if path and os.path.exists(path):
        return base64.b64encode(open(path, "rb").read()).decode()
    return ""


def build_section_diagram(out_html: str, data_csv: str, layout_json: str):
    crashes = read_data_csv(data_csv)
    layout = json.load(open(layout_json))
    layout["logo_b64"] = load_logo(layout.get("logo"))
    html = render_section(crashes, layout)
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)
    return len(crashes)
