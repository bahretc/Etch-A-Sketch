"""Package maps for fatal slip 260307016EA (US 311, Forsyth County).

Same figure family as examples/41000079307/build_package_maps.py:
full bleed map over a white footer strip, NC county locator inset,
plain north arrow, route shields.

Road vectors come from the Census TIGERweb Transportation service
(Overpass was unreachable from this container; the script fetches
the TIGER layers itself when mapdata/tiger_*.json are absent);
hydrography from TIGERweb Hydro; town names from TIGERweb Places; AADT stations and the
US 311 traffic segments (which double as the study centerline) from the
NCDOT AADT Mapping Application services. The centerline is calibrated
by the traffic segment mileposts (MP 9.388683 to 11.062383 and
11.062383 to 12.174483) and checked against the TEAAS features report
junctions (SR 1979 at 11.104, SR 1940 at 11.176, SR 1948 at 11.248).
"""
import base64
import json
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, "/home/user/Etch-A-Sketch")
from importlib import resources  # noqa: E402

from safety_eval.crash_map import fetch_tiles  # noqa: E402

SP = os.path.dirname(os.path.abspath(__file__))
MD = f"{SP}/mapdata"
OUT = f"{SP}/out"
EX = "/home/user/Etch-A-Sketch/examples/41000079307/mapdata"
WO = "260307016EA"
DIVISION = "9"
COORDS = "36.22298, -80.16971"
DESC = ["US 311 (Walnut Cove Road) from Waggoner Neal Road [MP 10.438]",
        "to 0.5 miles north of SR 1979 (Grubb Road) [MP 11.604]",
        "in Forsyth County"]
MP_LO, MP_HI = 10.438, 11.604
CRASH_MP = 11.11
CRASH_TXT = ("Fatal Crash 108571088<br>US 311 just north of<br>"
             "SR 1979 (Grubb Road), MP 11.11")


def _arc_query(url, bbox, fields, geom=True):
    """Page through an ArcGIS feature query for a lat/lon bbox."""
    import urllib.parse
    import urllib.request
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
        with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params),
                                    timeout=180) as fh:
            d = json.load(fh)
        got = d.get("features", [])
        feats += got
        if not d.get("exceededTransferLimit") or not got:
            return feats
        off += len(got)


def fetch_tiger(bbox=(36.140, -80.320, 36.310, -80.020)):
    """Pull TIGERweb roads, places and hydrography for the map extent
    when the cached JSON files are missing (public service, no token)."""
    base = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
    if not os.path.exists(f"{MD}/tiger_roads.json"):
        out = []
        for layer in (2, 6, 8):  # primary, secondary, local roads
            for f in _arc_query(f"{base}Transportation/MapServer/{layer}/query",
                                bbox, "NAME,MTFCC,RTTYP"):
                f["layer"] = layer
                out.append(f)
        json.dump(out, open(f"{MD}/tiger_roads.json", "w"))
    if not os.path.exists(f"{MD}/tiger_places.json"):
        d = _arc_query(f"{base}Places_CouSub_ConCity_SubMCD/MapServer/4/query",
                       bbox, "NAME,CENTLAT,CENTLON,LSADC", geom=False)
        json.dump([f["attributes"] for f in d],
                  open(f"{MD}/tiger_places.json", "w"))
    if not os.path.exists(f"{MD}/tiger_hydro.json"):
        out = []
        for layer in (0, 1):  # linear, areal hydrography
            out += _arc_query(f"{base}Hydro/MapServer/{layer}/query", bbox,
                              "NAME,MTFCC")
        json.dump(out, open(f"{MD}/tiger_hydro.json", "w"))


os.makedirs(MD, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
fetch_tiger()

# ------------------------------------------------------------ centerline
segs = json.load(open(f"{MD}/aadt_segments.json"))["features"]
segs = sorted((f for f in segs if f["properties"]["RouteID"] == "20000311034"),
              key=lambda f: f["properties"]["BeginMP"])


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[0], b[1], b[0]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(h))


CHAIN = []  # (mp, lat, lon)
for f in segs:
    p = f["properties"]
    c = f["geometry"]["coordinates"]
    d = [0.0]
    for i in range(1, len(c)):
        d.append(d[-1] + hav(c[i - 1], c[i]))
    span = p["EndMP"] - p["BeginMP"]
    for i, pt in enumerate(c):
        mp = p["BeginMP"] + span * (d[i] / d[-1])
        if CHAIN and abs(CHAIN[-1][0] - mp) < 1e-9:
            continue
        CHAIN.append((mp, pt[1], pt[0]))


def mp_to_ll(mp):
    for i in range(1, len(CHAIN)):
        if CHAIN[i][0] >= mp:
            m0, a0, o0 = CHAIN[i - 1]
            m1, a1, o1 = CHAIN[i]
            t = (mp - m0) / (m1 - m0) if m1 > m0 else 0
            return [round(a0 + t * (a1 - a0), 6), round(o0 + t * (o1 - o0), 6)]
    return [CHAIN[-1][1], CHAIN[-1][2]]


STUDY = [mp_to_ll(MP_LO)] + [[round(a, 6), round(o, 6)] for m, a, o in CHAIN
                              if MP_LO < m < MP_HI] + [mp_to_ll(MP_HI)]
MID = mp_to_ll((MP_LO + MP_HI) / 2)
ROUTE_LINE = [[round(a, 6), round(o, 6)] for m, a, o in CHAIN]
for name, mp in (("SR 1979", 11.104), ("SR 1940", 11.176), ("SR 1948", 11.248),
                 ("Waggoner Neal", 10.438), ("crash 108571088", 11.11)):
    print(f"  {name} MP {mp} -> {mp_to_ll(mp)}")

# ------------------------------------------------------------ TIGER roads
_tiger = json.load(open(f"{MD}/tiger_roads.json"))


def ref_of(name):
    n = name or ""
    m = re.match(r"^US (?:Hwy )?(\d+)", n)
    if m:
        return f"US {m.group(1)}"
    m = re.match(r"^(?:State Hwy|Nc|NC) (\d+)", n)
    if m:
        return f"NC {m.group(1)}"
    return ""


WAYS = []
for f in _tiger:
    a = f["attributes"]
    mt = a["MTFCC"]
    if mt not in ("S1100", "S1200", "S1400"):
        continue
    hw = {"S1100": "primary", "S1200": "secondary",
          "S1400": "residential"}[mt]
    nm = a.get("NAME") or ""
    ref = ref_of(nm)
    if mt == "S1400" and re.match(r"^(State Rd|Sr)\s*\d", nm):
        nm = ""
    for path in f["geometry"]["paths"]:
        WAYS.append({"tags": {"highway": hw, "name": nm, "ref": ref},
                     "geometry": [{"lat": p[1], "lon": p[0]} for p in path]})
print(f"TIGER ways: {len(WAYS)}")

PLACES = []
try:
    for p in json.load(open(f"{MD}/tiger_places.json")):
        nm = re.sub(r" (town|city|village)$", "", p["NAME"])
        PLACES.append({"lat": float(p["CENTLAT"]), "lon": float(p["CENTLON"]),
                       "tags": {"name": nm, "place": "town"}})
except FileNotFoundError:
    pass

aadt = json.load(open(f"{MD}/aadt_raw_stations_2025.json"))
LOGO_B64 = base64.b64encode(open(f"{EX}/vhb_logo.png", "rb").read()).decode()

_SUFF = (("Road", "Rd"), ("Street", "St"), ("Lane", "Ln"),
         ("Drive", "Dr"), ("Parkway", "Pkwy"), ("Trail", "Trl"),
         ("Avenue", "Ave"), ("Highway", "Hwy"), ("Court", "Ct"),
         ("Circle", "Cir"), ("Place", "Pl"), ("Terrace", "Ter"))


def abbr(name):
    for a, b in _SUFF:
        if name.endswith(" " + a):
            name = name[: -len(a)] + b
            break
    return name


def refs(w):
    return [r.strip() for r in w["tags"].get("ref", "").split(";") if r]


def is311(w):
    return "US 311" in refs(w) or w["tags"].get("name") == "Walnut Cove Rd"


def clip_ways(ways, b, classify):
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


def clip(b, classify):
    return clip_ways(WAYS, b, classify)


def vertex_and_rot(pred, target):
    best, bd, rot = None, 9e9, 0
    for w in WAYS:
        if not pred(w):
            continue
        g = w.get("geometry") or []
        for i, p in enumerate(g):
            d = (p["lat"] - target[0]) ** 2 + (p["lon"] - target[1]) ** 2
            if d < bd:
                j = i + 1 if i + 1 < len(g) else i - 1
                if j < 0:
                    continue
                a, c = (g[i], g[j]) if j > i else (g[j], g[i])
                dlat, dlon = c["lat"] - a["lat"], c["lon"] - a["lon"]
                ang = math.degrees(math.atan2(
                    -dlat, dlon * math.cos(math.radians(p["lat"]))))
                if ang > 90:
                    ang -= 180
                if ang < -90:
                    ang += 180
                bd, best, rot = d, [round(p["lat"], 5), round(p["lon"], 5)], \
                    round(ang, 1)
    return best, rot


def road_name_labels(b, cap, cls_css, minsep=70, oy=-11, skip=(),
                     avoid=(), avoidpx=40):
    latpx = 706 / (b[2] - b[0])
    lonpx = 1056 / (b[3] - b[1])
    by = defaultdict(list)
    for w in WAYS:
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
            continue
        if any(abs(mid["lon"] - q[1]) * lonpx < minsep
               and abs(mid["lat"] - q[0]) * latpx < minsep for q in placed):
            continue
        if any(abs(mid["lon"] - q[1]) * lonpx < avoidpx
               and abs(mid["lat"] - q[0]) * latpx < avoidpx for q in avoid):
            continue
        placed.append((mid["lat"], mid["lon"]))
        j = i + 1 if i + 1 < len(seg) else i - 1
        a, c = (seg[i], seg[j]) if j > i else (seg[j], seg[i])
        ang = math.degrees(math.atan2(
            -(c["lat"] - a["lat"]),
            (c["lon"] - a["lon"]) * math.cos(math.radians(mid["lat"]))))
        if ang > 90:
            ang -= 180
        if ang < -90:
            ang += 180
        out.append({"ll": [round(mid["lat"], 5), round(mid["lon"], 5)],
                    "html": abbr(nm), "cls": cls_css,
                    "rot": round(ang, 1), "ox": 0, "oy": oy})
    return out


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


PIN = ('<svg width="26" height="36" viewBox="0 0 26 36">'
       '<path d="M13 1 C6.4 1 1.5 6 1.5 12.2 C1.5 20.6 13 34 13 34 '
       'C13 34 24.5 20.6 24.5 12.2 C24.5 6 19.6 1 13 1 Z" fill="#D93025" '
       'stroke="#A11B12" stroke-width="1"/>'
       '<circle cx="13" cy="12.2" r="4.4" fill="#fff"/></svg>')


def locator_svg():
    d = json.load(open(f"{EX}/counties.json"))
    lon0, lon1, lat0, lat1 = -84.45, -75.30, 33.70, 36.75
    W = 208.0
    k = W / (lon1 - lon0)
    ky = k / math.cos(math.radians(35.3))
    H = (lat1 - lat0) * ky

    def xy(lon, lat):
        return ((lon - lon0) * k, (lat1 - lat) * ky)
    paths = []
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
        fill = ("#CC1111" if "forsyth" in
                (f["properties"].get("NAME", "") or "").lower() else "#fff")
        paths.append(f'<path d="{" ".join(dd)}" fill="{fill}" '
                     'stroke="#8A8A8A" stroke-width="0.5"/>')
    return (f'<svg width="{W:.0f}" height="{H:.0f}" '
            f'viewBox="0 0 {W:.0f} {H:.0f}">{"".join(paths)}</svg>')


CSS = """html,body{margin:0;width:1056px;height:816px;background:#fff;
font-family:'Segoe UI',Arial,Helvetica,sans-serif;overflow:hidden;
color:#000}
#frame{position:absolute;left:16px;top:16px;width:1022px;height:782px;
border:1.5px solid #000;overflow:hidden;background:#fff}
#map{position:absolute;top:0;left:0;right:0;height:680px;
background:#fff}
.leaflet-container{background:#fff}
#footer{position:absolute;left:0;right:0;top:680px;bottom:0;
border-top:1.5px solid #000;background:#fff}
#fl{position:absolute;left:16px;top:9px;font-size:12.5px;
line-height:1.62}
#fc{position:absolute;left:22%;right:22%;top:8px;text-align:center;
font-size:11.5px;line-height:1.5}
.fh{font-weight:bold;font-size:12.5px}
#fr{position:absolute;right:26px;top:8px;font-size:12px;
line-height:1.6;text-align:center}
#vhb{position:absolute;right:16px;bottom:12px;height:40px;width:auto}
#ds{position:absolute;left:12px;bottom:3px;font-size:8.5px;
font-style:italic;color:#555}
#locator{position:absolute;top:10px;left:10px;z-index:1300;
background:#fff;border:1px solid #999;padding:3px;line-height:0}
#north{position:absolute;left:14px;bottom:122px;z-index:1300}
.panel{position:absolute;z-index:1300;background:#fff;
border:1px solid #777;width:172px;font-size:8.4px;line-height:1.33}
.panel .bd{padding:3px 6px 4px}
.panel .row{display:flex}
.panel .row b{color:#9A9A9A;font-weight:normal;width:66px;
flex-shrink:0}
.panel .row span{word-break:break-word}
.panel .row.hot{outline:2px solid #E8112D;outline-offset:-1px}
#alegend{position:absolute;right:12px;bottom:122px;z-index:1300;
background:#fff;border:1px solid #999;padding:6px 12px 7px;
font-size:10.5px}
#alegend .r{display:flex;align-items:center;gap:8px;margin-top:3px}
#alegend .r:first-child{margin-top:0}
#leader{position:absolute;inset:0;z-index:1250;pointer-events:none}
.lblc{position:relative}
.lblc>span{position:absolute;white-space:nowrap;text-align:center;
display:inline-block;line-height:1.15}
.rn{color:#2E3033;font-weight:600;font-size:9.5px;
text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,
1px 1px 0 #fff,0 0 2.5px #fff}
.rn.a{color:#fff;font-size:10px;
text-shadow:-1px -1px 0 #222,1px -1px 0 #222,-1px 1px 0 #222,
1px 1px 0 #222,0 0 3px #000}
.gn{color:#9AA0A6;font-weight:600;font-size:9px;
text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,
1px 1px 0 #fff}
.tn{color:#3C4043;font-weight:bold;font-size:12.5px;
text-shadow:-1.5px -1.5px 0 #fff,1.5px -1.5px 0 #fff,
-1.5px 1.5px 0 #fff,1.5px 1.5px 0 #fff,0 0 3px #fff}
.tn.h{font-size:10.5px}
.bx{background:#fff;border:1.2px solid #000;color:#000;
font-weight:bold;font-size:11px;padding:3px 10px}
.badge{background:#fff;border:1.4px solid #000;border-radius:50%;
width:15px;height:15px;font-size:9.5px;font-weight:bold;
line-height:15px;text-align:center}
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
for(const ring of (P.muniFill||[]))
  L.polygon(ring,{color:"#E4E4E4",weight:0,fillColor:"#E4E4E4",
    fillOpacity:1,interactive:false}).addTo(map);
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
if(P.redEllipse){
  const p0=cpt(P.study[0]), p1=cpt(P.study[P.study.length-1]);
  const ecx=(p0.x+p1.x)/2, ecy=(p0.y+p1.y)/2;
  const ea=Math.hypot(p1.x-p0.x,p1.y-p0.y)/2+P.redEllipse.pad,
    eb=P.redEllipse.b;
  const eang=Math.atan2(p1.y-p0.y,p1.x-p0.x)*180/Math.PI;
  lbl(cll([ecx,ecy]),
    '<svg width="'+(2*ea+12)+'" height="'+(2*eb+12)+'">'+
    '<ellipse cx="'+(ea+6)+'" cy="'+(eb+6)+'" rx="'+ea+'" ry="'+eb+
    '" fill="none" stroke="#E8100C" stroke-width="4"/></svg>',
    "",0,0,eang,600);
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

NORTH = ('<svg width="26" height="46" viewBox="0 0 26 46">'
         '<polygon points="13,2 21,34 13,27 5,34" fill="#fff" '
         'stroke="#111" stroke-width="1.6"/>'
         '<polygon points="13,2 13,27 5,34" fill="#111"/>'
         '<text x="13" y="44" text-anchor="middle" font-size="10" '
         'font-weight="bold" font-family="Arial" fill="#111">N</text>'
         '</svg>')


def vendor(name):
    return (resources.files("safety_eval") / "vendor" / name).read_text(
        encoding="utf-8")


def build(out, title, payload, tiles=None, panels="", legend=False,
          datasource=""):
    tile_js = (f"window.TILES={json.dumps(tiles)};" if tiles else "")
    alegend = ""
    if legend:
        rows = [("#3B6FB5", "Interstates"), ("#E8112D", "US Routes"),
                ("#B14FC5", "NC Routes"), ("#38A800", "Secondary Routes"),
                ("#000000", "Non-System Routes")]
        alegend = ('<div id="alegend">' + "".join(
            f'<div class="r"><svg width="11" height="11">'
            f'<circle cx="5.5" cy="5.5" r="4.6" fill="{c}"/></svg>'
            f'<span>{t}</span></div>' for c, t in rows) + "</div>")
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title} - {WO}</title>
<style>{vendor('leaflet.min.css')}</style><style>{CSS}</style></head><body>
<div id="frame">
<div id="map"></div>
<svg id="leader"></svg>
<div id="locator">{locator_svg()}</div>
{panels}{alegend}
<div id="north">{NORTH}</div>
<div id="footer">
<div id="fl"><b>WO Number</b> {WO}<br><b>NCDOT Division</b> {DIVISION}</div>
<div id="fc"><span class="fh">Study Area</span><br>{DESC[0]}<br>{DESC[1]}<br>
{DESC[2]}</div>
<div id="fr"><span class="fh">Coordinates</span><br>{COORDS}</div>
<img id="vhb" src="data:image/png;base64,{LOGO_B64}" alt="vhb">
<div id="ds">Data Source: {datasource}</div>
</div>
</div>
<script>{vendor('leaflet.min.js')}</script>
<script>{tile_js}window.P={json.dumps(payload)};</script>
<script>{JS}</script></body></html>"""
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"  -> {out} ({len(html) // 1024} KB)")


def junction_labels(items, cls):
    out = []
    for mp, txt, ox, oy in items:
        out.append({"ll": mp_to_ll(mp), "html": txt, "cls": cls,
                    "rot": 0, "ox": ox, "oy": oy, "z": 700})
    return out


# ============================================================ 1 LOCATION
# 1022 x 680 px map inside the border at zoom 15 (about 0.0438 deg lon by 0.0235 deg lat)
clat = (STUDY[0][0] + STUDY[-1][0]) / 2
clon = (STUDY[0][1] + STUDY[-1][1]) / 2 - 0.004
LB = (clat - 0.0117, clon - 0.0219, clat + 0.0117, clon + 0.0219)
loc_labels = road_name_labels(LB, 12, "rn a", minsep=80,
                              skip=("Walnut Cove Rd",),
                              avoid=[tuple(STUDY[0]), tuple(STUDY[-1]),
                                     tuple(mp_to_ll(10.75)),
                                     tuple(mp_to_ll(11.38))],
                              avoidpx=60)
# US 311 name labels along the centerline (rotated to the road)
for mp in (10.75, 11.38):
    ll = mp_to_ll(mp)
    a, b = mp_to_ll(mp - 0.02), mp_to_ll(mp + 0.02)
    ang = math.degrees(math.atan2(-(b[0] - a[0]),
                                  (b[1] - a[1]) * math.cos(math.radians(ll[0]))))
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    loc_labels.append({"ll": ll, "html": "US 311 (Walnut Cove Rd)",
                       "cls": "rn a", "rot": round(ang, 1), "ox": 0,
                       "oy": -12, "z": 700})
loc_payload = {
    "minz": 14, "maxz": 16,
    "fb": [[LB[0], LB[1]], [LB[2], LB[3]]],
    "order": [], "style": {}, "roads": {},
    "limits": [
        {"ll": STUDY[0], "off": [-110, 46], "txt": "Begin Study"},
        {"ll": STUDY[-1], "off": [110, -46], "txt": "End Study"}],
    "crash": {"ll": mp_to_ll(CRASH_MP), "off": [170, 30], "txt": CRASH_TXT},
    "labels": loc_labels,
}
print("Location Map tiles...")
if os.path.exists(f"{SP}/loc_tiles.json"):
    tiles = json.load(open(f"{SP}/loc_tiles.json"))
    print(f"  {len(tiles)} tiles (cached)")
else:
    tiles, misses = fetch_tiles({"line": [[LB[0], LB[1]], [LB[2], LB[3]]]},
                                kinds=("a",), zooms=(14, 15))
    print(f"  {len(tiles)} tiles ({misses} missed)")
    json.dump(tiles, open(f"{SP}/loc_tiles.json", "w"))
build(f"{OUT}/{WO}_LocationMap.html", "Location Map", loc_payload, tiles,
      datasource="Esri, Maxar, Earthstar Geographics")

# ================================================================ 2 AREA
AB = (MID[0] - 0.085, MID[1] - 0.157, MID[0] + 0.085, MID[1] + 0.157)


def area_cls(w):
    hw = w["tags"]["highway"]
    if hw == "primary" or "US 311" in refs(w):
        return "hwy"
    if hw == "secondary":
        return "sec"
    if hw == "residential":
        return "res"
    return None


water_line, water_poly = [], []
try:
    for f in json.load(open(f"{MD}/tiger_hydro.json")):
        g = f["geometry"]
        if "rings" in g:
            for ring in g["rings"]:
                pts = [[round(p[1], 5), round(p[0], 5)] for p in ring]
                if len(pts) >= 4:
                    water_poly.append(pts)
        else:
            nm = (f["attributes"].get("NAME") or "")
            if not re.search(r"(River|Creek)\b", nm):
                continue
            for path in g.get("paths", []):
                pts = [[round(p[1], 5), round(p[0], 5)] for p in path]
                if len(pts) >= 2:
                    water_line.append(pts)
    print(f"water: {len(water_line)} lines, {len(water_poly)} polys")
except FileNotFoundError:
    pass

area_labels = []
for p in PLACES:
    nm = p["tags"].get("name", "")
    if not (AB[0] + 0.006 < p["lat"] < AB[2] - 0.006
            and AB[1] + 0.01 < p["lon"] < AB[3] - 0.01):
        continue
    area_labels.append({"ll": [round(p["lat"], 5), round(p["lon"], 5)],
                        "html": nm, "cls": "tn", "ox": 0, "oy": 0, "z": 800})
for tgt, ref, svg in [((MID[0] - 0.045, MID[1] + 0.006), "US 311", us_shield("311")),
                      ((MID[0] + 0.05, MID[1] + 0.04), "US 311", us_shield("311")),
                      ((MID[0] - 0.06, MID[1] - 0.09), "US 52", us_shield("52")),
                      ((MID[0] + 0.03, MID[1] - 0.12), "US 52", us_shield("52")),
                      ((MID[0] - 0.05, MID[1] + 0.09), "US 158", us_shield("158")),
                      ((MID[0] + 0.05, MID[1] - 0.05), "NC 65", nc_shield("65")),
                      ((MID[0] + 0.045, MID[1] + 0.10), "NC 65", nc_shield("65")),
                      ((MID[0] - 0.06, MID[1] - 0.03), "NC 66", nc_shield("66")),
                      ((MID[0] - 0.02, MID[1] + 0.12), "NC 66", nc_shield("66")),
                      ((MID[0] + 0.06, MID[1] + 0.0), "NC 8", nc_shield("8"))]:
    v, _ = vertex_and_rot(lambda w, r=ref: r in refs(w), tgt)
    if v and AB[0] < v[0] < AB[2] and AB[1] < v[1] < AB[3]:
        d2 = (v[0] - tgt[0]) ** 2 + (v[1] - tgt[1]) ** 2
        if d2 < 0.03 ** 2:
            area_labels.append({"ll": v, "html": svg, "cls": "", "ox": 0,
                                "oy": 0, "z": 900})
area_payload = {
    "minz": 10, "maxz": 17, "mapbg": "#E9F0E6",
    "fb": [[AB[0], AB[1]], [AB[2], AB[3]]],
    "order": ["res", "sec", "hwy"],
    "style": {
        "res": [{"color": "#DFE3E0", "weight": 1.8, "opacity": 1},
                {"color": "#FFFFFF", "weight": 1.0, "opacity": 1}],
        "sec": [{"color": "#C0C7CD", "weight": 4.0, "opacity": 1},
                {"color": "#FFFFFF", "weight": 2.5, "opacity": 1}],
        "hwy": [{"color": "#7E93AC", "weight": 4.4, "opacity": 1},
                {"color": "#9FB1C6", "weight": 2.8, "opacity": 1}]},
    "roads": clip(AB, area_cls),
    "waterLine": water_line, "waterPoly": water_poly,
    "pin": MID, "pinSvg": PIN,
    "labels": area_labels,
}
build(f"{OUT}/{WO}_AreaMap.html", "Area Map", area_payload,
      datasource="NCDOT, US Census Bureau TIGER, VHB")

# ================================================================ 3 AADT
DB = (MID[0] - 0.0235, MID[1] - 0.0435, MID[0] + 0.0235, MID[1] + 0.0435)


def adt_cls(w):
    hw = w["tags"]["highway"]
    if is311(w):
        return "us311"
    if hw == "primary":
        return "hwy"
    if hw == "secondary":
        return "sec"
    if hw == "residential":
        return "res"
    return None


CLASS_COLOR = {"1": "#3B6FB5", "2": "#E8112D", "3": "#B14FC5",
               "4": "#38A800", "8": "#000000"}
stations = []
for f in aadt["features"]:
    lon, lat = f["geometry"]["coordinates"]
    if not (DB[0] <= lat <= DB[2] and DB[1] <= lon <= DB[3]):
        continue
    c = CLASS_COLOR.get(str(f["properties"].get("RTE_CLS", "")))
    if c:
        stations.append({"ll": [round(lat, 5), round(lon, 5)], "c": c})
print(f"AADT stations in frame: {len(stations)}")

GOV = ["0340000299", "0340000301"]
MAINS = []
for f in aadt["features"]:
    p = f["properties"]
    if p.get("LocationID") in GOV:
        lon, lat = f["geometry"]["coordinates"]
        MAINS.append({"id": p["LocationID"],
                      "ll": [round(lat, 5), round(lon, 5)],
                      "loc": f'{p.get("Approach", "")} {p.get("Crossroad", "")}'.upper(),
                      "props": p})
MAINS.sort(key=lambda s: GOV.index(s["id"]))

panels_html = ""
panel_leaders = []
numbered = []
PANEL_POS = {"0340000299": (12, 112), "0340000301": (836, 12)}
for n, st in enumerate(MAINS, start=1):
    x, y = PANEL_POS[st["id"]]
    rows = ""
    for key, val in [("LocationID", st["id"]), ("COUNTY", "FORSYTH"),
                     ("RTE_CLS", "US Routes"), ("ROUTE", "US 311"),
                     ("LOCATION", st["loc"])]:
        rows += f'<div class="row"><b>{key}</b><span>{val}</span></div>'
    for yy in range(2002, 2026):
        v = st["props"].get(f"AADT_{yy}")
        val = "" if v is None else str(v)
        hot = ' hot' if yy == 2023 else ''
        rows += (f'<div class="row{hot}"><b>AADT_{yy}</b>'
                 f'<span>{val}</span></div>')
    pid = f"panel{n}"
    panels_html += (f'<div class="panel" id="{pid}" '
                    f'style="left:{x}px;top:{y}px">'
                    f'<div class="bd">{rows}</div></div>')
    panel_leaders.append({"id": pid, "ll": st["ll"]})
    numbered.append({"ll": st["ll"], "n": n})

adt_labels = road_name_labels(DB, 12, "gn", minsep=95, oy=-10,
                              skip=("Walnut Cove Rd",))
for mp in (10.15, 12.0):
    ll = mp_to_ll(mp)
    if DB[0] < ll[0] < DB[2] and DB[1] < ll[1] < DB[3]:
        adt_labels.append({"ll": ll, "html": us_shield("311"), "cls": "",
                           "ox": 0, "oy": 0, "z": 850})
adt_payload = {
    "minz": 10, "maxz": 17, "mapbg": "#FBFBFA",
    "fb": [[DB[0], DB[1]], [DB[2], DB[3]]],
    "order": ["res", "sec", "hwy", "us311"],
    "style": {
        "res": [{"color": "#E4E4E2", "weight": 1.4, "opacity": 1}],
        "sec": [{"color": "#CFCFCD", "weight": 4.0, "opacity": 1},
                {"color": "#FFFFFF", "weight": 2.4, "opacity": 1}],
        "hwy": [{"color": "#CFCFCD", "weight": 4.6, "opacity": 1},
                {"color": "#FFFFFF", "weight": 2.8, "opacity": 1}],
        "us311": [{"color": "#C9C9C7", "weight": 5.0, "opacity": 1},
                  {"color": "#FFFFFF", "weight": 3.2, "opacity": 1},
                  {"color": "#5BC8F0", "weight": 2.6, "opacity": 0.95}]},
    "roads": clip(DB, adt_cls),
    "stations": stations,
    "numbered": numbered,
    "panelLeaders": panel_leaders,
    "study": STUDY,
    "limits": [
        {"ll": STUDY[0], "off": [-120, 40], "txt": "Begin Study"},
        {"ll": STUDY[-1], "off": [120, -40], "txt": "End Study"}],
    "crash": {"ll": mp_to_ll(CRASH_MP), "off": [215, 95], "txt": CRASH_TXT},
    "labels": adt_labels,
}
build(f"{OUT}/{WO}_AADTMap.html", "AADT Map", adt_payload,
      panels=panels_html, legend=True,
      datasource="NCDOT AADT Mapping Application")
json.dump({"study": STUDY, "mid": MID}, open(f"{MD}/centerline.json", "w"))
print("done")
