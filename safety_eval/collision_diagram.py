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
def _arrowhead(x, y, ang, night):
    fill = "#000" if night else "#fff"
    pts = [(0, 0), (-16, 5.5), (-13, 0), (-16, -5.5)]
    cos, sin = math.cos(ang), math.sin(ang)
    p = " ".join(f"{x + px * cos - py * sin:.1f},{y + px * sin + py * cos:.1f}"
                 for px, py in pts)
    return (f'<polygon points="{p}" fill="{fill}" stroke="#000" '
            'stroke-width="1.1"/>')


def _speed_marks(x0, y0, x1, y1, speed):
    out = []
    if speed is None:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return (f'<text x="{mx:.1f}" y="{my + 3:.1f}" font-size="9" '
                f'fill="{BLUE}" text-anchor="middle">x</text>')
    if speed >= 70:
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L * 2.1, dx / L * 2.1
        for k in (-1, 0, 1):
            out.append(f'<line x1="{x0 + nx * k:.1f}" y1="{y0 + ny * k:.1f}" '
                       f'x2="{x1 + nx * k:.1f}" y2="{y1 + ny * k:.1f}" '
                       f'stroke="{BLUE}" stroke-width="1.4"/>')
        return "".join(out)
    n = min(7, speed // 10 + 1)
    for k in range(1, n + 1):
        t = k / (n + 1)
        out.append(f'<circle cx="{x0 + (x1 - x0) * t:.1f}" '
                   f'cy="{y0 + (y1 - y0) * t:.1f}" r="1.7" fill="{BLUE}"/>')
    return "".join(out)


def _severity_circle(x, y, sev):
    if sev == "O":
        return ""
    if sev == "K":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.6" fill="{RED}"/>'
    if sev == "A":
        return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.6" fill="#fff" '
                f'stroke="{RED}" stroke-width="1.5"/>'
                f'<path d="M {x - 4.6:.1f} {y:.1f} A 4.6 4.6 0 0 0 '
                f'{x + 4.6:.1f} {y:.1f} Z" fill="{RED}"/>')
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.6" fill="#fff" '
            f'stroke="{RED}" stroke-width="1.5"/>')


def _badge(x, y, n):
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9.5" fill="#fff" '
            'stroke="#000" stroke-width="1.1"/>'
            f'<text x="{x:.1f}" y="{y + 3.6:.1f}" font-size="10.5" '
            f'text-anchor="middle">{n}</text>')


_DIR_ANG = {"E": 0, "NE": -45, "N": -90, "NW": -135,
            "W": 180, "SW": 135, "S": 90, "SE": 45}


def _unit_arrow(x, y, ang_deg, length, unit, night, zigzag=False):
    """One unit: tail (optionally ran-off-road zigzag), speed marks, head."""
    a = math.radians(ang_deg)
    cos, sin = math.cos(a), math.sin(a)
    out = []
    x0, y0 = x, y
    if zigzag:
        seg = 9
        pts = [(0, 0), (seg, 7), (2 * seg, -7), (3 * seg, 7), (4 * seg, 0)]
        d = " ".join(f"{x + px * cos - py * sin:.1f},"
                     f"{y + px * sin + py * cos:.1f}" for px, py in pts)
        out.append(f'<polyline points="{d}" fill="none" stroke="#000" '
                   'stroke-width="1.1"/>')
        x0, y0 = x + 4 * seg * cos, y + 4 * seg * sin
    x1, y1 = x0 + length * cos, y0 + length * sin
    out.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" '
               f'y2="{y1:.1f}" stroke="#000" stroke-width="1.1"/>')
    out.append(_speed_marks(x0, y0, x1, y1, unit.speed))
    out.append(_arrowhead(x1, y1, a, night))
    return "".join(out), (x1, y1)


def crash_glyph(cr: DiagramCrash, base_ang: float = 0.0,
                route_forward: str = "E") -> tuple[str, float]:
    """Assemble one crash with the roadway's local bearing as its frame.

    ``base_ang`` is the road tangent in page degrees at this crash's
    milepost and ``route_forward`` names the compass direction that
    tangent represents, so a unit coded E travels along the drawn road
    and a unit coded N crosses it, the way the TSU sheets read. The
    local origin (0, 0) is the point of impact or departure; text stays
    upright. Returns (svg, halfwidth).
    """
    u1 = cr.units[0] if cr.units else Unit(1, route_forward)
    u2 = cr.units[1] if len(cr.units) > 1 else None
    base = base_ang - _DIR_ANG.get(route_forward, 0)

    def conv(d, fallback):
        return base + _DIR_ANG.get(d, fallback - base)

    a1 = conv(u1.direction, base)
    parts = []
    L = 46

    def vec(deg):
        r = math.radians(deg)
        return math.cos(r), math.sin(r)

    def tail_decor(ax, ay, ang_deg):
        c, s = vec(ang_deg)
        pc, ps = -s, c
        up = -1 if ps > 0 else 1
        bx, by = ax - (L + 20) * c, ay - (L + 20) * s
        deco = _badge(bx + pc * 16 * up, by + ps * 16 * up, cr.seq)
        mx, my = ax - L * 0.55 * c, ay - L * 0.55 * s
        deco += (f'<text x="{mx + pc * 11 * up:.1f}" '
                 f'y="{my + ps * 11 * up + 4:.1f}" font-size="12" '
                 f'fill="{MAGENTA}" text-anchor="middle">*</text>')
        deco += (f'<text x="{mx - pc * 11 * up:.1f}" '
                 f'y="{my - ps * 11 * up + 3:.1f}" font-size="10" '
                 f'fill="{GREEN}" text-anchor="middle">{cr.road_cond}</text>')
        return deco

    if cr.acc_typ in SINGLE_UNIT_TYPES or u2 is None:
        c, s = vec(a1)
        if cr.acc_typ in ROR_TYPES or cr.acc_typ in (18, 19):
            # departure trajectory: dotted tail on the road, zigzag off
            # to the coded side, short run to rest
            side = -1 if cr.acc_typ == 2 else 1
            pc, ps = -s * side, c * side
            t0 = (-(L + 4) * c, -(L + 4) * s)
            t1 = (-4 * c, -4 * s)
            parts.append(f'<line x1="{t0[0]:.1f}" y1="{t0[1]:.1f}" '
                         f'x2="{t1[0]:.1f}" y2="{t1[1]:.1f}" '
                         'stroke="#000" stroke-width="1.1"/>')
            parts.append(_speed_marks(*t0, *t1, u1.speed))
            zz = [t1]
            for adv, off in ((9, 11), (18, -7), (27, 13)):
                zz.append((t1[0] + adv * c + pc * off,
                           t1[1] + adv * s + ps * off))
            fa = a1 + side * 42
            fc, fs = vec(fa)
            p_end = (zz[-1][0] + 30 * fc, zz[-1][1] + 30 * fs)
            pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in zz)
            parts.append(f'<polyline points="{pts} {p_end[0]:.1f},'
                         f'{p_end[1]:.1f}" fill="none" stroke="#000" '
                         'stroke-width="1.1"/>')
            parts.append(_arrowhead(*p_end, math.radians(fa), cr.night))
            sx, sy = p_end[0] + 7 * fc, p_end[1] + 7 * fs
            if cr.acc_typ == 18:
                parts.append(f'<rect x="{sx:.1f}" y="{sy - 5:.1f}" '
                             'width="10" height="10" fill="none" '
                             'stroke="#000" stroke-width="1.1"/>')
            parts.append(_severity_circle(sx, sy, cr.severity))
            parts.append(tail_decor(0, 0, a1))
            return "".join(parts), L + 58
        svg, head = _unit_arrow(-L * c, -L * s, a1, L, u1, cr.night)
        parts.append(svg)
        parts.append(_severity_circle(head[0] + 4 * c, head[1] + 4 * s,
                                      cr.severity))
        parts.append(tail_decor(0, 0, a1))
        return "".join(parts), L + 46
    a2 = conv(u2.direction, a1 + 90 if cr.acc_typ == 30 else a1)
    c1, s1 = vec(a1)
    if cr.acc_typ in (21, 22):                       # rear end, inline
        svg1, _ = _unit_arrow(-(L + 14) * c1, -(L + 14) * s1, a1, L,
                              u1, cr.night)
        svg2, _ = _unit_arrow(4 * c1, 4 * s1, a1, L * 0.85, u2, cr.night)
        parts += [svg1, svg2, _severity_circle(0, 0, cr.severity),
                  tail_decor(-8 * c1, -8 * s1, a1)]
        return "".join(parts), 2 * L + 34
    if cr.acc_typ in (27, 29):                       # head on / ss opposite
        off = 6 if cr.acc_typ == 29 else 0
        pc, ps = -s1, c1
        svg1, _ = _unit_arrow(-(L + 5) * c1 + pc * off,
                              -(L + 5) * s1 + ps * off, a1, L, u1, cr.night)
        svg2, _ = _unit_arrow((L + 5) * c1 - pc * off,
                              (L + 5) * s1 - ps * off, a1 + 180, L,
                              u2, cr.night)
        parts += [svg1, svg2, _severity_circle(0, 0, cr.severity),
                  tail_decor(pc * off, ps * off, a1)]
        return "".join(parts), 2 * L + 30
    if cr.acc_typ == 28:                             # sideswipe same dir
        pc, ps = -s1, c1
        svg1, _ = _unit_arrow(-(L + 5) * c1 + pc * 6,
                              -(L + 5) * s1 + ps * 6, a1, L, u1, cr.night)
        svg2, _ = _unit_arrow(-(L + 5) * c1 - pc * 7,
                              -(L + 5) * s1 - ps * 7, a1 + 9, L,
                              u2, cr.night)
        parts += [svg1, svg2, _severity_circle(0, 0, cr.severity),
                  tail_decor(pc * 6, ps * 6, a1)]
        return "".join(parts), 2 * L + 30
    c2, s2 = vec(a2)
    svg1, _ = _unit_arrow(-(L + 6) * c1, -(L + 6) * s1, a1, L, u1, cr.night)
    svg2, _ = _unit_arrow(-(L + 6) * c2, -(L + 6) * s2, a2, L, u2, cr.night)
    parts += [svg1, svg2, _severity_circle(0, 0, cr.severity),
              tail_decor(0, 0, a1)]
    return "".join(parts), 2 * L + 24


def _rot(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


# ----------------------------------------------------------------- blocks
def legend_block(x, y, w=548, h=305):
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
           f'<text x="{x + w / 2}" y="{y + 30}" font-size="26" '
           'font-style="italic" text-anchor="middle" '
           f'text-decoration="underline">LEGEND</text>']
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
        out.append(f'<text x="{x + 92}" y="{ay + 3.5}" font-size="9.5">'
                   f'{label}</text>')
    for i, label in enumerate(rows2):
        ay = yy + 10 + i * 34
        ax = x + 210
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
        out.append(f'<text x="{x + 268}" y="{ay + 3.5}" font-size="9.5">'
                   f'{label}</text>')
    for i, label in enumerate(rows3):
        ay = yy + i * 27
        ax = x + 344
        spd = (None if label == "SPEED UNKNOWN"
               else 75 if label == "70 AND UP" else i * 10 + 5)
        u = Unit(1, speed=spd)
        svg, _ = _unit_arrow(ax, ay, 0, 40, u, False)
        out.append(svg)
        out.append(f'<text x="{x + 406}" y="{ay + 3.5}" font-size="8.5">'
                   f'{label}</text>')
    for i, (letter, label, color) in enumerate(rows4):
        ay = yy + i * 27
        out.append(f'<text x="{x + 486}" y="{ay + 4}" font-size="12" '
                   f'fill="{color}" text-anchor="middle">{letter}</text>')
        out.append(f'<text x="{x + 497}" y="{ay + 3.5}" font-size="8.5">'
                   f'{label}</text>')
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


def north_needle(x, y, h=170):
    return (f'<polygon points="{x},{y} {x + 5},{y + h * 0.62} '
            f'{x},{y + h} {x - 5},{y + h * 0.62}" fill="#fff" '
            'stroke="#000" stroke-width="1.2"/>'
            f'<polygon points="{x},{y} {x + 5},{y + h * 0.62} {x},{y + h}" '
            'fill="#000"/>'
            f'<circle cx="{x}" cy="{y + h * 0.62}" r="7" fill="#fff" '
            'stroke="#000"/>'
            f'<text x="{x}" y="{y + h * 0.62 + 3.5}" font-size="9" '
            'text-anchor="middle">N</text>')


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
        svg.append(f'<text x="{lx}" y="{ly}" font-size="16" '
                   f'text-anchor="middle">{lbl}</text>')
        svg.append(f'<text x="{lx}" y="{ly + 20}" font-size="16" '
                   f'text-anchor="middle">{mp:.2f}</text>')
    jn_keep = []
    for jn in layout.get("junctions", []):
        t = (jn["mp"] - lo) / (hi - lo) if hi > lo else 0.5
        if not 0.0 <= t <= 1.0:
            continue
        x, y = road_pt(t)
        a = road_ang(t) + math.pi / 2
        up = jn.get("side", -1)
        svg.append(f'<line x1="{x:.1f}" y1="{y:.1f}" '
                   f'x2="{x + up * 52 * math.cos(a):.1f}" '
                   f'y2="{y + up * 52 * math.sin(a):.1f}" stroke="#000" '
                   'stroke-width="1.1"/>')
        lx = x + up * 62 * math.cos(a)
        ly = y + up * 62 * math.sin(a) + (0 if up < 0 else 12)
        svg.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="12" '
                   f'text-anchor="middle">{jn["label"]}</text>')
        jn_keep.append((lx - 4.2 * len(jn["label"]), ly - 12,
                        lx + 4.2 * len(jn["label"]), ly + 6))

    keep_out = [(1040, 10, 1632, 400), (1300, 826, 1632, 1056),
                (210, 905, 560, 1040), (430, 20, 1050, 280),
                (0, 830, 200, 1056), (1460, 360, 1632, 446)]
    keep_out += jn_keep
    keep_out += [tuple(r) for r in layout.get("keep_out", [])]

    def clear(ox, oy, halfw):
        x0, y0 = ox - halfw - 16, oy - 40
        x1, y1 = ox + halfw + 16, oy + 40
        if x0 < 26 or x1 > PAGE_W - 26 or y0 < 26 or y1 > PAGE_H - 26:
            return False
        return not any(x0 < kx1 and x1 > kx0 and y0 < ky1 and y1 > ky0
                       for kx0, ky0, kx1, ky1 in keep_out)

    # crashes anchor to the roadway: assemblies sit in a tight ladder just
    # off the line at their milepost, stepping back along the road when a
    # milepost stacks several, the way the drawn sheets arrange them
    overflow: list[str] = []
    placed = []           # (x, y, halfw)
    for cr in sorted([c for c in crashes if c.mp is not None],
                     key=lambda c: (c.mp, c.seq)):
        t = (cr.mp - lo) / (hi - lo) if hi > lo else 0.5
        t = min(1.0, max(0.0, t))
        bx, by = road_pt(t)
        ang = math.degrees(road_ang(t))
        g, halfw = crash_glyph(cr, base_ang=ang,
                               route_forward=layout.get("route_forward",
                                                        "E"))
        nx, ny = _rot(0, -1, ang)
        txx, txy = _rot(-1, 0, ang)

        pref = 0
        if cr.acc_typ in (ROR_TYPES | {18, 19}) and cr.units:
            base = ang - _DIR_ANG.get(layout.get("route_forward", "E"), 0)
            ua = base + _DIR_ANG.get(cr.units[0].direction, -base)
            side = -1 if cr.acc_typ == 2 else 1
            fa = math.radians(ua + side * 42)
            pref = 1 if math.cos(fa) * nx + math.sin(fa) * ny > 0 else -1
        cands = []
        for v in range(5):
            for h in (0, -1, 1, -2, 2, -3, 3):
                for sd in (1, -1):
                    cands.append((v + abs(h) * 0.8 +
                                  (0.05 if sd < 0 else 0) +
                                  (2.5 if pref and sd != pref else 0),
                                  v, h, sd))
        cands.sort()

        def spot(v, h, sd):
            dist = 34 + v * 58
            return (bx + sd * nx * dist - txx * h * 84,
                    by + sd * ny * dist - txy * h * 84)

        pick = fallback = None
        for _, v, h, sd in cands:
            ox, oy = spot(v, h, sd)
            if not clear(ox, oy, halfw):
                continue
            if fallback is None:
                fallback = (ox, oy)
            if not any(abs(ox - px) < (halfw + pw) * 0.72
                       and abs(oy - py) < 50 for px, py, pw in placed):
                pick = (ox, oy)
                break
        if pick is None:
            overflow.append(cr.crash_id)
        ox, oy = pick or fallback or spot(0, 0, 1)
        placed.append((ox, oy, halfw))
        dx, dy = layout.get("nudges", {}).get(cr.crash_id, (0, 0))
        svg.append(f'<g transform="translate({ox + dx:.1f},'
                   f'{oy + dy:.1f})">{g}</g>')

    if overflow:
        print(f"  placement overflow (overdrawn): {overflow}")
    return _sheet(svg, layout, crashes)


def _sheet(body_svg: list, layout: dict, crashes) -> str:
    svg = [f'<rect x="14" y="14" width="{PAGE_W - 28}" '
           f'height="{PAGE_H - 28}" fill="#fff" stroke="#000" '
           'stroke-width="2"/>']
    tx = layout.get("title_x", 760)
    for i, line in enumerate(layout.get("title", [])):
        svg.append(f'<text x="{tx}" y="{58 + i * 26}" font-size="20" '
                   f'text-anchor="middle">{line}</text>')
    svg.append(legend_block(1058, 26))
    svg.append(north_needle(layout.get("north_x", 1010), 40))
    rl = layout.get("route_label", [])
    rx, ry = layout.get("route_label_xy", (520, 940))
    for i, line in enumerate(rl):
        svg.append(f'<text x="{rx}" y="{ry + i * 24}" font-size="17" '
                   f'text-anchor="middle">{line}</text>')
    for note in layout.get("notes", []):
        for i, line in enumerate(note["text"]):
            svg.append(f'<text x="{note["x"]}" y="{note["y"] + i * 17}" '
                       f'font-size="13" text-anchor="middle">{line}</text>')
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
