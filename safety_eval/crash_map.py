"""The study crash map: one self-contained HTML file.

Joins the engineer's reviewed statuses (the fiche working sheet) with the
DetailedFiche coordinates, draws the corridor from the study's own coded
crash cloud (location.clean_shape), and renders an interactive Leaflet map
with the basemap tiles EMBEDDED as data URIs, so the file opens from a study
folder or an email with no network at all.

Positions are honest by construction and every popup says which kind it got:
RE and ADD crashes sit at the engineer's New MP projected onto the
centreline; everything else sits at its DetailedFiche coordinate. The
centreline is derived from coded crashes (the NCDOT LRS is not reachable
from every environment), so placements are approximate to tens of feet, and
the legend says so.

Tile coverage carries a hard-won rule: at the overview zooms the whole
VIEWPORT must be covered, not just the padded corridor bounds - fitBounds
centres the corridor and a wide screen shows far more ground than the
bounds, which is exactly where grey corners come from. Verified by
screenshotting the rendered file, not by reading the code.
"""
from __future__ import annotations

import base64
import json
import math
import urllib.request
from importlib import resources

from .location import clean_shape
from .review_queue import parse_coordinates, parse_shape_points

#: Basemap sources. Esri World Imagery is the default engineers want (the
#: curves are visible); OSM carries the street names.
TILE_SOURCES = {
    "a": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
          "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
    "s": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
}
_UA = {"User-Agent": "safety-eval crash-map builder"}

#: Overview zooms cover the whole viewport; the deepest zoom covers a band
#: around the corridor (metres), because that is where a reader zooms.
DEFAULT_ZOOMS = (14, 15, 16, 17)
_VIEW_W, _VIEW_H = 1680, 1050
_DEEP_BUFFER_M = 900

#: Working-sheet columns (fiche_workbook.FICHE_COLUMNS, 1-based).
_COL = {"mproad": 7, "mp": 8, "status": 9, "new_mp": 10, "crash_id": 12,
        "date": 13, "c": 15, "s": 18, "type": 19, "dir": 20}


def _load_centerline(path: str, route: str):
    """Route geometry with vertex mileposts, via location.load_route_shape.

    Accepts the GeoJSON conventions that loader documents ([lon, lat, m]
    vertices, or 2D vertices with begin/end MP properties). This is the
    real centreline - LRS or a calibrated OSM trace - and when present it
    replaces the crash-cloud approximation entirely.
    """
    from .location import FeatureInventory, normalize_route

    inv = FeatureInventory()
    inv.load_route_shape(path, route=route)
    pts = inv.shape.get(normalize_route(route)) or []
    if len(pts) < 2:
        raise ValueError(
            f"centerline {path} carries no usable vertices for {route}")
    return pts


def _mp_to_ll(shape, mp):
    """Linear position of a milepost along the cleaned centreline."""
    if mp <= shape[0][0]:
        return shape[0][1], shape[0][2]
    for (m1, la1, lo1), (m2, la2, lo2) in zip(shape, shape[1:]):
        if m1 <= mp <= m2:
            t = 0 if m2 == m1 else (mp - m1) / (m2 - m1)
            return la1 + t * (la2 - la1), lo1 + t * (lo2 - lo1)
    return shape[-1][1], shape[-1][2]


def build_map_data(workbook_path: str, route: str, lo: float, hi: float,
                   sheet: str | None = None,
                   coords_source: str | None = None,
                   features=None, window: tuple | None = None,
                   subtitle: str = "", line_margin_mi: float = 0.35,
                   pad_deg: float = 0.004, diagram: bool = False,
                   targets=None, centerline: str | None = None,
                   diagram_round: float = 0.1) -> dict:
    """Everything the map draws, as one JSON-ready dict.

    ``coords_source`` defaults to the workbook itself: the fiche workbook the
    app builds carries its own DetailedFiche sheet, so no extra file is
    needed. ``features`` are ``(label, milepost)`` pairs - the same pairs the
    feature-inclusion list uses - split onto the map as mile markers (label
    starting MILE MARKER), curve points (label containing CURVE), or plain
    labelled points. ``window`` is ``(lo, hi, label)`` for the shaded
    sub-section. ``centerline`` is a GeoJSON with vertex mileposts (LRS or
    a calibrated trace); when given it IS the corridor, and the
    crash-cloud approximation is not used at all.
    """
    import openpyxl

    from .hsip import fiche_sheet_name

    coords_source = coords_source or workbook_path
    if centerline:
        shape = _load_centerline(centerline, route)
        shape_src = "lrs"
    else:
        pts = parse_shape_points(coords_source, route)
        shape = clean_shape(pts)
        shape_src = "crash-cloud"
        if len(shape) < 2:
            raise ValueError(
                f"the DetailedFiche in {coords_source} carries no usable "
                f"coordinates on {route}; cannot draw the corridor")
    coords = parse_coordinates(coords_source)

    from .location import normalize_route
    route_key = normalize_route(route)

    wb = openpyxl.load_workbook(workbook_path)
    ws = wb[sheet or fiche_sheet_name(wb)]
    crashes = []
    for r in range(2, ws.max_row + 1):
        cid = ws.cell(row=r, column=_COL["crash_id"]).value
        if cid is None:
            continue
        cid = str(cid).strip()
        coded = ws.cell(row=r, column=_COL["mp"]).value
        new = ws.cell(row=r, column=_COL["new_mp"]).value
        typed = ws.cell(row=r, column=_COL["type"]).value
        date = ws.cell(row=r, column=_COL["date"]).value
        road = str(ws.cell(row=r, column=_COL["mproad"]).value or "")
        dv = ws.cell(row=r, column=_COL["dir"]).value
        c = {"id": cid,
             "dir": (str(dv).strip()
                     if isinstance(dv, str) and dv.strip()
                     and not dv.startswith("=") else ""),
             "status": str(ws.cell(row=r, column=_COL["status"]).value
                           or "").strip(),
             "coded_mp": (round(float(coded), 3)
                          if isinstance(coded, (int, float)) else None),
             "new_mp": (round(float(new), 3)
                        if isinstance(new, (int, float)) else None),
             "type": (str(typed).strip()
                      if isinstance(typed, str)
                      and not typed.startswith("=") else ""),
             "c": (ws.cell(row=r, column=_COL["c"]).value
                   if isinstance(ws.cell(row=r, column=_COL["c"]).value, int)
                   else None),
             "sev": str(ws.cell(row=r, column=_COL["s"]).value or ""),
             "date": (date.strftime("%m/%d/%Y")
                      if hasattr(date, "strftime") else ""),
             "road": road}
        # Placement, most to least direct, the popup naming which one the
        # point got. The DetailedFiche covers only part of the fiche (189 of
        # 368 on the study this was built for), so a crash without a
        # coordinate is placed by its milepost on the centreline rather
        # than silently dropped - dropping them cost the first cut of this
        # module 11 of the 15 IS crashes.
        ll = coords.get(cid)
        moved = c["status"] in ("RE", "ADD") and c["new_mp"] is not None
        if ll is not None:
            c["lat"], c["lon"] = round(ll[0], 6), round(ll[1], 6)
            c["src"] = "position: DetailedFiche coordinate"
            if moved:
                # Drawn at the engineer's New MP; the coded coordinate stays
                # as the tail of the move line.
                la, ln = _mp_to_ll(shape, c["new_mp"])
                c["from_lat"], c["from_lon"] = c["lat"], c["lon"]
                c["lat"], c["lon"] = round(la, 6), round(ln, 6)
                c["src"] = "position: New MP on the centreline"
        else:
            mp = c["new_mp"] if moved else c["coded_mp"]
            if (mp is None or not (shape[0][0] <= mp <= shape[-1][0])
                    or normalize_route(road) != route_key):
                continue                    # nothing places it on this route
            la, ln = _mp_to_ll(shape, mp)
            c["lat"], c["lon"] = round(la, 6), round(ln, 6)
            c["src"] = ("position: New MP on the centreline" if moved
                        else "position: coded MP on the centreline")
        crashes.append(c)

    ladders = []
    if diagram:
        if targets is None:
            from .warrants import ROR_TYPES
            targets = ROR_TYPES
        in_analysis = [c for c in crashes
                       if c["status"] in ("IS", "RE", "ADD")]
        ladders = diagram_layout(in_analysis, shape, targets,
                                 round_to=diagram_round)
        # A collision diagram shows the analysis; everything else drops,
        # and the RE move tails go with it (the badge is not a position,
        # so a line from the coded coordinate to it would mislead).
        crashes = [c for c in in_analysis if c.get("diagram")]
        for c in crashes:
            c.pop("from_lat", None)
            c.pop("from_lon", None)
        line_margin_mi = min(line_margin_mi, 0.15)

    # Spread exact-duplicate coordinates in a small ring (about 2.5 m) so
    # stacked crashes stay individually clickable; popups carry the truth.
    # Not in the diagram: a bucket's badges SHARE their anchor by design
    # and separate by screen offset instead.
    if not diagram:
        groups: dict = {}
        for c in crashes:
            groups.setdefault((c["lat"], c["lon"]), []).append(c)
        for (la, ln), members in groups.items():
            for i, c in enumerate(members[1:], start=1):
                ang = 2 * math.pi * i / max(len(members) - 1, 1)
                c["lat"] = round(la + 2.3e-5 * math.sin(ang), 6)
                c["lon"] = round(ln + 2.8e-5 * math.cos(ang), 6)

    line = [[round(la, 6), round(ln, 6)] for m, la, ln in shape
            if lo - line_margin_mi <= m <= hi + line_margin_mi]
    if len(line) < 2:
        line = [[round(la, 6), round(ln, 6)] for _, la, ln in shape]

    # Only what the map shows: crashes beyond the drawn stretch would
    # balloon the basemap to the whole corridor (11 miles, on the study
    # this was built for). But an ANALYSIS crash is never silently lost
    # to a bad geocode: the DetailedFiche coordinates scatter up to a
    # mile off the road (measured on this study's own corridor), so one
    # whose final milepost is on the drawn stretch relocates to the
    # centreline, popup saying so, instead of dropping off the map.
    la0 = min(p[0] for p in line) - pad_deg
    la1 = max(p[0] for p in line) + pad_deg
    lo0 = min(p[1] for p in line) - pad_deg
    lo1 = max(p[1] for p in line) + pad_deg
    kept = []
    for c in crashes:
        if la0 <= c["lat"] <= la1 and lo0 <= c["lon"] <= lo1:
            kept.append(c)
            continue
        moved = c["status"] in ("RE", "ADD") and c["new_mp"] is not None
        mp = c["new_mp"] if moved else c["coded_mp"]
        if (c["status"] in ("IS", "RE", "ADD") and mp is not None
                and shape[0][0] <= mp <= shape[-1][0]
                and normalize_route(c["road"]) == route_key):
            la, ln = _mp_to_ll(shape, mp)
            c["lat"], c["lon"] = round(la, 6), round(ln, 6)
            c.pop("from_lat", None)
            c.pop("from_lon", None)
            c["src"] = ("position: milepost on the centreline (the "
                        "DetailedFiche coordinate is off this map)")
            kept.append(c)
    crashes = kept

    overlays: dict = {"limits": [], "markers": [], "points": [],
                      "window": None, "ladders": ladders, "mp_ticks": []}
    for mp, label, kind in ((lo, f"MP {lo:.3f} (study begin)", "begin"),
                            (hi, f"MP {hi:.3f} (study end)", "end")):
        la, ln = _mp_to_ll(shape, mp)
        overlays["limits"].append({"mp": round(mp, 3), "label": label,
                                   "kind": kind,
                                   "lat": round(la, 6), "lon": round(ln, 6)})
    if diagram:
        # Green milepost ticks every tenth, the ladders' own scale.
        m = round(math.ceil(round(lo, 6) * 10 - 1e-6) / 10, 1)
        while m <= hi + 1e-9:
            la, ln = _mp_to_ll(shape, m)
            overlays["mp_ticks"].append({"mp": round(m, 1),
                                         "lat": round(la, 6),
                                         "lon": round(ln, 6)})
            m = round(m + 0.1, 1)
        # The BEGIN/END callouts stay BESIDE their dots - a label that
        # drifts down the road mislabels the study limit. Each box sits
        # just off the road on the ladder-free side (outward along the
        # road when both sides ladder); the map view, not the label,
        # makes room for the legend (crashmap.js widens the left fit
        # padding until nothing hides under it).
        for lim, sign in ((overlays["limits"][0], -1),
                          (overlays["limits"][1], 1)):
            ux, uy, _cos = _bearing_at(shape, lim["mp"])
            near = {}
            for ld in ladders:
                if abs(ld["mp"] - lim["mp"]) <= 0.06:
                    near[ld["dir"]] = min(near.get(ld["dir"], 9e9),
                                          ld["len"])
            free = [side for side in ("WB", "EB") if side not in near]
            if free:
                side = free[0]
                pang = next((ld["angle"] for ld in ladders
                             if ld["dir"] == side), None)
                if pang is None:
                    s = -1 if side == "EB" else 1   # eb_side default
                    pang = math.degrees(math.atan2(-ux * s, -uy * s))
                ox = math.cos(math.radians(pang)) * 54
                oy = math.sin(math.radians(pang)) * 54
            else:
                ox, oy = sign * 78 * ux, sign * 78 * -uy
            lim["off"] = [round(ox), round(oy)]
    for label, mp in features or ():
        la, ln = _mp_to_ll(shape, float(mp))
        item = {"mp": round(float(mp), 3), "label": str(label),
                "lat": round(la, 6), "lon": round(ln, 6)}
        up = str(label).upper()
        if up.startswith(("MILE MARKER", "*MILE", "MM ")):
            item["short"] = "MM " + up.split()[-1]
            overlays["markers"].append(item)
        else:
            overlays["points"].append(item)
    if window:
        wlo, whi = float(window[0]), float(window[1])
        label = (window[2] if len(window) > 2 and window[2]
                 else f"sub-section MP {wlo:.3f} to {whi:.3f}")
        mid_la, mid_ln = _mp_to_ll(shape, (wlo + whi) / 2)
        overlays["window"] = {
            "lo": wlo, "hi": whi, "label": label,
            "mid": [round(mid_la, 6), round(mid_ln, 6)],
            "line": [[round(la, 6), round(ln, 6)] for la, ln in
                     (_mp_to_ll(shape, wlo + i * (whi - wlo) / 24)
                      for i in range(25))]}
        if diagram:
            # The hotspot callout goes on the side OPPOSITE the tallest
            # in-window ladder, past whatever ladders that side has - a
            # screen offset like the ladders themselves, so it clears
            # them at any zoom and the fit pads stay balanced.
            inw = [ld for ld in ladders
                   if wlo - 0.05 <= ld["mp"] <= whi + 0.05]
            tallest = max(inw, key=lambda ld: ld["len"], default=None)
            lside = ("WB" if (tallest or {}).get("dir") == "EB" else "EB")
            opp = max((ld["len"] for ld in inw if ld["dir"] == lside),
                      default=40)
            reach = opp + 70
            ang = next((ld["angle"] for ld in ladders
                        if ld["dir"] == lside), None)
            if ang is None:
                ux, uy, _cos = _bearing_at(shape, (wlo + whi) / 2)
                s = -1 if lside == "EB" else 1  # eb_side default
                ang = math.degrees(math.atan2(-ux * s, -uy * s))
            overlays["window"]["label_off"] = [
                round(math.cos(math.radians(ang)) * reach),
                round(math.sin(math.radians(ang)) * reach)]

    counts: dict = {}
    for c in crashes:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    study = ws.title.replace("_Fiche", "")
    data = {"study": study, "route": route, "lo": lo, "hi": hi,
            "subtitle": subtitle, "line": line, "crashes": crashes,
            "overlays": overlays, "counts": counts,
            "diagram": bool(diagram), "shape_src": shape_src,
            "diagram_round": diagram_round}
    if diagram:
        # The tight crop: the studied stretch plus the badge anchors -
        # ladders and callouts live in screen space, so their reach
        # becomes fitBounds PADDING (data["pad"], px per side) rather
        # than geography.
        core = [(la, ln) for m, la, ln in shape
                if lo - 0.06 <= m <= hi + 0.06]
        core += [(c["lat"], c["lon"]) for c in crashes]
        if core:
            data["fit_bounds"] = [
                [round(min(p[0] for p in core), 6),
                 round(min(p[1] for p in core), 6)],
                [round(max(p[0] for p in core), 6),
                 round(max(p[1] for p in core), 6)]]
        pad = [40.0, 60.0, 150.0, 40.0]     # left, top, right, bottom
        def grow(ex, ey, m=13):
            pad[0] = max(pad[0], -ex + m)
            pad[1] = max(pad[1], -ey + m)
            pad[2] = max(pad[2], ex + m)
            pad[3] = max(pad[3], ey + m)
        for ld in ladders:
            ang = math.radians(ld["angle"])
            grow(math.cos(ang) * (ld["len"] + 15),
                 math.sin(ang) * (ld["len"] + 15))
        w = overlays.get("window") or {}
        if w.get("label_off"):
            ox, oy = w["label_off"]
            grow(ox - 150, oy - 27, 0)
            grow(ox + 150, oy + 27, 0)
        for lim in overlays["limits"]:
            if lim.get("off"):
                ox, oy = lim["off"]
                grow(ox - 58, oy - 19, 0)
                grow(ox + 58, oy + 19, 0)
        data["pad"] = [round(p) for p in pad]
    return data


#: Collision-diagram grammar, read off the engineer's 41000078675 example:
#: severity letter in the badge, Target/Other fill, road-condition ring.
_COND_BUCKET = {1: "Dry", 2: "Wet", 3: "Wet", 4: "Snow", 5: "Snow"}
_SEV_LETTERS = {"O", "C", "B", "A", "K"}
#: The hundredths (MPRound2) layout is composed at this zoom - the
#: letter-print fit - the way a plotted exhibit is composed at one scale.
_COMPOSE_Z = 15


def _bearing_at(shape, mp):
    """Unit vector along the road at a milepost, in planar degrees.

    Zero-length segments are skipped, not divided by: a crash-cloud
    shape can put two bucket medians at the same point, and normalising
    that noise once flipped a BEGIN callout to the wrong side of the
    study.
    """
    def seg(a, b):
        (_, la1, lo1), (_, la2, lo2) = a, b
        cos = math.cos(math.radians(la1)) or 1e-9
        dx, dy = (lo2 - lo1) * cos, (la2 - la1)
        n = math.hypot(dx, dy)
        return (dx / n, dy / n, cos) if n >= 1e-7 else None
    for a, b in zip(shape, shape[1:]):
        if a[0] <= mp <= b[0] or (b[0] == shape[-1][0] and mp >= b[0]):
            got = seg(a, b)
            if got:
                return got
    for a, b in zip(shape, shape[1:]):
        got = seg(a, b)
        if got:
            return got
    return 1.0, 0.0, 1.0


def diagram_layout(crashes, shape, targets, step_px: float = 34,
                   base_px: float = 48, eb_side: int = -1,
                   round_to: float = 0.1) -> list:
    """Ladder the crashes off the roadway, collision-diagram style.

    Crashes bucket by final milepost rounded to ``round_to`` - 0.1 mile
    (the example's MPRound1) by default, 0.01 for its finer MPRound2 -
    AND by direction of travel: crashes travelling with
    increasing milepost (EB on US 74) ladder off one side of the road,
    the opposing direction off the other, exactly like the engineer's
    ArcGIS layout. Every badge in a bucket anchors at the SAME point on
    the road - the rounded milepost - and steps outward in SCREEN
    PIXELS, not ground feet: the symbols are fixed-size, so only a
    fixed-pixel step keeps a stack separated at every zoom and on the
    printed page alike (a ground-feet step spans 12 px or 60 px
    depending on the fitted zoom, and 12 px is half a badge - measured
    overlap, the first version's mistake). Badges carry the severity
    letter; ``targets`` decides the Target/Other fill; the ring is the
    road-condition bucket off the C code.

    ``eb_side`` is the perpendicular sign the increasing-MP direction
    ladders on (-1 = the driver's right for that direction). Mutates the
    crash dicts in place - ``odx``/``ody`` are each badge's screen
    offset from its anchor - and returns the ladder guide lines as
    anchor + screen angle + pixel length.
    """
    buckets: dict = {}
    for c in crashes:
        mp = c.get("new_mp") if c.get("new_mp") is not None \
            else c.get("coded_mp")
        if mp is None:
            c["diagram"] = False
            continue
        c["_mp"] = float(mp)
        d = (c.get("dir") or "").upper()
        dcode = "WB" if d.startswith(("WB", "SB")) else "EB"
        # Power-of-ten grids keep decimal rounding (13.05 -> 13.1, the
        # TEAAS convention); other grids (0.05) snap arithmetically.
        if round_to in (0.1, 0.01):
            grid = round(float(mp), 1 if round_to == 0.1 else 2)
        else:
            grid = round(round(float(mp) / round_to) * round_to, 3)
        buckets.setdefault((grid, dcode), []).append(c)
    # One shared road bearing for every ladder: locally-perpendicular
    # ladders CONVERGE as they run out on a curve, and adjacent deep
    # stacks tangle at their far ends. Parallel columns - the print
    # idiom - never can. (Local bearings return only if the corridor
    # bends so far the mean direction degenerates.)
    mean_uxy = None
    if buckets:
        vx = vy = 0.0
        for bmp, _dcode in buckets:
            a = min(max(bmp, shape[0][0]), shape[-1][0])
            ux, uy, _ = _bearing_at(shape, a)
            vx += ux
            vy += uy
        n = math.hypot(vx, vy)
        if n > 0.3 * len(buckets):
            mean_uxy = (vx / n, vy / n)

    def decorate(c):
        c["diagram"] = True
        c["sev"] = (c.get("sev") or "O").strip().upper()[:1]
        if c["sev"] not in _SEV_LETTERS:
            c["sev"] = "O"
        c["cond"] = _COND_BUCKET.get(c.get("c"), "Unknown")
        t = (c.get("type") or "").upper()
        c["target"] = ("Target" if any(t.startswith(x.upper())
                                      or x.upper() in t
                                      for x in targets) else "Other")

    def frame(bmp, dcode):
        anchor = min(max(bmp, shape[0][0]), shape[-1][0])
        ux, uy = mean_uxy or _bearing_at(shape, anchor)[:2]
        s = eb_side if dcode == "EB" else -eb_side
        px, py = -uy * s, ux * s                # perpendicular (E, N)
        return (_mp_to_ll(shape, anchor), (px, -py), (ux, -uy))

    # The exhibit is composed at ONE scale (z15, the letter-print fit),
    # the way a plotted sheet is - guaranteeing separation at every
    # zoom instead forced a reach ratchet whose cascades marched a mile
    # off the road (reviewed verdict: hot garbage). At the composition
    # scale the anchor pitch decides the layout: a grid the symbols fit
    # between (0.1, or 0.05 with the smaller symbols) draws classic
    # columns; a finer grid (0.01) falls back to collision-composed
    # reaches, where isolated crashes sit at the road and only true
    # near-neighbours stack.
    fine = round_to < 0.1                   # 20 px symbols, tighter steps
    badge = 20 if fine else 26
    step = 24.0 if fine else step_px
    base = 42.0 if fine else base_px
    mid_lat = shape[len(shape) // 2][1]
    m_per_px = (156543.03392 * math.cos(math.radians(mid_lat))
                / 2 ** _COMPOSE_Z)
    px_per_mi = 1609.344 / m_per_px
    pitch = round_to * px_per_mi
    ladders = []
    if pitch < badge + 1:
        # Anchors closer than a symbol at composition scale: composed
        # reaches with a symbol of clearance in (along-px, reach) space.
        rung, clear = step / 2, badge + 2
        sides: dict = {}
        for (bmp, dcode), members in sorted(buckets.items()):
            sides.setdefault(dcode, []).append((bmp, members))
        for dcode in sorted(sides):
            placed = []                     # (along_px, reach)
            for bmp, members in sorted(sides[dcode]):
                (ala, aln), (sx, sy), (tx, ty) = frame(bmp, dcode)
                members.sort(key=lambda c: (c["_mp"],
                                            c.get("date") or "",
                                            c["id"]))
                s = bmp * px_per_mi
                top = base
                for c in members:
                    reach = base
                    while any(math.hypot(s - ps, reach - pr) < clear
                              for ps, pr in placed):
                        reach += rung
                    placed.append((s, reach))
                    top = max(top, reach)
                    c["lat"], c["lon"] = round(ala, 6), round(aln, 6)
                    c["odx"] = round(sx * reach, 1)
                    c["ody"] = round(sy * reach, 1)
                    decorate(c)
                ladders.append(
                    {"mp": bmp, "dir": dcode, "n": len(members),
                     "lat": round(ala, 6), "lon": round(aln, 6),
                     "angle": round(math.degrees(math.atan2(sy, sx)), 1),
                     "len": round(top - 8)})
                for c in members:
                    c.pop("_mp", None)
        return ladders

    for (bmp, dcode), members in sorted(buckets.items()):
        members.sort(key=lambda c: (c["_mp"], c.get("date") or "",
                                    c["id"]))
        (ala, aln), (sx, sy), (tx, ty) = frame(bmp, dcode)
        # A stack deeper than 4 splits into two staggered columns (the
        # example CSV's Offset1/Offset2), halving the ladder's reach so
        # the fitted zoom stays close instead of shrinking the road to
        # make room for one long chain. Only when the anchor pitch can
        # afford the doubled width - on the 0.05 grid it cannot, so
        # those stacks stay single columns.
        double = len(members) > 4 and pitch >= 1.5 * badge
        reach = 0.0
        for i, c in enumerate(members):
            if double:
                q = i % 2
                reach = base + (i // 2) * step + q * step / 2
                lat_off = 11 if q else -11
            else:
                reach = base + i * step
                lat_off = 0
            c["lat"], c["lon"] = round(ala, 6), round(aln, 6)
            c["odx"] = round(sx * reach + tx * lat_off, 1)
            c["ody"] = round(sy * reach + ty * lat_off, 1)
            decorate(c)
        ladders.append({"mp": bmp, "dir": dcode, "n": len(members),
                        "lat": round(ala, 6), "lon": round(aln, 6),
                        "angle": round(math.degrees(math.atan2(sy, sx)), 1),
                        "len": round(reach if not double
                                     else base + ((len(members) - 1) // 2)
                                     * step + 8)})
        for c in members:
            c.pop("_mp", None)
    return ladders


def _ll2t(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def tiles_needed(data: dict, zooms=DEFAULT_ZOOMS,
                 view=(_VIEW_W, _VIEW_H),
                 deep_buffer_m: float = _DEEP_BUFFER_M) -> list:
    """The ``(z, x, y)`` set one basemap needs. Pure; no network.

    Zooms up to 16 cover the whole viewport centred on the corridor (the
    grey-corner lesson); deeper zooms cover a band around the centreline,
    where a reader actually zooms.
    """
    line = data["line"]
    lats = [p[0] for p in line]
    lons = [p[1] for p in line]
    cen_la, cen_lo = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    out = []
    for z in zooms:
        if z <= 16:
            mpp = 156543.03392 * math.cos(math.radians(cen_la)) / (2 ** z)
            half_w = mpp * view[0] / 2 + 300
            half_h = mpp * view[1] / 2 + 300
            dlon = half_w / (111320 * math.cos(math.radians(cen_la)))
            dlat = half_h / 110540
            x0, y0 = _ll2t(cen_la + dlat, cen_lo - dlon, z)
            x1, y1 = _ll2t(cen_la - dlat, cen_lo + dlon, z)
            out += [(z, x, y) for x in range(min(x0, x1), max(x0, x1) + 1)
                    for y in range(min(y0, y1), max(y0, y1) + 1)]
            continue
        dlat = deep_buffer_m / 110540
        dlon = deep_buffer_m / (111320 * math.cos(math.radians(cen_la)))
        wanted = set()
        for la, ln in line:
            x0, y0 = _ll2t(la + dlat, ln - dlon, z)
            x1, y1 = _ll2t(la - dlat, ln + dlon, z)
            wanted |= {(z, x, y)
                       for x in range(min(x0, x1), max(x0, x1) + 1)
                       for y in range(min(y0, y1), max(y0, y1) + 1)}
        out += sorted(wanted)
    return out


def fetch_tiles(data: dict, kinds=("a", "s"), zooms=DEFAULT_ZOOMS,
                timeout: float = 20, progress=None) -> tuple:
    """Download and base64 the basemap tiles. Returns ``(tiles, misses)``.

    A missed tile renders as a blank square, never an error; misses are
    reported so the caller can say so.
    """
    wanted = tiles_needed(data, zooms=zooms)
    tiles: dict = {}
    misses = 0
    for kind in kinds:
        url_t = TILE_SOURCES[kind]
        for i, (z, x, y) in enumerate(wanted):
            url = url_t.format(z=z, x=x, y=y)
            try:
                req = urllib.request.Request(url, headers=_UA)
                with urllib.request.urlopen(req, timeout=timeout) as fh:
                    blob = fh.read()
                if blob[:3] != b"\xff\xd8\xff" and blob[:8] != \
                        b"\x89PNG\r\n\x1a\n":
                    raise ValueError("not an image")
                mime = ("image/jpeg" if blob[:3] == b"\xff\xd8\xff"
                        else "image/png")
                tiles[f"{kind}/{z}/{x}/{y}"] = (
                    f"data:{mime};base64,"
                    + base64.b64encode(blob).decode())
            except Exception:
                misses += 1
            if progress and i % 50 == 0:
                progress(kind, i, len(wanted))
    return tiles, misses


def render_map_html(data: dict, tiles: dict, out_path: str,
                    county: str = "") -> int:
    """Write the single self-contained HTML file. Returns its byte size."""
    def vendor(name):
        return (resources.files("safety_eval") / "vendor" / name).read_text(
            encoding="utf-8")

    zs = sorted({int(k.split("/")[1]) for k in tiles}) or list(DEFAULT_ZOOMS)
    d = dict(data)
    d["zmin"], d["zmax"] = min(zs), max(zs)
    d["basemaps"] = sorted({k.split("/")[0] for k in tiles}) or ["a"]

    k = d["counts"]
    n_in = (k.get("IS", 0) + k.get("RE", 0) + k.get("ADD", 0))
    # The IS/RE/ADD breakdown is review-process detail: it stays on the
    # working crash map, whose legend is those statuses, and off the
    # diagram exhibit, whose audience only needs the count.
    count = (f"{n_in} crashes in the analysis" if d.get("diagram")
             else f"{n_in} crashes in the analysis "
                  f"({k.get('IS', 0)} IS, {k.get('RE', 0)} RE, "
                  f"{k.get('ADD', 0)} ADD)")
    bits = [x for x in (county and f"{county} County",
                        f"MP {d['lo']:.3f} to {d['hi']:.3f}", count,
                        d.get("subtitle") or "") if x]
    if d.get("diagram"):
        def loct(fill, ring="#767b85", letter="", lcolor="#111111"):
            return ('<span class="lwrap">'
                    f'<span class="loct" style="background:{ring}">'
                    f'<span class="in" style="background:{fill};'
                    f'color:{lcolor}">{letter}'
                    "</span></span></span>")
        red_style = ' style="color:#c00000;font-weight:600"'
        # K and A letters are red IN the swatch, exactly as on the
        # badges themselves - a legend that recolours the symbol it
        # explains is wrong.
        sev_rows = "".join(
            f'<div class="row">'
            f'{loct("#ffffff", "#767b85", k, "#c00000" if red else "#111111")}'
            f'<span{red_style if red else ""}>{t}</span></div>'
            for k, t, red in (("K", "K - Fatal", True),
                              ("A", "A - Serious Injury", True),
                              ("B", "B - Minor Injury", False),
                              ("C", "C - Possible Injury", False),
                              ("O", "O - Property Damage Only", False)))
        # Road condition is the badge's RING, so the swatches are rings
        # too - the condition colour around a white inner, exactly what
        # the symbol shows - never filled dots. Snow is white (see the
        # RING note in crashmap.js); the swatch wrapper's hairline
        # shadow keeps it visible on the white box.
        cond_rows = "".join(
            f'<div class="row">{loct("#ffffff", c)}<span>{t}</span></div>'
            for c, t in (("#111111", "Dry"), ("#31b4e8", "Wet"),
                         ("#f4f7fa", "Snow"), ("#8a8f98", "Unknown")))
        legend = (
            '<div class="box"><div class="h">Crash Type</div>'
            f'<div class="row">{loct("#ffe14d")}<span>Target</span></div>'
            f'<div class="row">{loct("#c9ccd1")}<span>Other</span></div>'
            "</div>"
            f'<div class="box"><div class="h">Crash Severity</div>{sev_rows}'
            "</div>"
            f'<div class="box"><div class="h">Road Condition</div>{cond_rows}'
            "</div>")
    else:
        rows = [("#0072B2", "IS &mdash; in study"),
                ("#E69F00", "RE &mdash; remileposted (dashed line = the move)"),
                ("#009E73", "ADD &mdash; added from report review"),
                ("#6b7280", "DEL &mdash; deleted (animal / not in study)"),
                ("#b8bec7", "NIS &mdash; not in study (context)")]
        legend = "".join(
            f'<div class="row"><span class="dot" style="background:{c}"></span>'
            f'<span>{t}</span></div>' for c, t in rows)
    if d["overlays"].get("window") and not d.get("diagram"):
        # The diagram's HOT SPOT callout on the map already names the
        # window; a legend row would say it twice.
        legend += ('<div class="row"><span class="band"></span><span>'
                   + d["overlays"]["window"]["label"] + "</span></div>")
    lrs = d.get("shape_src") == "lrs"
    if d.get("diagram"):
        # One caveat a reviewer must have - the stacks are counts, not
        # offsets - and nothing else.
        step = d.get("diagram_round", 0.1)
        legend += (f'<div class="note">Crashes group to the nearest '
                   f"{step:g} mile by direction of travel; distance "
                   "from the road is stacking order, not "
                   "position.</div>")
    elif lrs:
        legend += ('<div class="note">RE and ADD are placed at the '
                   "engineer's New MP on the route centreline; other "
                   "positions are DetailedFiche coordinates. Click any "
                   "point for details.</div>")
    else:
        legend += ('<div class="note">RE and ADD are placed at the engineer\'s '
               "New MP on the centreline; other positions are DetailedFiche "
               "coordinates. The dotted centreline is derived from the "
               "corridor's coded crashes, so placements are approximate. "
               "Click any point for details.</div>")

    north = ""
    kind_word = "Collision Diagram" if d.get("diagram") else "Crash Map"
    if d.get("diagram"):
        north = ('<div id="north" aria-label="North">'
                 '<svg viewBox="0 0 24 30" width="26" height="32">'
                 '<polygon points="12,2 18,20 12,16 6,20" fill="#111827"/>'
                 '<text x="12" y="29" text-anchor="middle" '
                 'font-size="9" font-weight="700" fill="#111827">N</text>'
                 "</svg></div>")
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{d['route']} {kind_word} - Study {d['study']}</title>
<style>{vendor('leaflet.min.css')}</style>
<style>{vendor('crashmap.css')}</style></head><body>
<div id="hdr"><h1>{d['route']} {kind_word} &middot; Study {d['study']}</h1>
<span class="sub">{" &middot; ".join(bits)}</span></div>
<div id="map"></div>
<div id="legend"{' class="diagram"' if d.get('diagram') else ''}>{legend}</div>
{north}<script>{vendor('leaflet.min.js')}</script>
<script>window.DATA={json.dumps(d)};</script>
<script>window.TILES={json.dumps(tiles)};</script>
<script>{vendor('crashmap.js')}</script>
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return len(html.encode("utf-8"))


def build_crash_map(out_path: str, workbook_path: str, route: str,
                    lo: float, hi: float, sheet: str | None = None,
                    coords_source: str | None = None, features=None,
                    window: tuple | None = None, subtitle: str = "",
                    county: str = "", basemap: bool = True,
                    zooms=DEFAULT_ZOOMS, progress=None,
                    diagram: bool = False, targets=None,
                    centerline: str | None = None,
                    diagram_round: float = 0.1) -> dict:
    """One call: data join, tile fetch, render. Returns a summary dict."""
    data = build_map_data(workbook_path, route, lo, hi, sheet=sheet,
                          coords_source=coords_source, features=features,
                          window=window, subtitle=subtitle,
                          diagram=diagram, targets=targets,
                          centerline=centerline,
                          diagram_round=diagram_round)
    tiles, misses = ({}, 0)
    if basemap:
        # The diagram has no layer switcher, so one basemap (aerial).
        kinds = ("a",) if diagram else ("a", "s")
        tiles, misses = fetch_tiles(data, kinds=kinds, zooms=zooms,
                                    progress=progress)
    size = render_map_html(data, tiles, out_path, county=county)
    return {"crashes": len(data["crashes"]), "counts": data["counts"],
            "tiles": len(tiles), "misses": misses, "bytes": size}


def export_gis(out_path: str, workbook_path: str, route: str,
               lo: float, hi: float, sheet: str | None = None,
               coords_source: str | None = None,
               centerline: str | None = None, targets=None,
               window: tuple | None = None,
               route_id: str = "") -> tuple:
    """The diagram as DATA: a GeoJSON (plus a CSV twin) for ArcGIS.

    Every analysis crash sits at its EXACT final milepost on the
    centreline, with the grouping schemes precomputed as columns the way
    the engineer's AttributeTable carries them - MPRound1/Offset1 (0.1),
    MPRound05/Offset05 (0.05) and MPRound2/Offset2 (0.01) - so the
    exhibit can be composed in GIS at any sheet scale. The centreline,
    study limits and warrant window ride along as their own features.
    Returns ``(crash_count, csv_path)``.
    """
    import csv as _csv

    import openpyxl

    from .hsip import fiche_sheet_name
    from .warrants import ROR_TYPES

    coords_source = coords_source or workbook_path
    if centerline:
        shape = _load_centerline(centerline, route)
    else:
        shape = clean_shape(parse_shape_points(coords_source, route))
        if len(shape) < 2:
            raise ValueError(
                f"the DetailedFiche in {coords_source} carries no usable "
                f"coordinates on {route}; cannot place the crashes")
    if targets is None:
        targets = ROR_TYPES
    wb = openpyxl.load_workbook(workbook_path)
    ws = wb[sheet or fiche_sheet_name(wb)]
    rows = []
    for r in range(2, ws.max_row + 1):
        cid = ws.cell(row=r, column=_COL["crash_id"]).value
        status = str(ws.cell(row=r, column=_COL["status"]).value
                     or "").strip()
        if cid is None or status not in ("IS", "RE", "ADD"):
            continue
        coded = ws.cell(row=r, column=_COL["mp"]).value
        new = ws.cell(row=r, column=_COL["new_mp"]).value
        mp = (float(new) if status in ("RE", "ADD")
              and isinstance(new, (int, float))
              else float(coded) if isinstance(coded, (int, float)) else None)
        if mp is None:
            continue
        typed = ws.cell(row=r, column=_COL["type"]).value
        dv = ws.cell(row=r, column=_COL["dir"]).value
        date = ws.cell(row=r, column=_COL["date"]).value
        sev = str(ws.cell(row=r, column=_COL["s"]).value or "O").strip()
        cval = ws.cell(row=r, column=_COL["c"]).value
        lval = ws.cell(row=r, column=17).value
        ctype = (str(typed).strip() if isinstance(typed, str)
                 and not typed.startswith("=") else "")
        dirv = (str(dv).strip() if isinstance(dv, str)
                and not dv.startswith("=") else "")
        rows.append({
            "id": str(cid).strip(), "status": status, "mp": round(mp, 3),
            "coded": (round(float(coded), 3)
                      if isinstance(coded, (int, float)) else None),
            "dir": dirv,
            "side": "WB" if dirv.upper().startswith(("WB", "SB")) else "EB",
            "type": ctype, "sev": sev.upper()[:1],
            "cond": _COND_BUCKET.get(cval, "Unknown"),
            "l": lval if isinstance(lval, int) else "",
            "date": (date.strftime("%m/%d/%Y")
                     if hasattr(date, "strftime") else ""),
            "target": 1 if any(ctype.upper().startswith(x.upper())
                               or x.upper() in ctype.upper()
                               for x in targets) else 0})
    rows.sort(key=lambda x: (x["mp"], x["date"], x["id"]))

    def ranks(grid):
        counts: dict = {}
        out = {}
        for row in rows:
            key = (round(round(row["mp"] / grid) * grid, 3), row["side"])
            counts[key] = counts.get(key, 0) + 1
            out[row["id"]] = (key[0], counts[key])
        return out

    r1, r05, r2 = ranks(0.1), ranks(0.05), ranks(0.01)
    feats = []
    csv_rows = []
    for i, row in enumerate(rows, start=1):
        la, ln = _mp_to_ll(shape, row["mp"])
        props = {
            "CrashNum": i, "CrashID": row["id"], "Status": row["status"],
            "RouteID": route_id, "Route": route, "Direction": row["dir"],
            "Dir": row["side"], "MP": row["mp"], "CodedMP": row["coded"],
            "MPRound1": r1[row["id"]][0], "Offset1": r1[row["id"]][1],
            "MPRound05": r05[row["id"]][0], "Offset05": r05[row["id"]][1],
            "MPRound2": r2[row["id"]][0], "Offset2": r2[row["id"]][1],
            "CrashType": row["type"], "TargetFlag": row["target"],
            "Injury": row["sev"], "RoadCond": row["cond"],
            "LightCond": row["l"], "CrashDate": row["date"],
            "Latitude": round(la, 6), "Longitude": round(ln, 6)}
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Point",
                                   "coordinates": [round(ln, 6),
                                                   round(la, 6)]}})
        csv_rows.append(props)
    line = [[round(p[2], 6), round(p[1], 6)] for p in shape
            if lo - 0.15 <= p[0] <= hi + 0.15]
    feats.append({"type": "Feature",
                  "properties": {"Layer": "Centerline", "Route": route,
                                 "RouteID": route_id},
                  "geometry": {"type": "LineString", "coordinates": line}})
    for mp, kind in ((lo, "Begin Study"), (hi, "End Study")):
        la, ln = _mp_to_ll(shape, mp)
        feats.append({"type": "Feature",
                      "properties": {"Layer": kind, "MP": round(mp, 3)},
                      "geometry": {"type": "Point",
                                   "coordinates": [round(ln, 6),
                                                   round(la, 6)]}})
    if window:
        wlo, whi = float(window[0]), float(window[1])
        wline = [[round(ln, 6), round(la, 6)] for la, ln in
                 (_mp_to_ll(shape, wlo + i * (whi - wlo) / 24)
                  for i in range(25))]
        feats.append({"type": "Feature",
                      "properties": {"Layer": "Warrant Window",
                                     "BeginMP": wlo, "EndMP": whi,
                                     "Label": (window[2]
                                               if len(window) > 2 else "")},
                      "geometry": {"type": "LineString",
                                   "coordinates": wline}})
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh)
    csv_path = out_path.rsplit(".", 1)[0] + ".csv"
    cols = list(csv_rows[0]) if csv_rows else []
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(csv_rows)
    return len(csv_rows), csv_path
