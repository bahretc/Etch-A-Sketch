"""The three package maps of a strip study in the VHB figure format.

Location Map  aerial (Esri World Imagery) with Begin Study and End Study
              markers, road names, the study route named along its line,
              and the crash circled with a text box for a fatal slip.
Area Map      soft vector style (pale land, white roads with grey casings,
              blue-grey highways, water, town names, route shields) with a
              red pin at the section midpoint.
AADT Map      AADT Mapping Application look: station dots by route class
              with the legend, the governing stations' attribute panels with
              leader lines and the median-year row boxed red, the study route
              traced cyan, the study limits and the circled crash.

Every figure sits in a black-bordered frame with a white page margin over a
footer strip (WO Number, PH Number when there is one, NCDOT Division, Study
Area, Coordinates, the vhb logo, data source line) and an NC county locator
inset with the study county filled red.

Inputs come from public services and are cached beside the outputs:
route centerline and AADT stations from the NCDOT AADT services
(``route_geometry``, ``aadt_arcgis``), roads, places and hydrography from
the Census TIGERweb services, tiles from Esri. A study is described by a
small YAML (see :class:`MapSpec` and ``load_spec``); ``build_maps`` writes
the HTML pages and ``print_pdfs`` prints them with Chromium through
Playwright at 1056 x 816 landscape.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from importlib import resources

from .aadt_arcgis import STATIONS_2025_URL
from .route_geometry import Centerline, load_centerline

TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
_UA = {"User-Agent": "safety-eval package-maps"}
PAGE_W, PAGE_H = 1056, 816
FRAME_W, FRAME_H, MAP_H = 1022, 782, 680
CLASS_COLOR = {"1": "#3B6FB5", "2": "#E8112D", "3": "#B14FC5",
               "4": "#38A800", "8": "#000000"}
CLASS_NAME = {"1": "Interstates", "2": "US Routes", "3": "NC Routes",
              "4": "Secondary Routes", "8": "Non-System Routes"}


# ------------------------------------------------------------------ spec
@dataclass
class MapSpec:
    wo: str
    division: str
    county: str
    route: str                      # "US 311"
    route_id: str                   # AADT RouteID, "20000311034"
    mp_lo: float
    mp_hi: float
    description: list = field(default_factory=list)   # footer Study Area lines
    ph: str = ""
    road_label: str = ""            # "Walnut Cove Road"
    crash_lat: float | None = None
    crash_lon: float | None = None
    crash_text: str = ""            # HTML allowed (<br>)
    coords_text: str = ""           # footer; defaults to the crash point
    median_year: int = 2024
    stations: list = field(default_factory=list)      # governing station ids
    area_half: tuple = (0.085, 0.157)                 # deg lat, deg lon
    aadt_half: tuple = (0.0235, 0.0435)
    location_zoom: int = 15
    loc_label_offset: tuple = (170, 30)
    aadt_label_offset: tuple = (215, 95)
    aadt_limit_offsets: tuple = ((-120, 40), (120, -40))
    loc_limit_offsets: tuple = ((-110, 46), (110, -46))
    loc_shift_lon: float = -0.004   # nudge the aerial frame off a mosaic seam

    @property
    def coords(self) -> str:
        if self.coords_text:
            return self.coords_text
        if self.crash_lat is not None:
            return f"{self.crash_lat:.5f}, {self.crash_lon:.5f}"
        return ""


def load_spec(path: str) -> MapSpec:
    import yaml
    with open(path, encoding="utf-8") as fh:
        d = yaml.safe_load(fh) or {}
    known = {f for f in MapSpec.__dataclass_fields__}
    kw = {k: v for k, v in d.items() if k in known}
    for key in ("area_half", "aadt_half", "loc_label_offset",
                "aadt_label_offset", "loc_limit_offsets", "loc_limit_offsets"):
        if key in kw and isinstance(kw[key], list):
            kw[key] = tuple(tuple(x) if isinstance(x, list) else x
                            for x in kw[key])
    for key in ("aadt_limit_offsets",):
        if key in kw and isinstance(kw[key], list):
            kw[key] = tuple(tuple(x) for x in kw[key])
    unknown = sorted(set(d) - known)
    if unknown:
        raise ValueError(f"unknown keys in the map spec: {', '.join(unknown)}")
    return MapSpec(**kw)


# ------------------------------------------------------------ data pulls
def arc_query(url: str, bbox: tuple, fields: str = "*", geom: bool = True,
              timeout: int = 180) -> list:
    """Every feature of an ArcGIS layer inside a (lat0, lon0, lat1, lon1)
    box, paged through resultOffset; Esri JSON features."""
    feats, off = [], 0
    while True:
        params = {"where": "1=1",
                  "geometry": f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}",
                  "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                  "spatialRel": "esriSpatialRelIntersects",
                  "outFields": fields,
                  "returnGeometry": "true" if geom else "false",
                  "outSR": "4326", "f": "json", "resultOffset": str(off),
                  "resultRecordCount": "1000"}
        req = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(params)}", headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            d = json.loads(fh.read().decode("utf-8"))
        if "error" in d:
            raise RuntimeError(f"{url}: {d['error']}")
        got = d.get("features", [])
        feats += got
        if not d.get("exceededTransferLimit") or not got:
            return feats
        off += len(got)


def _cached(cache_dir: str, name: str, producer):
    path = os.path.join(cache_dir, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    data = producer()
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def fetch_tiger(bbox: tuple, cache_dir: str) -> dict:
    """Roads (primary, secondary, local), incorporated places and hydro."""
    roads = _cached(cache_dir, "tiger_roads.json", lambda: [
        dict(layer=layer, **f)
        for layer in (2, 6, 8)
        for f in arc_query(f"{TIGER}Transportation/MapServer/{layer}/query",
                           bbox, "NAME,MTFCC,RTTYP")])
    places = _cached(cache_dir, "tiger_places.json", lambda: [
        f["attributes"] for f in arc_query(
            f"{TIGER}Places_CouSub_ConCity_SubMCD/MapServer/4/query", bbox,
            "NAME,CENTLAT,CENTLON,LSADC", geom=False)])
    hydro = _cached(cache_dir, "tiger_hydro.json", lambda: [
        f for layer in (0, 1)
        for f in arc_query(f"{TIGER}Hydro/MapServer/{layer}/query", bbox,
                           "NAME,MTFCC")])
    return {"roads": roads, "places": places, "hydro": hydro}


def fetch_stations(bbox: tuple, cache_dir: str,
                   service_url: str = STATIONS_2025_URL) -> list:
    return _cached(cache_dir, "aadt_stations.json",
                   lambda: arc_query(f"{service_url}/query", bbox, "*"))


# ------------------------------------------------------------ road model
_SUFF = (("Road", "Rd"), ("Street", "St"), ("Lane", "Ln"), ("Drive", "Dr"),
         ("Parkway", "Pkwy"), ("Trail", "Trl"), ("Avenue", "Ave"),
         ("Highway", "Hwy"), ("Court", "Ct"), ("Circle", "Cir"),
         ("Place", "Pl"), ("Terrace", "Ter"))


def abbr(name: str) -> str:
    for a, b in _SUFF:
        if name.endswith(" " + a):
            return name[: -len(a)] + b
    return name


def ref_of(name: str) -> str:
    n = name or ""
    m = re.match(r"^(?:US|Us) (?:Hwy )?(\d+)", n)
    if m:
        return f"US {m.group(1)}"
    m = re.match(r"^(?:State Hwy|Nc|NC|N C) (\d+)", n)
    if m:
        return f"NC {m.group(1)}"
    m = re.match(r"^(?:I|Interstate)[- ](\d+)", n)
    if m:
        return f"I {m.group(1)}"
    return ""


def ways_from_tiger(roads: list) -> list:
    ways = []
    for f in roads:
        a = f["attributes"]
        mt = a.get("MTFCC")
        if mt not in ("S1100", "S1200", "S1400"):
            continue
        hw = {"S1100": "primary", "S1200": "secondary",
              "S1400": "residential"}[mt]
        nm = a.get("NAME") or ""
        if mt == "S1400" and re.match(r"^(State Rd|Sr)\s*\d", nm):
            nm = ""
        for path in f.get("geometry", {}).get("paths", []):
            ways.append({"tags": {"highway": hw, "name": nm,
                                  "ref": ref_of(nm)},
                         "geometry": [{"lat": p[1], "lon": p[0]}
                                      for p in path]})
    return ways


def refs(w) -> list:
    return [r for r in w["tags"].get("ref", "").split(";") if r]


def clip_ways(ways, b, classify) -> dict:
    out = defaultdict(list)
    m = 0.004
    for w in ways:
        g = w.get("geometry") or []
        if not any(b[0] - m <= p["lat"] <= b[2] + m
                   and b[1] - m <= p["lon"] <= b[3] + m for p in g):
            continue
        cls = classify(w)
        if cls:
            out[cls].append([[round(p["lat"], 5), round(p["lon"], 5)]
                             for p in g])
    return dict(out)


def _angle(a, c, lat):
    ang = math.degrees(math.atan2(-(c["lat"] - a["lat"]),
                                  (c["lon"] - a["lon"])
                                  * math.cos(math.radians(lat))))
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    return round(ang, 1)


def road_name_labels(ways, b, cap, cls_css, minsep=70, oy=-11, skip=(),
                     avoid=(), avoidpx=40, map_w=FRAME_W, map_h=MAP_H) -> list:
    latpx = map_h / (b[2] - b[0])
    lonpx = map_w / (b[3] - b[1])
    by = defaultdict(list)
    for w in ways:
        nm = w["tags"].get("name")
        if not nm or nm in skip or w["tags"].get("ref"):
            continue
        g = [p for p in (w.get("geometry") or [])
             if b[0] <= p["lat"] <= b[2] and b[1] <= p["lon"] <= b[3]]
        if len(g) >= 2:
            by[nm].append(g)
    items = sorted(((nm, max(s, key=len)) for nm, s in by.items()),
                   key=lambda x: -len(x[1]))
    placed, out = [], []
    mlat, mlon = (b[2] - b[0]) * 0.04, (b[3] - b[1]) * 0.035
    for nm, seg in items:
        if len(out) >= cap:
            break
        i = len(seg) // 2
        mid = seg[i]
        if not (b[0] + mlat <= mid["lat"] <= b[2] - mlat
                and b[1] + mlon <= mid["lon"] <= b[3] - mlon):
            continue
        if (mid["lat"] > b[2] - 0.17 * (b[2] - b[0])
                and mid["lon"] < b[1] + 0.24 * (b[3] - b[1])):
            continue                      # locator inset corner
        if any(abs(mid["lon"] - q[1]) * lonpx < minsep
               and abs(mid["lat"] - q[0]) * latpx < minsep for q in placed):
            continue
        if any(abs(mid["lon"] - q[1]) * lonpx < avoidpx
               and abs(mid["lat"] - q[0]) * latpx < avoidpx for q in avoid):
            continue
        placed.append((mid["lat"], mid["lon"]))
        j = i + 1 if i + 1 < len(seg) else i - 1
        a, c = (seg[i], seg[j]) if j > i else (seg[j], seg[i])
        out.append({"ll": [round(mid["lat"], 5), round(mid["lon"], 5)],
                    "html": abbr(nm), "cls": cls_css,
                    "rot": _angle(a, c, mid["lat"]), "ox": 0, "oy": oy})
    return out


def shield_points(ways, b, per_ref: int = 2) -> list:
    """One or two shield positions per route ref in the frame, at the
    midpoints of the longest in-frame runs, far apart."""
    by = defaultdict(list)
    for w in ways:
        for r in refs(w):
            g = [p for p in w["geometry"]
                 if b[0] <= p["lat"] <= b[2] and b[1] <= p["lon"] <= b[3]]
            if len(g) >= 2:
                by[r].append(g)
    out = []
    mlat, mlon = (b[2] - b[0]) * 0.05, (b[3] - b[1]) * 0.04
    for r, segs in by.items():
        segs.sort(key=len, reverse=True)
        picked = []
        for seg in segs:
            mid = seg[len(seg) // 2]
            if not (b[0] + mlat <= mid["lat"] <= b[2] - mlat
                    and b[1] + mlon <= mid["lon"] <= b[3] - mlon):
                continue
            if any(abs(mid["lat"] - q[0]) < (b[2] - b[0]) * 0.25
                   and abs(mid["lon"] - q[1]) < (b[3] - b[1]) * 0.25
                   for q in picked):
                continue
            picked.append((mid["lat"], mid["lon"]))
            out.append((r, [round(mid["lat"], 5), round(mid["lon"], 5)]))
            if len(picked) >= per_ref:
                break
    return out


# ----------------------------------------------------------------- svg
def us_shield(num):
    return ('<svg width="26" height="24" viewBox="0 0 26 24">'
            '<path d="M13 22.8 C8.2 19.9 2.2 17.8 2.2 9.7 C2.2 6.8 3 4.8 4 '
            '3.7 C6.3 4.8 8.7 5.2 13 5.2 C17.3 5.2 19.7 4.8 22 3.7 C23 4.8 '
            '23.8 6.8 23.8 9.7 C23.8 17.8 17.8 19.9 13 22.8 Z" fill="#fff" '
            'stroke="#5B6670" stroke-width="1.4"/>'
            f'<text x="13" y="15.8" text-anchor="middle" font-size="9.5" '
            f'font-weight="bold" font-family="Arial" fill="#3C4043">{num}'
            '</text></svg>')


def nc_shield(num):
    fs = 7.5 if len(num) > 2 else 9
    return ('<svg width="26" height="26" viewBox="0 0 26 26">'
            '<rect x="5" y="5" width="16" height="16" '
            'transform="rotate(45 13 13)" fill="#fff" stroke="#5B6670" '
            'stroke-width="1.4"/>'
            f'<text x="13" y="{13 + fs * 0.36:.1f}" text-anchor="middle" '
            f'font-size="{fs}" font-weight="bold" font-family="Arial" '
            f'fill="#3C4043">{num}</text></svg>')


def i_shield(num):
    return ('<svg width="26" height="26" viewBox="0 0 26 26">'
            '<path d="M13 24.6 C6.3 21.7 2 18.6 2 12.9 L2 8.3 C5.3 9.3 9 '
            '9.7 13 9.7 C17 9.7 20.7 9.3 24 8.3 L24 12.9 C24 18.6 19.7 '
            '21.7 13 24.6 Z" fill="#3B6FB5" stroke="#fff" stroke-width="1.1"/>'
            '<path d="M2 8.3 C2 5.2 3 3.3 4.1 2.1 C7 3.5 9.9 4.1 13 4.1 '
            'C16.1 4.1 19 3.5 21.9 2.1 C23 3.3 24 5.2 24 8.3 C20.7 9.3 17 '
            '9.7 13 9.7 C9 9.7 5.3 9.3 2 8.3 Z" fill="#C8452E" '
            'stroke="#fff" stroke-width="1.1"/>'
            f'<text x="13" y="19.6" text-anchor="middle" font-size="8.5" '
            f'font-weight="bold" font-family="Arial" fill="#fff">{num}'
            '</text></svg>')


def shield_svg(ref: str) -> str:
    kind, num = ref.split(" ", 1)
    return {"US": us_shield, "NC": nc_shield, "I": i_shield}[kind](num)


PIN = ('<svg width="26" height="36" viewBox="0 0 26 36">'
       '<path d="M13 1 C6.4 1 1.5 6 1.5 12.2 C1.5 20.6 13 34 13 34 '
       'C13 34 24.5 20.6 24.5 12.2 C24.5 6 19.6 1 13 1 Z" fill="#D93025" '
       'stroke="#A11B12" stroke-width="1"/>'
       '<circle cx="13" cy="12.2" r="4.4" fill="#fff"/></svg>')
NORTH = ('<svg width="26" height="46" viewBox="0 0 26 46">'
         '<polygon points="13,2 21,34 13,27 5,34" fill="#fff" '
         'stroke="#111" stroke-width="1.6"/>'
         '<polygon points="13,2 13,27 5,34" fill="#111"/>'
         '<text x="13" y="44" text-anchor="middle" font-size="10" '
         'font-weight="bold" font-family="Arial" fill="#111">N</text></svg>')


def _vendor_text(name: str) -> str:
    return (resources.files("safety_eval") / "vendor" / name).read_text(
        encoding="utf-8")


def _vendor_bytes(name: str) -> bytes:
    return (resources.files("safety_eval") / "vendor" / name).read_bytes()


def locator_svg(county: str) -> str:
    d = json.loads(_vendor_text("nc_counties.json"))
    lon0, lon1, lat0, lat1 = -84.45, -75.30, 33.70, 36.75
    W = 208.0
    k = W / (lon1 - lon0)
    ky = k / math.cos(math.radians(35.3))
    H = (lat1 - lat0) * ky

    def xy(lon, lat):
        return ((lon - lon0) * k, (lat1 - lat) * ky)
    paths = []
    want = county.lower().replace(" county", "").strip()
    for f in d["features"]:
        geom = f["geometry"]
        polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        dd = []
        for poly in polys:
            for ring in poly:
                pts = [xy(c[0], c[1]) for c in ring]
                dd.append("M" + " L".join(f"{x:.1f},{y:.1f}"
                                          for x, y in pts) + " Z")
        name = (f["properties"].get("NAME", "") or "").lower()
        fill = "#CC1111" if name.replace(" county", "") == want else "#fff"
        paths.append(f'<path d="{" ".join(dd)}" fill="{fill}" '
                     'stroke="#8A8A8A" stroke-width="0.5"/>')
    return (f'<svg width="{W:.0f}" height="{H:.0f}" '
            f'viewBox="0 0 {W:.0f} {H:.0f}">{"".join(paths)}</svg>')


# --------------------------------------------------------------- page
CSS = f"""html,body{{margin:0;width:{PAGE_W}px;height:{PAGE_H}px;background:#fff;
font-family:'Segoe UI',Arial,Helvetica,sans-serif;overflow:hidden;color:#000}}
#frame{{position:absolute;left:16px;top:16px;width:{FRAME_W}px;height:{FRAME_H}px;
border:1.5px solid #000;overflow:hidden;background:#fff}}
#map{{position:absolute;top:0;left:0;right:0;height:{MAP_H}px;background:#fff}}
.leaflet-container{{background:#fff}}
#footer{{position:absolute;left:0;right:0;top:{MAP_H}px;bottom:0;
border-top:1.5px solid #000;background:#fff}}
#fl{{position:absolute;left:16px;top:9px;font-size:12.5px;line-height:1.62}}
#fc{{position:absolute;left:22%;right:22%;top:8px;text-align:center;
font-size:11.5px;line-height:1.5}}
.fh{{font-weight:bold;font-size:12.5px}}
#fr{{position:absolute;right:26px;top:8px;font-size:12px;line-height:1.6;
text-align:center}}
#vhb{{position:absolute;right:16px;bottom:12px;height:40px;width:auto}}
#ds{{position:absolute;left:12px;bottom:3px;font-size:8.5px;font-style:italic;
color:#555}}
#locator{{position:absolute;top:10px;left:10px;z-index:1300;background:#fff;
border:1px solid #999;padding:3px;line-height:0}}
#north{{position:absolute;left:14px;bottom:122px;z-index:1300}}
.panel{{position:absolute;z-index:1300;background:#fff;border:1px solid #777;
width:172px;font-size:8.4px;line-height:1.33}}
.panel .bd{{padding:3px 6px 4px}}
.panel .row{{display:flex}}
.panel .row b{{color:#9A9A9A;font-weight:normal;width:66px;flex-shrink:0}}
.panel .row span{{word-break:break-word}}
.panel .row.hot{{outline:2px solid #E8112D;outline-offset:-1px}}
#alegend{{position:absolute;right:12px;bottom:122px;z-index:1300;background:#fff;
border:1px solid #999;padding:6px 12px 7px;font-size:10.5px}}
#alegend .r{{display:flex;align-items:center;gap:8px;margin-top:3px}}
#alegend .r:first-child{{margin-top:0}}
#leader{{position:absolute;inset:0;z-index:1250;pointer-events:none}}
.lblc{{position:relative}}
.lblc>span{{position:absolute;white-space:nowrap;text-align:center;
display:inline-block;line-height:1.15}}
.rn{{color:#2E3033;font-weight:600;font-size:9.5px;
text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,
0 0 2.5px #fff}}
.rn.a{{color:#fff;font-size:10px;text-shadow:-1px -1px 0 #222,1px -1px 0 #222,
-1px 1px 0 #222,1px 1px 0 #222,0 0 3px #000}}
.gn{{color:#9AA0A6;font-weight:600;font-size:9px;text-shadow:-1px -1px 0 #fff,
1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff}}
.tn{{color:#3C4043;font-weight:bold;font-size:12.5px;
text-shadow:-1.5px -1.5px 0 #fff,1.5px -1.5px 0 #fff,-1.5px 1.5px 0 #fff,
1.5px 1.5px 0 #fff,0 0 3px #fff}}
.bx{{background:#fff;border:1.2px solid #000;color:#000;font-weight:bold;
font-size:11px;padding:3px 10px}}
.badge{{background:#fff;border:1.4px solid #000;border-radius:50%;width:15px;
height:15px;font-size:9.5px;font-weight:bold;line-height:15px;text-align:center}}
"""

JS = r"""(function(){
const P=window.P;
if(P.mapbg) document.getElementById("map").style.background=P.mapbg;
const map=L.map("map",{zoomControl:false,attributionControl:false,
  zoomSnap:1,minZoom:P.minz,maxZoom:P.maxz});
if(window.TILES){
  const BLANK="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAAB"+
    "AAEAAAICTAEAOw==";
  const Base=L.TileLayer.extend({getTileUrl:function(c){
    return window.TILES["a/"+c.z+"/"+c.x+"/"+c.y]||BLANK;}});
  (new Base("",{minZoom:P.minz,maxZoom:P.maxz})).addTo(map);
}
map.fitBounds(P.fb,{animate:false});
function cpt(ll){return map.latLngToContainerPoint(L.latLng(ll[0],ll[1]));}
function cll(p){return map.containerPointToLatLng(L.point(p[0],p[1]));}
function lbl(ll,html,cls,ox,oy,rot,z){
  const la=(ll.lat!==undefined)?ll.lat:ll[0],
    lo=(ll.lng!==undefined)?ll.lng:ll[1];
  const st="transform:translate(calc(-50% + "+(ox||0)+"px), calc(-50% + "+
    (oy||0)+"px)) rotate("+(rot||0)+"deg)";
  return L.marker([la,lo],{interactive:false,icon:L.divIcon({
    className:"lblc",html:'<span class="'+(cls||"")+'" style="'+st+'">'+
    html+'</span>',iconSize:[0,0]}),zIndexOffset:z||0}).addTo(map);
}
for(const wp of (P.waterPoly||[]))
  L.polygon(wp,{color:"#A9D3E8",weight:1,fillColor:"#BFE0F0",
    fillOpacity:1,interactive:false}).addTo(map);
for(const wl of (P.waterLine||[]))
  L.polyline(wl,{color:"#A9D3E8",weight:1.2,opacity:1,
    interactive:false}).addTo(map);
for(const cls of P.order||[]){
  const passes=P.style[cls], group=P.roads[cls];
  if(!passes||!group) continue;
  for(const spec of passes)
    for(const pts of group)
      L.polyline(pts,Object.assign({interactive:false},spec)).addTo(map);
}
if(P.pin) lbl(P.pin,P.pinSvg,"",0,-16,0,950);
const XMARK='<svg width="27" height="27"><circle cx="13.5" cy="13.5" '+
  'r="10.5" fill="#F5C844" stroke="#5E5320" stroke-width="2"/>'+
  '<line x1="6.5" y1="6.5" x2="20.5" y2="20.5" stroke="#5E5320" '+
  'stroke-width="2.2"/><line x1="20.5" y1="6.5" x2="6.5" y2="20.5" '+
  'stroke="#5E5320" stroke-width="2.2"/></svg>';
for(const m of (P.limits||[])){
  const ap=cpt(m.ll), bc=[ap.x+m.off[0],ap.y+m.off[1]];
  L.polyline([m.ll,cll(bc)],{color:"#000",weight:1.4,
    interactive:false}).addTo(map);
  lbl(cll(bc),m.txt,"bx",0,0,0,800);
  lbl(m.ll,XMARK,"",0,0,0,900);
}
if(P.crash){
  const c=P.crash, ap=cpt(c.ll), bc=[ap.x+c.off[0],ap.y+c.off[1]];
  L.circleMarker(c.ll,{radius:15,color:"#E8100C",weight:3.5,fill:false,
    interactive:false}).addTo(map);
  L.polyline([c.ll,cll(bc)],{color:"#000",weight:1.4,
    interactive:false}).addTo(map);
  lbl(cll(bc),c.txt,"bx",0,0,0,820);
}
for(const s of (P.stations||[]))
  L.circleMarker(s.ll,{radius:5,color:"#fff",weight:1.4,
    fillColor:s.c,fillOpacity:1,interactive:false}).addTo(map);
for(const nb of (P.numbered||[]))
  lbl(nb.ll,'<span class="badge">'+nb.n+'</span>',"",13,-11,0,940);
for(const l of (P.labels||[]))
  lbl(l.ll,l.html,l.cls,l.ox,l.oy,l.rot||0,l.z||0);
if(P.panelLeaders){
  const mr=document.getElementById("map").getBoundingClientRect();
  const svg=document.getElementById("leader");
  svg.setAttribute("width",mr.width);svg.setAttribute("height",mr.height);
  let lines="";
  for(const pl of P.panelLeaders){
    const el=document.getElementById(pl.id);
    if(!el) continue;
    const r=el.getBoundingClientRect();
    const t=cpt(pl.ll);
    const cx=r.left-mr.left+r.width/2, cy=r.top-mr.top+r.height/2;
    const dx=t.x-cx, dy=t.y-cy;
    const tx=dx!==0?(r.width/2)/Math.abs(dx):1e9,
      ty=dy!==0?(r.height/2)/Math.abs(dy):1e9;
    const tt=Math.min(tx,ty);
    lines+='<line x1="'+(cx+dx*tt)+'" y1="'+(cy+dy*tt)+'" x2="'+t.x+
      '" y2="'+t.y+'" stroke="#000" stroke-width="1.3"/>';
  }
  svg.innerHTML=lines;
}
window._map=map;
})();"""


def render_page(spec: MapSpec, title: str, payload: dict, tiles=None,
                panels: str = "", legend: bool = False,
                datasource: str = "") -> str:
    tile_js = f"window.TILES={json.dumps(tiles)};" if tiles else ""
    alegend = ""
    if legend:
        alegend = ('<div id="alegend">' + "".join(
            f'<div class="r"><svg width="11" height="11">'
            f'<circle cx="5.5" cy="5.5" r="4.6" fill="{CLASS_COLOR[k]}"/></svg>'
            f'<span>{CLASS_NAME[k]}</span></div>' for k in "12348") + "</div>")
    logo = base64.b64encode(_vendor_bytes("vhb_logo.png")).decode()
    ph = f"<br><b>PH Number</b> {spec.ph}" if spec.ph else ""
    desc = "<br>".join(spec.description)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title} - {spec.wo}</title>
<style>{_vendor_text('leaflet.min.css')}</style><style>{CSS}</style></head><body>
<div id="frame">
<div id="map"></div>
<svg id="leader"></svg>
<div id="locator">{locator_svg(spec.county)}</div>
{panels}{alegend}
<div id="north">{NORTH}</div>
<div id="footer">
<div id="fl"><b>WO Number</b> {spec.wo}{ph}<br><b>NCDOT Division</b> {spec.division}</div>
<div id="fc"><span class="fh">Study Area</span><br>{desc}</div>
<div id="fr"><span class="fh">Coordinates</span><br>{spec.coords}</div>
<img id="vhb" src="data:image/png;base64,{logo}" alt="vhb">
<div id="ds">Data Source: {datasource}</div>
</div>
</div>
<script>{_vendor_text('leaflet.min.js')}</script>
<script>{tile_js}window.P={json.dumps(payload)};</script>
<script>{JS}</script></body></html>"""


# ------------------------------------------------------------- builders
def _route_label_points(cl: Centerline, lo, hi, fracs=(0.3, 0.7)):
    out = []
    for f in fracs:
        mp = lo + f * (hi - lo)
        ll = cl.mp_to_ll(mp)
        a, b = cl.mp_to_ll(mp - 0.02), cl.mp_to_ll(mp + 0.02)
        ang = _angle({"lat": a[0], "lon": a[1]}, {"lat": b[0], "lon": b[1]},
                     ll[0])
        out.append((list(ll), ang))
    return out


def _crash_payload(spec: MapSpec, off):
    if spec.crash_lat is None:
        return None
    return {"ll": [spec.crash_lat, spec.crash_lon], "off": list(off),
            "txt": spec.crash_text or "Crash"}


def location_payload(spec: MapSpec, cl: Centerline, ways: list,
                     tile_fetch=None, cache_dir: str = "") -> tuple:
    """(payload, tiles) for the aerial location map at ``spec.location_zoom``
    with the frame sized so the tiles are not scaled."""
    study = cl.polyline(spec.mp_lo, spec.mp_hi)
    clat = (study[0][0] + study[-1][0]) / 2
    clon = (study[0][1] + study[-1][1]) / 2 + spec.loc_shift_lon
    ppd = 256 * 2 ** spec.location_zoom / 360          # px per deg lon
    half_lon = FRAME_W / ppd / 2
    half_lat = MAP_H / (ppd / math.cos(math.radians(clat))) / 2
    b = (clat - half_lat, clon - half_lon, clat + half_lat, clon + half_lon)
    route_pts = _route_label_points(cl, spec.mp_lo, spec.mp_hi)
    avoid = [tuple(study[0]), tuple(study[-1])] + [tuple(p) for p, _ in route_pts]
    labels = road_name_labels(ways, b, 12, "rn a", minsep=80,
                              skip=(abbr(spec.road_label),), avoid=avoid,
                              avoidpx=60)
    name = f"{spec.route} ({abbr(spec.road_label)})" if spec.road_label else spec.route
    for ll, ang in route_pts:
        labels.append({"ll": ll, "html": name, "cls": "rn a", "rot": ang,
                       "ox": 0, "oy": -12, "z": 700})
    lo_off, hi_off = spec.loc_limit_offsets
    payload = {
        "minz": spec.location_zoom - 1, "maxz": spec.location_zoom + 1,
        "fb": [[b[0], b[1]], [b[2], b[3]]],
        "order": [], "style": {}, "roads": {},
        "limits": [{"ll": study[0], "off": list(lo_off), "txt": "Begin Study"},
                   {"ll": study[-1], "off": list(hi_off), "txt": "End Study"}],
        "crash": _crash_payload(spec, spec.loc_label_offset),
        "labels": labels,
    }
    tiles = None
    if tile_fetch is not None:
        cache = os.path.join(cache_dir, "loc_tiles.json") if cache_dir else ""
        if cache and os.path.exists(cache):
            with open(cache, encoding="utf-8") as fh:
                tiles = json.load(fh)
        else:
            tiles, _ = tile_fetch({"line": [[b[0], b[1]], [b[2], b[3]]]},
                                  kinds=("a",),
                                  zooms=(spec.location_zoom - 1,
                                         spec.location_zoom))
            if cache:
                with open(cache, "w", encoding="utf-8") as fh:
                    json.dump(tiles, fh)
    return payload, tiles


def area_payload(spec: MapSpec, cl: Centerline, ways: list, places: list,
                 hydro: list) -> dict:
    mid = cl.mp_to_ll((spec.mp_lo + spec.mp_hi) / 2)
    hl, hn = spec.area_half
    b = (mid[0] - hl, mid[1] - hn, mid[0] + hl, mid[1] + hn)

    def cls(w):
        hw = w["tags"]["highway"]
        if hw == "primary" or spec.route in refs(w):
            return "hwy"
        return {"secondary": "sec", "residential": "res"}.get(hw)
    water_line, water_poly = [], []
    for f in hydro:
        g = f.get("geometry", {})
        if "rings" in g:
            for ring in g["rings"]:
                pts = [[round(p[1], 5), round(p[0], 5)] for p in ring]
                if len(pts) >= 4:
                    water_poly.append(pts)
        else:
            nm = f.get("attributes", {}).get("NAME") or ""
            if not re.search(r"(River|Creek)\b", nm):
                continue
            for path in g.get("paths", []):
                pts = [[round(p[1], 5), round(p[0], 5)] for p in path]
                if len(pts) >= 2:
                    water_line.append(pts)
    labels = []
    for p in places:
        try:
            lat, lon = float(p["CENTLAT"]), float(p["CENTLON"])
        except (KeyError, ValueError):
            continue
        if not (b[0] + 0.006 < lat < b[2] - 0.006 and b[1] + 0.01 < lon < b[3] - 0.01):
            continue
        nm = re.sub(r" (town|city|village)$", "", p.get("NAME", ""))
        labels.append({"ll": [round(lat, 5), round(lon, 5)], "html": nm,
                       "cls": "tn", "ox": 0, "oy": 0, "z": 800})
    for ref, ll in shield_points(ways, b):
        labels.append({"ll": ll, "html": shield_svg(ref), "cls": "",
                       "ox": 0, "oy": 0, "z": 900})
    return {
        "minz": 10, "maxz": 17, "mapbg": "#E9F0E6",
        "fb": [[b[0], b[1]], [b[2], b[3]]],
        "order": ["res", "sec", "hwy"],
        "style": {
            "res": [{"color": "#DFE3E0", "weight": 1.8, "opacity": 1},
                    {"color": "#FFFFFF", "weight": 1.0, "opacity": 1}],
            "sec": [{"color": "#C0C7CD", "weight": 4.0, "opacity": 1},
                    {"color": "#FFFFFF", "weight": 2.5, "opacity": 1}],
            "hwy": [{"color": "#7E93AC", "weight": 4.4, "opacity": 1},
                    {"color": "#9FB1C6", "weight": 2.8, "opacity": 1}]},
        "roads": clip_ways(ways, b, cls),
        "waterLine": water_line, "waterPoly": water_poly,
        "pin": list(mid), "pinSvg": PIN,
        "labels": labels,
    }


def governing_stations(spec: MapSpec, cl: Centerline, stations: list) -> list:
    """The stations whose panels go on the AADT map: the ids in the spec,
    else the route's stations nearest the section (at most two)."""
    rows = []
    for f in stations:
        a = f.get("attributes", {})
        g = f.get("geometry", {})
        if "x" not in g:
            continue
        sid = str(a.get("LocationID") or a.get("LOCATION_ID") or "")
        rows.append((sid, g["y"], g["x"], a))
    if spec.stations:
        want = [str(s) for s in spec.stations]
        picked = [r for r in rows if r[0] in want]
        picked.sort(key=lambda r: want.index(r[0]))
        return picked
    on_route = [r for r in rows if str(r[3].get("RouteID", "")) == spec.route_id]
    mid = (spec.mp_lo + spec.mp_hi) / 2
    on_route.sort(key=lambda r: abs(cl.snap(r[1], r[2])[0] - mid))
    return on_route[:2]


def aadt_payload(spec: MapSpec, cl: Centerline, ways: list,
                 stations: list) -> tuple:
    """(payload, panels_html)."""
    mid = cl.mp_to_ll((spec.mp_lo + spec.mp_hi) / 2)
    hl, hn = spec.aadt_half
    b = (mid[0] - hl, mid[1] - hn, mid[0] + hl, mid[1] + hn)
    study = cl.polyline(spec.mp_lo, spec.mp_hi)

    def cls(w):
        hw = w["tags"]["highway"]
        if spec.route in refs(w) or (spec.road_label and
                                     w["tags"].get("name") == abbr(spec.road_label)):
            return "route"
        return {"primary": "hwy", "secondary": "sec",
                "residential": "res"}.get(hw)
    dots = []
    for f in stations:
        g = f.get("geometry", {})
        if "x" not in g or not (b[0] <= g["y"] <= b[2] and b[1] <= g["x"] <= b[3]):
            continue
        c = CLASS_COLOR.get(str(f["attributes"].get("RTE_CLS", "")))
        if c:
            dots.append({"ll": [round(g["y"], 5), round(g["x"], 5)], "c": c})
    panels, leaders, numbered = "", [], []
    positions = [(12, 112), (836, 12)]
    for n, (sid, lat, lon, a) in enumerate(governing_stations(spec, cl, stations)[:2], 1):
        x, y = positions[n - 1]
        loc = f'{a.get("Approach", "")} {a.get("Crossroad", "")}'.strip().upper()
        rows = ""
        for key, val in [("LocationID", sid), ("COUNTY", spec.county.upper()),
                         ("RTE_CLS", CLASS_NAME.get(str(a.get("RTE_CLS", "")), "")),
                         ("ROUTE", a.get("Located_On") or spec.route),
                         ("LOCATION", loc)]:
            rows += f'<div class="row"><b>{key}</b><span>{val}</span></div>'
        years = sorted(int(k[5:]) for k in a if re.match(r"^AADT_\d{4}$", k))
        for yy in years:
            v = a.get(f"AADT_{yy}")
            hot = " hot" if yy == spec.median_year else ""
            rows += (f'<div class="row{hot}"><b>AADT_{yy}</b>'
                     f'<span>{"" if v is None else v}</span></div>')
        pid = f"panel{n}"
        panels += (f'<div class="panel" id="{pid}" style="left:{x}px;top:{y}px">'
                   f'<div class="bd">{rows}</div></div>')
        leaders.append({"id": pid, "ll": [round(lat, 5), round(lon, 5)]})
        numbered.append({"ll": [round(lat, 5), round(lon, 5)], "n": n})
    labels = road_name_labels(ways, b, 12, "gn", minsep=95, oy=-10,
                              skip=(abbr(spec.road_label),))
    for mp in (spec.mp_lo - 0.3, spec.mp_hi + 0.4):
        ll = cl.mp_to_ll(mp)
        if b[0] < ll[0] < b[2] and b[1] < ll[1] < b[3]:
            labels.append({"ll": list(ll), "html": shield_svg(spec.route),
                           "cls": "", "ox": 0, "oy": 0, "z": 850})
    lo_off, hi_off = spec.aadt_limit_offsets
    payload = {
        "minz": 10, "maxz": 17, "mapbg": "#FBFBFA",
        "fb": [[b[0], b[1]], [b[2], b[3]]],
        "order": ["res", "sec", "hwy", "route"],
        "style": {
            "res": [{"color": "#E4E4E2", "weight": 1.4, "opacity": 1}],
            "sec": [{"color": "#CFCFCD", "weight": 4.0, "opacity": 1},
                    {"color": "#FFFFFF", "weight": 2.4, "opacity": 1}],
            "hwy": [{"color": "#CFCFCD", "weight": 4.6, "opacity": 1},
                    {"color": "#FFFFFF", "weight": 2.8, "opacity": 1}],
            "route": [{"color": "#C9C9C7", "weight": 5.0, "opacity": 1},
                      {"color": "#FFFFFF", "weight": 3.2, "opacity": 1},
                      {"color": "#5BC8F0", "weight": 2.6, "opacity": 0.95}]},
        "roads": clip_ways(ways, b, cls),
        "stations": dots, "numbered": numbered, "panelLeaders": leaders,
        "limits": [{"ll": study[0], "off": list(lo_off), "txt": "Begin Study"},
                   {"ll": study[-1], "off": list(hi_off), "txt": "End Study"}],
        "crash": _crash_payload(spec, spec.aadt_label_offset),
        "labels": labels,
    }
    return payload, panels


def build_maps(spec: MapSpec, out_dir: str, cache_dir: str | None = None,
               tiles: bool = True, centerline: Centerline | None = None,
               log=print) -> dict:
    """Write ``<WO>_LocationMap.html``, ``_AreaMap.html`` and
    ``_AADTMap.html`` under ``out_dir``; returns ``{name: path}``."""
    cache_dir = cache_dir or os.path.join(out_dir, "mapdata")
    os.makedirs(out_dir, exist_ok=True)
    cl = centerline or load_centerline(
        spec.route_id, cache_path=os.path.join(cache_dir, "route_segments.json"))
    mid = cl.mp_to_ll((spec.mp_lo + spec.mp_hi) / 2)
    hl, hn = spec.area_half
    bbox = (mid[0] - hl - 0.01, mid[1] - hn - 0.01,
            mid[0] + hl + 0.01, mid[1] + hn + 0.01)
    log("TIGER roads, places and hydrography...")
    tg = fetch_tiger(bbox, cache_dir)
    ways = ways_from_tiger(tg["roads"])
    log(f"  {len(ways)} road ways")
    log("NCDOT AADT stations...")
    stations = fetch_stations(bbox, cache_dir)
    log(f"  {len(stations)} stations in the area")
    out = {}
    tile_fetch = None
    if tiles:
        from .crash_map import fetch_tiles
        tile_fetch = fetch_tiles
    log("Location Map...")
    payload, tl = location_payload(spec, cl, ways, tile_fetch, cache_dir)
    p = os.path.join(out_dir, f"{spec.wo}_LocationMap.html")
    _write(p, render_page(spec, "Location Map", payload, tl,
                          datasource="Esri, Maxar, Earthstar Geographics"))
    out["location"] = p
    log("Area Map...")
    p = os.path.join(out_dir, f"{spec.wo}_AreaMap.html")
    _write(p, render_page(spec, "Area Map",
                          area_payload(spec, cl, ways, tg["places"], tg["hydro"]),
                          datasource="NCDOT, US Census Bureau TIGER, VHB"))
    out["area"] = p
    log("AADT Map...")
    payload, panels = aadt_payload(spec, cl, ways, stations)
    p = os.path.join(out_dir, f"{spec.wo}_AADTMap.html")
    _write(p, render_page(spec, "AADT Map", payload, panels=panels, legend=True,
                          datasource="NCDOT AADT Mapping Application"))
    out["aadt"] = p
    return out


def _write(path: str, html: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


def chromium_path() -> str | None:
    """A Chromium binary for Playwright: ``SAFETY_EVAL_CHROMIUM``, else the
    first ``chromium-*/chrome-linux/chrome`` under the Playwright browsers
    dir, else None (Playwright's own default)."""
    env = os.environ.get("SAFETY_EVAL_CHROMIUM")
    if env and os.path.exists(env):
        return env
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if base and os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            cand = os.path.join(base, name, "chrome-linux", "chrome")
            if name.startswith("chromium-") and os.path.exists(cand):
                return cand
    return None


def print_pdfs(pairs: list, screenshots: bool = False) -> list:
    """Print ``[(html, pdf), ...]`` with Chromium at 1056 x 816 landscape.

    Needs the ``playwright`` package and a Chromium (``playwright install
    chromium`` once, or point ``SAFETY_EVAL_CHROMIUM`` at one).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("PDF printing needs Playwright: pip install "
                           "'safety-eval[maps]' then 'playwright install "
                           "chromium'") from exc
    done = []
    with sync_playwright() as p:
        kw = {}
        exe = chromium_path()
        if exe:
            kw["executable_path"] = exe
        browser = p.chromium.launch(**kw)
        for html, pdf in pairs:
            page = browser.new_page(viewport={"width": PAGE_W, "height": PAGE_H})
            page.goto("file://" + os.path.abspath(html))
            page.wait_for_function("window._map !== undefined")
            page.wait_for_timeout(2500)
            page.pdf(path=pdf, landscape=True, print_background=True,
                     margin={"top": "0", "bottom": "0", "left": "0",
                             "right": "0"})
            if screenshots:
                page.screenshot(path=os.path.splitext(pdf)[0] + ".png")
            page.close()
            done.append(pdf)
        browser.close()
    return done
