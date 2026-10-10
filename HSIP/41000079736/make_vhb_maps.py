#!/usr/bin/env python3
"""Location Map, Area Map and ADT Map for study 41000079736 in the layout of the TSU/VHB package maps
(see the 4100007xxxx_LocationMap.pdf / _AreaMap.pdf / _ADTMap.pdf examples): letter landscape, map frame with a thin
black border, NC county inset top-left with the study county in red, north arrow + scale box bottom-left, footer with
WO Number, PH Number, NCDOT Division, Study Area, Lat/Long and a data-source line.
  Naming follows the package examples: the Location Map is the aerial close-up with the crash-location callout and the
  Area Map is the county-scale route map.
  Location map: Esri World Imagery, about 5,100 ft across; shields and street names sit on the road centrelines taken from
      the NCDOT 2025 AADT traffic-segment lines.
  Area map: drawn from vector data (no basemap tiles, so no stray basemap labels): light grey land, municipal areas
      (NCDOT MunicipalData) a shade darker, water bodies (Esri USA Detailed Water Bodies) grey, secondary roads thin grey and
      the Interstate / US / NC routes bold black (both from the NCDOT State Maintained Roads feature service), route shields,
      municipality names and the NC-SC state line (NCDOT 2016 NC-SC State Boundary); about 21 miles across like the examples.
  ADT map: NCDOT AADT Mapping Application view (station popups), Esri World Topographic Map.
Feature-service responses are cached as GeoJSON in maps/.tiles/ next to the basemap tiles.
Outputs: maps/41000079736_LocationMap.pdf/.png, _AreaMap.pdf/.png, _ADTMap.pdf/.png
"""
import json, math, urllib.parse, urllib.request
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib import font_manager
from matplotlib.path import Path as MPath
from matplotlib.patches import Circle, Rectangle, Polygon, PathPatch
from PIL import Image
import make_maps as M

HERE = Path(__file__).resolve().parent; OUT = HERE / "maps"
WO, PH, DIV = "41000079736", "TSUINT716412", "12"
LAT, LON = M.LAT, M.LON
STUDY_AREA = ["NC 180/NC 226 (Post Rd) at SR 1103", "(Pleasant Dr/Pleasant Hill Church Rd)", "in Cleveland County"]
COUNTY = "CLEVELAND"
PW, PH_IN = 11.0, 8.5                      # letter landscape, inches
FRAME_DEFAULT = (0.22, 1.52, 10.78, 8.32)  # map frame: x0, y0, x1, y1 (inches, origin bottom-left)
FRAME = FRAME_DEFAULT
for cand in ("Carlito", "Liberation Sans", "DejaVu Sans"):
    if any(f.name == cand for f in font_manager.fontManager.ttflist): FONT = cand; break
plt.rcParams["font.family"] = FONT; plt.rcParams["pdf.fonttype"] = 42

NCDOT = "https://services.arcgis.com/NuWFvHYDMVmmxMeM/ArcGIS/rest/services"
ESRI_WATER = "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/USA_Detailed_Water_Bodies/FeatureServer/0"   # Esri Living Atlas
ESRI_TOPO = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
M_PER_DEG_LAT = 111320.0; M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT))


# ---------------------------------------------------------------- data (NCDOT ArcGIS feature services, cached as GeoJSON)
def fetch_features(name, layer, where="1=1", bbox=None, fields="*", tol=None):
    """GeoJSON features (WGS84) of a feature-service layer (NCDOT layer path, or a full layer URL) inside bbox=(w, s, e, n), paged;
    cached in maps/.tiles/<name>.geojson"""
    path = M.CACHE / f"{name}.geojson"; url = layer if layer.startswith("http") else f"{NCDOT}/{layer}"
    if path.exists(): return json.loads(path.read_text())["features"]
    feats, off = [], 0
    while True:
        q = {"where": where, "outFields": fields, "outSR": 4326, "f": "geojson", "resultOffset": off, "resultRecordCount": 1000}
        if bbox: q.update(geometry=",".join(f"{v:.5f}" for v in bbox), geometryType="esriGeometryEnvelope", inSR=4326, spatialRel="esriSpatialRelIntersects")
        if tol: q["maxAllowableOffset"] = tol
        req = urllib.request.Request(f"{url}/query?" + urllib.parse.urlencode(q), headers={"User-Agent": "hsip-map-script/1.0 (NCDOT crash analysis)"})
        d = json.load(urllib.request.urlopen(req, timeout=180))
        if "error" in d: raise RuntimeError(f"{layer}: {d['error']}")
        feats += d["features"]
        if not d.get("properties", {}).get("exceededTransferLimit"): break
        off += len(d["features"])
    M.CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return feats


def lines_of(feature):
    g = feature["geometry"]
    return [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]


def rings_of(feature):
    g = feature["geometry"]
    return [r for poly in g["coordinates"] for r in poly] if g["type"] == "MultiPolygon" else list(g["coordinates"])


def mercator_frame(half_w_m, half_h_m, z=14):
    """Web-Mercator pixel frame centred on the study point, same geometry as make_maps.basemap but without tiles:
    returns (width_px, height_px, lat/lon -> px, metres per px)"""
    mpp = 156543.03392 * math.cos(math.radians(LAT)) / 2 ** z
    cx, cy = M.px(LAT, LON, z); x0, y0 = cx - half_w_m / mpp, cy - half_h_m / mpp
    def to_px(lat, lon):
        X, Y = M.px(lat, lon, z); return X - x0, Y - y0
    return 2 * half_w_m / mpp, 2 * half_h_m / mpp, to_px, mpp


def dist_m(a, b):
    """metres between two (lon, lat) points (equirectangular, fine at this scale)"""
    return math.hypot((b[0] - a[0]) * M_PER_DEG_LON, (b[1] - a[1]) * M_PER_DEG_LAT)


def bearing(a, b):
    """degrees clockwise from north, a -> b"""
    return math.degrees(math.atan2((b[0] - a[0]) * M_PER_DEG_LON, (b[1] - a[1]) * M_PER_DEG_LAT)) % 360


def walk(coords, d_m, smooth_m=20.0):
    """(lon, lat, bearing) at d_m metres along the polyline from its first vertex; bearing is the chord over +-smooth_m"""
    def point_at(d):
        acc = 0.0
        for a, b in zip(coords, coords[1:]):
            L = dist_m(a, b)
            if acc + L >= d:
                t = (d - acc) / L if L else 0
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            acc += L
        return tuple(coords[-1])
    p = point_at(d_m); p0 = point_at(max(0.0, d_m - smooth_m)); p1 = point_at(d_m + smooth_m)
    return p[0], p[1], bearing(p0, p1)


def study_legs():
    """The four approach centrelines from the NCDOT 2025 AADT traffic segments (NC 180 = RouteID 30000180023, SR 1103 =
    40001103023), each oriented away from the intersection, keyed by compass leg: NE/SW (NC 180/NC 226), NW/SE (SR 1103)."""
    feats = fetch_features("ncdot_aadt_segments_area", "NCDOT_2025_AADTandTrafficSegments_gdb/FeatureServer/0",
                           bbox=(LON - 0.012, LAT - 0.009, LON + 0.012, LAT + 0.009), fields="RouteID,AADT,AADT_Year")
    node = (LON, LAT); legs = {}
    for f in feats:
        if f["properties"]["RouteID"] not in ("30000180023", "40001103023"): continue
        for line in lines_of(f):
            if min(dist_m(node, line[0]), dist_m(node, line[-1])) > 30: continue
            if dist_m(node, line[-1]) < dist_m(node, line[0]): line = line[::-1]
            b = bearing(line[0], walk(line, 120)[:2])
            key = ("NE", "SE", "SW", "NW")[int(b // 90)]                 # quadrant of the leg's initial bearing
            legs[key] = [tuple(node)] + [tuple(c) for c in line[1:]]
    missing = {"NE", "SE", "SW", "NW"} - set(legs)
    if missing: raise RuntimeError(f"approach legs not found in the AADT segments: {missing}")
    return legs


# ---------------------------------------------------------------- page furniture
def page(frame=FRAME_DEFAULT):
    global FRAME; FRAME = frame
    fig = plt.figure(figsize=(PW, PH_IN))
    fw, fh = FRAME[2] - FRAME[0], FRAME[3] - FRAME[1]
    ax = fig.add_axes([FRAME[0] / PW, FRAME[1] / PH_IN, fw / PW, fh / PH_IN]); ax.set_axis_off()
    return fig, ax, fw, fh


def frame_border(fig):
    fig.add_artist(Rectangle((FRAME[0] / PW, FRAME[1] / PH_IN), (FRAME[2] - FRAME[0]) / PW, (FRAME[3] - FRAME[1]) / PH_IN,
                             transform=fig.transFigure, fill=False, ec="k", lw=1.0, zorder=20))


def inset(fig):
    """NC counties, study county in red, white box at the top-left of the frame"""
    geo = json.loads((OUT / ".tiles" / "nc_counties.geojson").read_text())
    w, h = 2.35, 0.95
    ax = fig.add_axes([(FRAME[0] + 0.02) / PW, (FRAME[3] - h - 0.02) / PH_IN, w / PW, h / PH_IN], zorder=25)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("white")
    for s in ax.spines.values(): s.set_linewidth(0.8)
    for f in geo["features"]:
        name = f["properties"]["NAME"].upper()
        for poly in f["geometry"]["coordinates"]:
            ring = poly[0]
            ax.add_patch(Polygon(ring, closed=True, fc=("#e00000" if name == COUNTY else "white"), ec="#777", lw=0.35, zorder=2))
    ax.set_xlim(-84.4, -75.4); ax.set_ylim(33.75, 36.7); ax.set_aspect(1 / math.cos(math.radians(35.3)))


def north_scale(fig, ax, mpp, units):
    """white box bottom-left of the frame: north arrow in a black disc + alternating scale bar ('feet' or 'miles'); returns its width (in)"""
    fw = FRAME[2] - FRAME[0]
    x0, x1 = ax.get_xlim(); m_per_in = abs(x1 - x0) * mpp / fw          # map metres per page inch
    if units == "feet": segs, lab, unit_m = [0, 300, 600], ["0", "300", "600"], 0.3048
    elif units == "feet2": segs, lab, unit_m = [0, 1000, 2000], ["0", "1,000", "2,000"], 0.3048
    else: segs, lab, unit_m = [0, 0.5, 1, 2], ["0", "0.5", "1", "2"], 1609.344
    bar = segs[-1] * unit_m / m_per_in                                   # bar length, inches
    sx, h = 0.58, 0.48; w = sx + bar + 0.55
    bx = fig.add_axes([(FRAME[0] + 0.02) / PW, (FRAME[1] + 0.02) / PH_IN, w / PW, h / PH_IN], zorder=25)
    bx.set_xlim(0, w); bx.set_ylim(0, h); bx.set_xticks([]); bx.set_yticks([]); bx.set_facecolor("white")
    for s in bx.spines.values(): s.set_linewidth(0.8)
    bx.add_patch(Circle((0.27, h / 2), 0.17, fc="k", ec="k", zorder=3))
    bx.add_patch(Polygon([(0.27, h / 2 + 0.13), (0.19, h / 2 - 0.10), (0.27, h / 2 - 0.04), (0.35, h / 2 - 0.10)], fc="white", ec="white", zorder=4))
    bx.text(0.27, h / 2 - 0.16, "N", ha="center", va="center", fontsize=5, color="white", fontweight="bold", zorder=5)
    y = 0.17
    for i in range(len(segs) - 1):
        a, b = segs[i] * unit_m / m_per_in, segs[i + 1] * unit_m / m_per_in
        bx.add_patch(Rectangle((sx + a, y), b - a, 0.07, fc=("k" if i % 2 == 0 else "white"), ec="k", lw=0.6, zorder=3))
    for sg, l in zip(segs, lab): bx.text(sx + sg * unit_m / m_per_in, y + 0.11, l, ha="center", va="bottom", fontsize=6.5)
    bx.text(sx + bar + 0.06, y + 0.035, "Feet" if units.startswith("feet") else "Miles", ha="left", va="center", fontsize=6.5)
    return w


def footer(fig, source):
    L, R = 0.25, PW - 0.25
    rows = [("WO Number", f" {WO}"), ("PH Number", f" {PH}"), ("NCDOT Division", f" {DIV}")]
    for i, (k, v) in enumerate(rows):
        y = (1.22 - i * 0.30) / PH_IN
        t = fig.text(L / PW, y, k, fontsize=11, fontweight="bold", va="center", ha="left")
        fig.canvas.draw(); bb = t.get_window_extent().transformed(fig.transFigure.inverted())
        fig.text(bb.x1, y, v, fontsize=11, va="center", ha="left")
    fig.text(0.5, 1.22 / PH_IN, "Study Area", fontsize=11, fontweight="bold", ha="center", va="center")
    for i, line in enumerate(STUDY_AREA):
        fig.text(0.5, (0.92 - i * 0.26) / PH_IN, line, fontsize=11, ha="center", va="center")
    fig.text(R / PW, 1.22 / PH_IN, "Lat, Long", fontsize=11, fontweight="bold", va="center", ha="right")
    fig.text(R / PW, 0.92 / PH_IN, f"{LAT:.6f}, {LON:.6f}", fontsize=11, va="center", ha="right")
    fig.text(0.1 / PW, 0.09 / PH_IN, f"Data Source: {source}", fontsize=7.5, style="italic", ha="left", va="center", color="#333")
    logo = HERE / "data" / "vhb_logo.png"                      # firm logo as it appears on the package maps (0.95 x 0.5 in, bottom right)
    if logo.exists():
        lim = Image.open(logo); lw_in, lh_in = 0.95, 0.95 * lim.height / lim.width
        lax = fig.add_axes([(PW - 0.15 - lw_in) / PW, 0.15 / PH_IN, lw_in / PW, lh_in / PH_IN], zorder=30)
        lax.imshow(lim); lax.set_axis_off()


# ---------------------------------------------------------------- labels and shields (sizes in page inches, converted with ppi)
def text_rotation(brg):
    """rotation (deg, counter-clockwise) that runs text along a road of compass bearing brg, never upside down"""
    rot = (90 - brg) % 360
    return rot - 180 if 90 < rot < 270 else rot


def halo_text(ax, x, y, s, rot=0, size=8, color="k", halo="white", weight="normal", z=12):
    ax.text(x, y, s, rotation=rot, rotation_mode="anchor", ha="center", va="center", fontsize=size, color=color, fontweight=weight, zorder=z,
            path_effects=[pe.withStroke(linewidth=2.5, foreground=halo)])


def nc_shield(ax, x, y, num, size=16, fs=6.5):
    """black diamond, white number (size = half-diagonal in image px)"""
    ax.add_patch(Polygon([(x, y - size), (x + size, y), (x, y + size), (x - size, y)], closed=True, fc="k", ec="white", lw=1.0, zorder=12))
    ax.text(x, y, num, ha="center", va="center", fontsize=fs, color="white", fontweight="bold", zorder=13)


US_SHIELD = MPath([(-0.9, 0.5), (-0.95, 0.9), (-0.7, 1.0), (-0.3, 0.85), (-0.15, 0.8), (0.15, 0.8), (0.3, 0.85), (0.7, 1.0), (0.95, 0.9), (0.9, 0.5),
                   (0.95, -0.1), (0.7, -0.6), (0, -0.95), (-0.7, -0.6), (-0.95, -0.1), (-0.9, 0.5), (-0.9, 0.5)],
                  [MPath.MOVETO] + [MPath.CURVE4] * 15 + [MPath.CLOSEPOLY])
I_BODY = MPath([(-0.95, 0.55), (-0.5, 0.75), (0.5, 0.75), (0.95, 0.55), (1.0, 0.0), (0.7, -0.65), (0, -0.95), (-0.7, -0.65), (-1.0, 0.0), (-0.95, 0.55), (-0.95, 0.55)],
               [MPath.MOVETO] + [MPath.CURVE4] * 9 + [MPath.CLOSEPOLY])
I_CROWN = MPath([(-0.95, 0.55), (-0.5, 0.75), (0.5, 0.75), (0.95, 0.55), (0.88, 1.0), (0.5, 0.9), (-0.5, 0.9), (-0.88, 1.0), (-0.95, 0.55), (-0.95, 0.55)],
                [MPath.MOVETO] + [MPath.CURVE4] * 3 + [MPath.LINETO] + [MPath.CURVE4] * 3 + [MPath.LINETO, MPath.CLOSEPOLY])


def _scaled(path, x, y, hw, hh):
    return MPath([(x + vx * hw, y - vy * hh) for vx, vy in path.vertices], path.codes)   # image y axis points down


def us_shield(ax, x, y, num, hw, hh, fs=6.5, banner=None):
    """white US route crest with a black outline; banner (e.g. 'BUS') is written above the crest"""
    ax.add_patch(PathPatch(_scaled(US_SHIELD, x, y, hw, hh), fc="white", ec="k", lw=1.0, zorder=12))
    ax.text(x, y - 0.05 * hh, num, ha="center", va="center", fontsize=fs, color="k", fontweight="bold", zorder=13)
    if banner: halo_text(ax, x, y - 1.35 * hh, banner, size=fs - 1.5, weight="bold", z=13)


def i_shield(ax, x, y, num, hw, hh, fs=6.5):
    """Interstate crest: blue body, red crown, white outline and number"""
    ax.add_patch(PathPatch(_scaled(I_BODY, x, y, hw, hh), fc="#1d3fa0", ec="white", lw=1.0, zorder=12))
    ax.add_patch(PathPatch(_scaled(I_CROWN, x, y, hw, hh), fc="#c8102e", ec="white", lw=1.0, zorder=12))
    ax.text(x, y - 0.12 * hh, num, ha="center", va="center", fontsize=fs, color="white", fontweight="bold", zorder=13)


def red_ring(ax, x, y, r):
    ax.add_patch(Circle((x, y), r, fill=False, ec="#e00000", lw=3.2, zorder=14))


# ---------------------------------------------------------------- Location Map
ROUTE_STYLE = {"1": dict(lw=3.4, color="#1a1a1a", z=7), "2": dict(lw=2.2, color="#222", z=6), "3": dict(lw=1.9, color="#222", z=5)}   # RouteClass: 1 = I, 2 = US, 3 = NC
QUALIFIER = {"0": "", "1": "ALT", "2": "BYP", "3": "BUS", "9": "BUS"}   # NCDOT RouteQualifier -> shield banner (9 = Business, as on US 74 through Shelby / Kings Mountain)
TOWN_NUDGE = {"Patterson Springs": -0.12, "Shelby": 0.14}   # name offsets (page inches, + = up): off the study ring / off the US 74 BUS line
DEBUG = False


def area_map():
    fig, ax, fw, fh = page()
    half_w = 17000.0; half_h = half_w * fh / fw
    W, H, to_px, mpp = mercator_frame(half_w, half_h)
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.set_aspect("equal")
    ppi = W / fw
    dlon, dlat = half_w / M_PER_DEG_LON, half_h / M_PER_DEG_LAT
    bbox = (LON - dlon * 1.05, LAT - dlat * 1.05, LON + dlon * 1.05, LAT + dlat * 1.05)
    def to_in(px, py): return FRAME[0] + px / ppi, FRAME[3] - py / ppi            # map px -> page inches
    def inside(px, py, m=0.0): return m * ppi <= px <= W - m * ppi and m * ppi <= py <= H - m * ppi
    def poly_px(ring): return [to_px(c[1], c[0]) for c in ring]
    # base: land, municipal areas, water bodies, secondary roads (thin grey), like the light grey canvas of the examples
    ax.add_patch(Rectangle((0, 0), W, H, fc="#f0f0f0", ec="none", zorder=0))
    towns = fetch_features("ncdot_municipalities_location", "MunicipalData/FeatureServer/0", bbox=bbox, fields="Municipali,Population", tol=0.0005)
    for f in towns:
        for ring in rings_of(f): ax.add_patch(Polygon(poly_px(ring), closed=True, fc="#e4e4e4", ec="none", zorder=1))
    water = fetch_features("esri_water_bodies_location", ESRI_WATER, bbox=bbox, fields="NAME,FTYPE,SQKM", tol=0.0002)
    for f in water:
        for ring in rings_of(f): ax.add_patch(Polygon(poly_px(ring), closed=True, fc="#cdd0d6", ec="none", zorder=2))
    secondary = fetch_features("ncdot_secondary_roads_location", "NCDOT_StateMaintainedRoadsER/FeatureServer/0", where="RouteClass='4'", bbox=bbox,
                               fields="RouteClass,RouteNumber,RouteID", tol=0.0001)
    for f in secondary:
        for line in lines_of(f):
            pts = poly_px(line); ax.plot([q[0] for q in pts], [q[1] for q in pts], color="#c2c2c2", lw=0.5, solid_capstyle="round", zorder=3)
    # Interstate / US / NC routes (NCDOT State Maintained Roads), thin ones first
    roads = fetch_features("ncdot_routes_location", "NCDOT_StateMaintainedRoadsER/FeatureServer/0", where="RouteClass IN ('1','2','3')", bbox=bbox,
                           fields="RouteClass,RouteNumber,RouteQualifier,RouteName,StreetName,RouteID", tol=0.00005)
    routes = {}
    for f in sorted(roads, key=lambda f: f["properties"]["RouteClass"], reverse=True):
        p = f["properties"]; st = ROUTE_STYLE[p["RouteClass"]]
        for line in lines_of(f):
            pts = [to_px(c[1], c[0]) for c in line]
            ax.plot([q[0] for q in pts], [q[1] for q in pts], color=st["color"], lw=st["lw"], solid_capstyle="round", solid_joinstyle="round", zorder=st["z"])
            routes.setdefault((p["RouteClass"], p["RouteNumber"], QUALIFIER.get(p["RouteQualifier"], "")), []).append(pts)
    # NC - SC state line: yellow with black dashes, labelled on both sides
    state = fetch_features("ncdot_nc_sc_state_line", "NCDOT_2016NCSCStateBoundaryChange/FeatureServer/2", bbox=bbox, fields="OBJECTID")
    sl = [c for f in state for line in lines_of(f) for c in line if bbox[0] <= c[0] <= bbox[2]]
    sl.sort(key=lambda c: c[0]); spx = [to_px(c[1], c[0]) for c in sl]
    ax.plot([q[0] for q in spx], [q[1] for q in spx], color="#f2e600", lw=2.4, zorder=8, solid_capstyle="butt")
    ax.plot([q[0] for q in spx], [q[1] for q in spx], color="k", lw=0.7, ls=(0, (6, 3)), zorder=9)
    for lon_at, bold in ((LON - 0.09, True), (LON + 0.125, False)):
        i = min(range(len(sl)), key=lambda k: abs(sl[k][0] - lon_at)); brg = bearing(sl[max(i - 8, 0)], sl[min(i + 8, len(sl) - 1)])
        rot = text_rotation(brg); nx, ny = -math.sin(math.radians(rot)), -math.cos(math.radians(rot))   # unit normal (image px) to the 'up' side of the text
        for s, side in (("NORTH CAROLINA", 1), ("SOUTH CAROLINA", -1)):
            ax.text(spx[i][0] + nx * side * 0.10 * ppi, spx[i][1] + ny * side * 0.10 * ppi, s, rotation=rot, rotation_mode="anchor", ha="center", va="center",
                    fontsize=7.5 if bold else 6.5, fontweight="bold" if bold else "normal", color="k" if bold else "#666", zorder=11,
                    path_effects=[pe.withStroke(linewidth=2, foreground="white")])
    # study point
    x, y = to_px(LAT, LON); red_ring(ax, x, y, 0.15 * ppi)
    # obstacles for label placement: page-inch boxes (x0, y0, x1, y1) + the ring
    sb_w = 0.58 + 2 * 1609.344 / (2 * half_w / fw) + 0.55
    boxes = [(FRAME[0], FRAME[3] - 1.0, FRAME[0] + 2.4, FRAME[3]), (FRAME[0], FRAME[1], FRAME[0] + sb_w + 0.05, FRAME[1] + 0.53)]
    placed = [(*to_in(x, y), 0.55)]                                   # (x_in, y_in, keep-out radius)
    last = None                                                        # the state line and its labels: keep shields and names off it
    for q in spx:
        qi = to_in(*q)
        if last is None or math.hypot(qi[0] - last[0], qi[1] - last[1]) > 0.25: placed.append((qi[0], qi[1], 0.22)); last = qi
    def clear(px, py, r):
        xi, yi = to_in(px, py)
        if not inside(px, py, 0.32): return False
        if any(bx0 - r < xi < bx1 + r and by0 - r < yi < by1 + r for bx0, by0, bx1, by1 in boxes): return False
        return all(math.hypot(xi - qx, yi - qy) >= r + qr for qx, qy, qr in placed)
    # municipality names (NCDOT MunicipalData polygons -> centroid of the largest ring), sized by population
    for f in sorted(towns, key=lambda f: -(f["properties"]["Population"] or 0)):
        g = f["geometry"]; rings = [p[0] for p in g["coordinates"]] if g["type"] == "MultiPolygon" else [g["coordinates"][0]]
        ring = max(rings, key=len); A = Cx = Cy = 0.0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            w = x0 * y1 - x1 * y0; A += w; Cx += (x0 + x1) * w; Cy += (y0 + y1) * w
        clon, clat = (Cx / (3 * A), Cy / (3 * A)) if A else (sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring))
        name, pop = f["properties"]["Municipali"], f["properties"]["Population"] or 0
        tx, ty = to_px(clat, clon); ty -= TOWN_NUDGE.get(name, 0.0) * ppi
        if not inside(tx, ty, 0.45): continue
        fs = 10.5 if pop > 15000 else 9.5 if pop > 8000 else 8.5 if pop > 3000 else 7.5
        label = name.replace("Kings Mountain", "Kings\nMountain")
        w_in = 0.085 * fs / 10 * max(len(s) for s in label.split("\n")); h_in = 0.16 * fs / 10 * len(label.split("\n"))
        ax.text(tx, ty, label, ha="center", va="center", fontsize=fs, color="#111", zorder=11, linespacing=1.0,
                path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])
        placed.append((*to_in(tx, ty), max(w_in, h_in) / 2 + 0.05))
    # route shields on the drawn lines: candidates are route vertices, chosen to keep clear of everything placed so far
    def frame_length(key):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for line in routes[key] for a, b in zip(line, line[1:]) if inside(*a) and inside(*b)) / ppi
    for key in sorted(routes, key=frame_length):                       # shortest in-frame routes first, so each still finds a clear spot
        cls, num, qual = key; length_in = frame_length(key)
        n_want = 2 if length_in > 5.0 else 1                           # two shields on routes that cross most of the frame
        for sep in (0.26, 0.18, 0.12):                                 # short routes hemmed in by other labels accept a tighter fit
            cands = [q for line in routes[key] for q in line[::3] if clear(q[0], q[1], sep)]
            if cands: break
        if DEBUG: print(f"  {key}: {length_in:.1f} in in frame, {n_want} wanted, {len(cands)} clear candidates (sep {sep}) of {sum(len(l) for l in routes[key])} vertices")
        for _ in range(n_want):
            if not cands: break
            def score(q):
                xi, yi = to_in(*q)
                return min([math.hypot(xi - qx, yi - qy) - qr for qx, qy, qr in placed] + [min(xi - FRAME[0], FRAME[2] - xi, yi - FRAME[1], FRAME[3] - yi)])
            best = max(cands, key=score)
            hw, hh = 0.16 * ppi, 0.15 * ppi
            if cls == "3": nc_shield(ax, best[0], best[1], num, 0.155 * ppi, fs=7)
            elif cls == "2": us_shield(ax, best[0], best[1], num, 0.17 * ppi, 0.15 * ppi, fs=7, banner=qual or None)
            else: i_shield(ax, best[0], best[1], num, 0.18 * ppi, 0.16 * ppi, fs=7)
            placed.append((*to_in(*best), 0.24 + (0.08 if qual else 0)))
            cands = [q for q in cands if clear(q[0], q[1], sep)]
    frame_border(fig); inset(fig); north_scale(fig, ax, mpp, "miles")
    footer(fig, "NCDOT, Esri (water bodies), VHB")
    fig.savefig(OUT / "41000079736_AreaMap.pdf"); fig.savefig(OUT / "41000079736_AreaMap.png", dpi=150); plt.close(fig)  # county-scale = Area Map


# ---------------------------------------------------------------- Area Map
def location_map():
    fig, ax, fw, fh = page()
    half_w = 775.0; half_h = half_w * fh / fw
    im, to_px, mpp = M.basemap(M.ESRI_IMG, 18, half_w, half_h)
    ax.imshow(im); ax.set_xlim(0, im.width); ax.set_ylim(im.height, 0)
    ppi = im.width / fw                                           # image px per page inch
    x, y = to_px(LAT, LON); red_ring(ax, x, y, 0.15 * ppi)
    legs = study_legs()
    def on_leg(key, d_m):
        """image px and local road bearing d_m metres from the intersection along approach leg key"""
        lon, lat, brg = walk(legs[key], d_m); px_, py_ = to_px(lat, lon); return px_, py_, brg
    # callout, upper left, leader to the ring edge
    cx, cy = to_px(LAT + 190 / M_PER_DEG_LAT, LON - 470 / M_PER_DEG_LON)
    ax.annotate("Crash Location: NC 180/NC 226 at SR 1103", xy=(x - 0.12 * ppi, y - 0.08 * ppi), xytext=(cx, cy), fontsize=8, ha="center", va="center", zorder=15,
                bbox=dict(boxstyle="square,pad=0.45", fc="white", ec="k", lw=0.8), arrowprops=dict(arrowstyle="-", color="k", lw=0.8, shrinkA=0, shrinkB=0))
    # NC 180 / NC 226: both diamonds on the centreline one after the other, 'Post Rd' along the pavement between ring and shields
    for key in ("NE", "SW"):
        for num, d in (("180", 340), ("226", 400)):
            sx, sy, _ = on_leg(key, d); nc_shield(ax, sx, sy, num, 0.13 * ppi, fs=6.5)
        nx, ny, brg = on_leg(key, 190); halo_text(ax, nx, ny, "Post Rd", rot=text_rotation(brg), size=7.5, color="white", halo="#222")
    # SR 1103 street names along the pavement
    for key, name, d in (("NW", "Pleasant Dr (SR 1103)", 230), ("SE", "Pleasant Hill Church Rd (SR 1103)", 300)):
        nx, ny, brg = on_leg(key, d); halo_text(ax, nx, ny, name, rot=text_rotation(brg), size=7.5, color="white", halo="#222")
    frame_border(fig); inset(fig); north_scale(fig, ax, mpp, "feet")
    footer(fig, "NCDOT, Esri World Imagery, VHB")
    fig.savefig(OUT / "41000079736_LocationMap.pdf"); fig.savefig(OUT / "41000079736_LocationMap.png", dpi=150); plt.close(fig)  # aerial = Location Map


# ---------------------------------------------------------------- ADT Map (package format: NCDOT AADT Mapping Application view)
CLASS_COLOR = {"Interstates": "#1f6fe0", "US Routes": "#e01010", "NC Hwys": "#b020e0", "Secondary Routes": "#2faa2f"}
CLASS_TX = {"I": "Interstates", "US": "US Routes", "NC": "NC Hwys", "SR": "Secondary Routes"}


def adt_map():
    """Stations from the NCDOT AADT Mapping Application data (data/ncdot_aadt_stations.json, fetch_ncdot_stations.py), each
    study station with its popup (LocationID, COUNTY, RTE_CLS, ROUTE, LOCATION, AADT_2002..AADT_2025) and the year used
    boxed in red, like the 4100007xxxx_ADTMap.pdf examples."""
    import json as _json
    A = _json.loads((HERE / "aadt.json").read_text()); mid = A["entering_aadt"]["study_10yr_middle_year"]; yr = str(mid["year"])
    ST = {s["LocationID"]: s for s in _json.loads((HERE / "data" / "ncdot_aadt_stations.json").read_text())["stations"]}
    STUDY = {"N": "0230000187", "S": "0230000152", "NW": "0230000045", "SE": "0230000531"}
    fig, ax, fw, fh = page()
    half_h = 1150.0; half_w = half_h * fw / fh
    im, to_px, mpp = M.basemap(ESRI_TOPO, 16, half_w, half_h, lat=LAT - 0.0034)
    ax.imshow(im); ax.set_xlim(0, im.width); ax.set_ylim(im.height, 0)
    ppi = im.width / fw
    def page_to_px(xin, yin): return (xin - FRAME[0]) * ppi, (FRAME[3] - yin) * ppi
    # every station in view, coloured by route class
    for sid, st in ST.items():
        sx, sy = to_px(st["lat"], st["lon"])
        if 0 <= sx <= im.width and 0 <= sy <= im.height:
            ax.plot(sx, sy, "o", ms=6.5, color=CLASS_COLOR.get(CLASS_TX.get(st["RTE_CLS_TX"], st["RTE_CLS_TX"]), "k"), mec="none", zorder=13)
    # study intersection
    x, y = to_px(LAT, LON); ax.add_patch(Circle((x, y), 0.11 * ppi, fill=False, ec="#e00000", lw=3.6, zorder=14))
    def popup(sid, box_in, boxed_years):
        """popup pasted from the Mapping Application: white box at box_in=(x, y_top) inches, 1.45 in wide; leader arrow to the station"""
        st = ST[sid]; sx, sy = to_px(st["lat"], st["lon"])
        rows = [("LocationID", sid), ("COUNTY", st["COUNTY"]), ("RTE_CLS", CLASS_TX.get(st["RTE_CLS_TX"], st["RTE_CLS_TX"])), ("ROUTE", st["ROUTE"]), ("LOCATION", st["LOCATION"])]
        rows += [(f"AADT_{y_}", ("" if st["AADT"].get(y_) in (None, "", " ") else f"{int(st['AADT'][y_])}")) for y_ in sorted(st["AADT"])]
        w, lead, top = 1.45, 0.086, 0.17
        h = top + lead * len(rows) + 0.06
        bx = fig.add_axes([box_in[0] / PW, (box_in[1] - h) / PH_IN, w / PW, h / PH_IN], zorder=26)
        bx.set_xlim(0, w); bx.set_ylim(h, 0); bx.set_xticks([]); bx.set_yticks([]); bx.set_facecolor("white")
        for sp in bx.spines.values(): sp.set_linewidth(0.7)
        bx.text(0.05, 0.085, f"NCDOT AADT Stations: {sid}", fontsize=5.6, fontweight="bold", va="center", ha="left")
        bx.plot([0.03, w - 0.03], [0.15, 0.15], color="#444", lw=0.4)
        for i, (k, v) in enumerate(rows):
            yy = top + lead * (i + 0.5)
            bx.text(0.06, yy, k, fontsize=5.2, color="#8a8a8a", va="center", ha="left")
            bx.text(0.62, yy, v, fontsize=5.2, color="#222", va="center", ha="left")
            if k[-4:] in boxed_years:
                bx.add_patch(Rectangle((0.03, yy - lead * 0.46), w - 0.06, lead * 0.92, fill=False, ec="#e00000", lw=1.6, zorder=5))
        # leader arrow: from the box edge nearest the station to the station
        corners = [(box_in[0], box_in[1]), (box_in[0] + w, box_in[1]), (box_in[0], box_in[1] - h), (box_in[0] + w, box_in[1] - h),
                   (box_in[0] + w / 2, box_in[1]), (box_in[0] + w / 2, box_in[1] - h), (box_in[0], box_in[1] - h / 2), (box_in[0] + w, box_in[1] - h / 2)]
        cx, cy = min((page_to_px(*c) for c in corners), key=lambda q: (q[0] - sx) ** 2 + (q[1] - sy) ** 2)
        ax.annotate("", xy=(sx, sy), xytext=(cx, cy), arrowprops=dict(arrowstyle="-|>", color="k", lw=0.8, shrinkA=0, shrinkB=4, mutation_scale=8), zorder=15)
    popup(STUDY["NW"], (0.36, 7.22), {"2018", "2022"})
    popup(STUDY["N"], (9.22, 8.12), {yr})
    popup(STUDY["S"], (4.35, 4.35), {yr})
    popup(STUDY["SE"], (6.95, 4.35), {yr})
    # callouts
    def callout(text, xy_in, target_px, fs=9):
        tx, ty = page_to_px(*xy_in)
        ax.annotate(text, xy=target_px, xytext=(tx, ty), fontsize=fs, ha="center", va="center", zorder=16,
                    bbox=dict(boxstyle="square,pad=0.45", fc="white", ec="k", lw=0.8),
                    arrowprops=dict(arrowstyle="-|>", color="k", lw=0.8, shrinkA=0, shrinkB=6, mutation_scale=9))
    callout("Crash Location: NC 180/NC 226 at SR 1103", (7.6, 6.3), (x + 0.1 * ppi, y - 0.06 * ppi))
    lon_, lat_, _ = walk(study_legs()["NW"], 160)                   # a point on the Pleasant Dr (SR 1103) centreline, 160 m from the intersection
    callout(f"Estimated {yr} AADT: {mid['legs']['NW']:,} vpd\n(interpolated between the 2018 and 2022 counts)", (4.7, 7.6), to_px(lat_, lon_), fs=8)
    # legend (route classes, as in the Mapping Application)
    lw_, lh = 1.95, 1.32
    lg = fig.add_axes([(FRAME[2] - lw_ - 0.02) / PW, (FRAME[1] + 0.02) / PH_IN, lw_ / PW, lh / PH_IN], zorder=25)
    lg.set_xlim(0, lw_); lg.set_ylim(lh, 0); lg.set_xticks([]); lg.set_yticks([]); lg.set_facecolor("white")
    for sp in lg.spines.values(): sp.set_linewidth(0.7)
    for i, (name, col) in enumerate(list(CLASS_COLOR.items()) + [("Non-System Routes", "k")]):
        lg.plot(0.22, 0.2 + i * 0.235, "o", ms=6.5, color=col, mec="none"); lg.text(0.42, 0.2 + i * 0.235, name, fontsize=9, va="center", ha="left")
    frame_border(fig); inset(fig); north_scale(fig, ax, mpp, "feet2")
    footer(fig, "NCDOT AADT Mapping Application (station data), Esri World Topographic Map")
    fig.savefig(OUT / "41000079736_ADTMap.pdf"); fig.savefig(OUT / "41000079736_ADTMap.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    import sys
    which = sys.argv[1:] or ["location", "area", "adt"]
    if "location" in which: location_map()
    if "area" in which: area_map()
    if "adt" in which: adt_map()
    print("wrote", ", ".join(str(OUT / f"41000079736_{n}.pdf") for w, n in (("location", "LocationMap"), ("area", "AreaMap"), ("adt", "ADTMap")) if w in which), "font", FONT)
