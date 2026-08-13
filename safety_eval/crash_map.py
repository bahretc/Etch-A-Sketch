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
        "date": 13, "s": 18, "type": 19}


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
                   pad_deg: float = 0.004) -> dict:
    """Everything the map draws, as one JSON-ready dict.

    ``coords_source`` defaults to the workbook itself: the fiche workbook the
    app builds carries its own DetailedFiche sheet, so no extra file is
    needed. ``features`` are ``(label, milepost)`` pairs - the same pairs the
    feature-inclusion list uses - split onto the map as mile markers (label
    starting MILE MARKER), curve points (label containing CURVE), or plain
    labelled points. ``window`` is ``(lo, hi, label)`` for the shaded
    sub-section.
    """
    import openpyxl

    from .hsip import fiche_sheet_name

    coords_source = coords_source or workbook_path
    pts = parse_shape_points(coords_source, route)
    shape = clean_shape(pts)
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
        c = {"id": cid,
             "status": str(ws.cell(row=r, column=_COL["status"]).value
                           or "").strip(),
             "coded_mp": (round(float(coded), 3)
                          if isinstance(coded, (int, float)) else None),
             "new_mp": (round(float(new), 3)
                        if isinstance(new, (int, float)) else None),
             "type": (str(typed).strip()
                      if isinstance(typed, str)
                      and not typed.startswith("=") else ""),
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

    # Spread exact-duplicate coordinates in a small ring (about 2.5 m) so
    # stacked crashes stay individually clickable; popups carry the truth.
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
    # this was built for).
    la0 = min(p[0] for p in line) - pad_deg
    la1 = max(p[0] for p in line) + pad_deg
    lo0 = min(p[1] for p in line) - pad_deg
    lo1 = max(p[1] for p in line) + pad_deg
    crashes = [c for c in crashes
               if la0 <= c["lat"] <= la1 and lo0 <= c["lon"] <= lo1]

    overlays: dict = {"limits": [], "markers": [], "points": [],
                      "window": None}
    for mp, label in ((lo, f"MP {lo:.3f} (study begin)"),
                      (hi, f"MP {hi:.3f} (study end)")):
        la, ln = _mp_to_ll(shape, mp)
        overlays["limits"].append({"mp": round(mp, 3), "label": label,
                                   "lat": round(la, 6), "lon": round(ln, 6)})
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
        overlays["window"] = {
            "lo": wlo, "hi": whi, "label": label,
            "line": [[round(la, 6), round(ln, 6)] for la, ln in
                     (_mp_to_ll(shape, wlo + i * (whi - wlo) / 24)
                      for i in range(25))]}

    counts: dict = {}
    for c in crashes:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    study = ws.title.replace("_Fiche", "")
    return {"study": study, "route": route, "lo": lo, "hi": hi,
            "subtitle": subtitle, "line": line, "crashes": crashes,
            "overlays": overlays, "counts": counts}


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
    bits = [x for x in (county and f"{county} County",
                        f"MP {d['lo']:.3f} to {d['hi']:.3f}",
                        f"{n_in} crashes in the analysis "
                        f"({k.get('IS', 0)} IS, {k.get('RE', 0)} RE, "
                        f"{k.get('ADD', 0)} ADD)",
                        d.get("subtitle") or "") if x]
    rows = [("#0072B2", "IS &mdash; in study"),
            ("#E69F00", "RE &mdash; remileposted (dashed line = the move)"),
            ("#009E73", "ADD &mdash; added from report review"),
            ("#6b7280", "DEL &mdash; deleted (animal / not in study)"),
            ("#b8bec7", "NIS &mdash; not in study (context)")]
    legend = "".join(
        f'<div class="row"><span class="dot" style="background:{c}"></span>'
        f'<span>{t}</span></div>' for c, t in rows)
    if d["overlays"].get("window"):
        legend += ('<div class="row"><span class="band"></span><span>'
                   + d["overlays"]["window"]["label"] + "</span></div>")
    legend += ('<div class="note">RE and ADD are placed at the engineer\'s '
               "New MP on the centreline; other positions are DetailedFiche "
               "coordinates. The dotted centreline is derived from the "
               "corridor's coded crashes, so placements are approximate. "
               "Click any point for details.</div>")

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{d['route']} Crash Map - Study {d['study']}</title>
<style>{vendor('leaflet.min.css')}</style>
<style>{vendor('crashmap.css')}</style></head><body>
<div id="hdr"><h1>{d['route']} Crash Map &middot; Study {d['study']}</h1>
<span class="sub">{" &middot; ".join(bits)}</span></div>
<div id="map"></div>
<div id="legend">{legend}</div>
<script>{vendor('leaflet.min.js')}</script>
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
                    zooms=DEFAULT_ZOOMS, progress=None) -> dict:
    """One call: data join, tile fetch, render. Returns a summary dict."""
    data = build_map_data(workbook_path, route, lo, hi, sheet=sheet,
                          coords_source=coords_source, features=features,
                          window=window, subtitle=subtitle)
    tiles, misses = ({}, 0)
    if basemap:
        tiles, misses = fetch_tiles(data, zooms=zooms, progress=progress)
    size = render_map_html(data, tiles, out_path, county=county)
    return {"crashes": len(data["crashes"]), "counts": data["counts"],
            "tiles": len(tiles), "misses": misses, "bytes": size}
