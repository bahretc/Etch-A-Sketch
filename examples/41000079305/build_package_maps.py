"""Package maps for study 41000079305 in the NCDOT house format.

Modeled on the engineer's ArcMap deliverables for Order 6300055941E
PH 81I00059 (Location Map, Vicinity Map, AADT Map): bold title line
above a neatlined frame, blue study marking, sky blue callout boxes
with wedge leaders, cream AADT year boxes with the governing year
boxed in red, yellow halo route labels, alternating scale bar in a
white box, compass rose bottom right.

Location Map  - aerial, study section blue over the yellow route.
Area Map      - vicinity style vector street map, white background.
AADT Map      - white background road diagram with the three mainline
                count stations and the assumption callout.
"""
import json
import math
import re
import sys
from collections import defaultdict

sys.path.insert(0, "/home/user/Etch-A-Sketch")
from importlib import resources  # noqa: E402

from safety_eval.crash_map import fetch_tiles  # noqa: E402

SP = ("/tmp/claude-0/-home-user-Etch-A-Sketch/"
      "4d83860a-51f4-5f7b-a60e-765168dfbb13/scratchpad/map79305")
STUDY_NO = "41000079305"
TITLE_LL = "(35.275639, -82.132762)"

# ---------------------------------------------------------------- data
cl = json.load(open(f"{SP}/centerline_us74.geojson"))
CO = cl["features"][0]["geometry"]["coordinates"]
STUDY = [[round(c[1], 6), round(c[0], 6)] for c in CO if 12.8 <= c[2] <= 13.815]

osm = json.load(open(f"{SP}/osm_roads.json"))
WAYS = [e for e in osm["elements"] if e["type"] == "way"
        and "highway" in e.get("tags", {})]
PLACES = [e for e in osm["elements"] if e["type"] == "node"]

aadt = json.load(open(f"{SP}/aadt_raw.json"))

# name -> SR from station Location strings plus OSM refs; ambiguous -> None
srsets = defaultdict(set)
for f in aadt["features"]:
    loc = f["properties"].get("Location", "") or ""
    for m in re.finditer(r"SR (\d{4}) \(([^)]+)\)", loc):
        srsets[re.sub(r"[^A-Z0-9 ]", "", m.group(2).upper()).strip()].add(
            "SR " + m.group(1))
for w in WAYS:
    ref, nm = w["tags"].get("ref", ""), w["tags"].get("name")
    if nm and re.fullmatch(r"SR \d{4}", ref):
        srsets[re.sub(r"[^A-Z0-9 ]", "", nm.upper()).strip()].add(ref)
SRMAP = {k: next(iter(v)) for k, v in srsets.items() if len(v) == 1}


_ABBR = ((" ROAD", " RD"), (" STREET", " ST"), (" LANE", " LN"),
         (" DRIVE", " DR"), (" PARKWAY", " PKWY"), (" TRAIL", " TRL"),
         (" AVENUE", " AVE"), (" HIGHWAY", " HWY"), (" CIRCLE", " CIR"),
         (" COURT", " CT"), (" PLACE", " PL"))


def abbrev(name):
    up = name.upper()
    for a, b in _ABBR:
        if up.endswith(a):
            up = up[: -len(a)] + b
        up = up.replace(a + " ", b + " ")
    return up


def srfor(name):
    key = abbrev(re.sub(r"[^A-Za-z0-9 ]", "", name)).strip()
    return SRMAP.get(key)


def is74(w):
    ref = w["tags"].get("ref", "")
    return "US 74" in ref and "I 26" not in ref


def isi26(w):
    return "I 26" in w["tags"].get("ref", "")


def clip(b, classify):
    out = defaultdict(list)
    m = 0.004
    for w in WAYS:
        g = w.get("geometry") or []
        if not any(b[0] - m <= p["lat"] <= b[2] + m
                   and b[1] - m <= p["lon"] <= b[3] + m for p in g):
            continue
        cls = classify(w)
        if cls:
            out[cls].append([[round(p["lat"], 5), round(p["lon"], 5)]
                             for p in g])
    return dict(out)


def nearest_vertex(pred, target):
    best, bd = None, 9e9
    for w in WAYS:
        if not pred(w):
            continue
        for p in w.get("geometry") or []:
            d = (p["lat"] - target[0]) ** 2 + (p["lon"] - target[1]) ** 2
            if d < bd:
                bd, best = d, [round(p["lat"], 5), round(p["lon"], 5)]
    return best


def named_labels(b, want, cap, cls_css, minsep=95, skip=()):
    latpx = 746 / (b[2] - b[0])
    lonpx = 996 / (b[3] - b[1])
    by = defaultdict(list)
    for w in WAYS:
        nm = w["tags"].get("name")
        if not nm or w["tags"]["highway"] not in want or nm in skip:
            continue
        g = [p for p in (w.get("geometry") or [])
             if b[0] <= p["lat"] <= b[2] and b[1] <= p["lon"] <= b[3]]
        if len(g) >= 2:
            by[nm].append(g)
    items = sorted(((nm, max(segs, key=len)) for nm, segs in by.items()),
                   key=lambda x: -len(x[1]))
    mlat, mlon = (b[2] - b[0]) * 0.045, (b[3] - b[1]) * 0.05
    placed, out = [], []
    for nm, seg in items:
        if len(out) >= cap:
            break
        mid = seg[len(seg) // 2]
        if not (b[0] + mlat <= mid["lat"] <= b[2] - mlat
                and b[1] + mlon <= mid["lon"] <= b[3] - mlon):
            continue
        if any(abs(mid["lon"] - q[1]) * lonpx < minsep
               and abs(mid["lat"] - q[0]) * latpx < minsep for q in placed):
            continue
        placed.append((mid["lat"], mid["lon"]))
        sr = srfor(nm)
        html = abbrev(nm) + (f"<br>({sr})" if sr else "")
        out.append({"ll": [round(mid["lat"], 5), round(mid["lon"], 5)],
                    "html": html, "cls": cls_css, "ox": 0, "oy": -13})
    return out


def station_rows(props, n=3):
    rows = []
    for y in range(2024, 2001, -1):
        v = str(props.get(f"AADT_{y}") or "").strip()
        if v:
            rows.append([str(y), f"{int(v):,}"])
        if len(rows) == n:
            break
    return rows


MAINS = []
for f in aadt["features"]:
    if f["properties"].get("Route") == 20000074075:
        lon, lat = f["geometry"]["coordinates"]
        MAINS.append({"ll": [round(lat, 5), round(lon, 5)],
                      "loc": f["properties"].get("Location", ""),
                      "rows": station_rows(f["properties"])})
MAINS.sort(key=lambda s: s["ll"][1])
assert len(MAINS) == 3, MAINS

# ---------------------------------------------------------------- svg


def rose_svg():
    cx, cy, rl, rs = 36, 42, 26, 12
    def pt(ang, dist):
        a = math.radians(ang)
        return (cx + dist * math.sin(a), cy - dist * math.cos(a))
    polys = []
    for ang in (45, 135, 225, 315, 0, 90, 180, 270):
        card = ang % 90 == 0
        tip = pt(ang, rl if card else rs)
        sh = 6.4 if card else 4.6
        shl, shr = pt(ang - 22.5, sh), pt(ang + 22.5, sh)
        polys.append(
            f'<polygon points="{tip[0]:.1f},{tip[1]:.1f} {cx},{cy} '
            f'{shl[0]:.1f},{shl[1]:.1f}" fill="#111" stroke="#111" '
            'stroke-width="0.5"/>'
            f'<polygon points="{tip[0]:.1f},{tip[1]:.1f} {cx},{cy} '
            f'{shr[0]:.1f},{shr[1]:.1f}" fill="#fff" stroke="#111" '
            'stroke-width="0.7"/>')
    ring = (f'<circle cx="{cx}" cy="{cy}" r="9.6" fill="none" '
            'stroke="#111" stroke-width="1"/>'
            f'<circle cx="{cx}" cy="{cy}" r="7.6" fill="none" '
            'stroke="#111" stroke-width="0.5"/>')
    lt = 'font-family="Georgia,serif" font-size="10.5" fill="#111"'
    letters = (f'<text x="{cx}" y="11" text-anchor="middle" {lt}>N</text>'
               f'<text x="{cx + rl + 6}" y="{cy + 3.5}" '
               f'text-anchor="middle" {lt}>E</text>'
               f'<text x="{cx}" y="{cy + rl + 11}" text-anchor="middle" '
               f'{lt}>S</text>'
               f'<text x="{cx - rl - 6}" y="{cy + 3.5}" '
               f'text-anchor="middle" {lt}>W</text>')
    return (f'<svg width="72" height="84" viewBox="0 0 72 84">{ring}'
            f'{"".join(polys)}{letters}</svg>')


def us_shield(num):
    return ('<svg width="27" height="25" viewBox="0 0 27 25">'
            '<path d="M13.5 23.6 C8.5 20.6 2.2 18.4 2.2 10 C2.2 7 3.1 4.9 '
            '4.1 3.8 C6.5 4.9 9 5.4 13.5 5.4 C18 5.4 20.5 4.9 22.9 3.8 '
            'C23.9 4.9 24.8 7 24.8 10 C24.8 18.4 18.5 20.6 13.5 23.6 Z" '
            'fill="#fff" stroke="#000" stroke-width="1.5"/>'
            f'<text x="13.5" y="16.4" text-anchor="middle" font-size="10" '
            f'font-weight="bold" font-family="Arial" fill="#000">{num}'
            '</text></svg>')


def nc_shield(num):
    fs = 8 if len(num) > 2 else 9
    return ('<svg width="27" height="27" viewBox="0 0 27 27">'
            '<rect x="5.2" y="5.2" width="16.6" height="16.6" '
            'transform="rotate(45 13.5 13.5)" fill="#000" stroke="#fff" '
            'stroke-width="1"/>'
            f'<text x="13.5" y="{13.5 + fs * 0.36:.1f}" text-anchor="middle" '
            f'font-size="{fs}" font-weight="bold" font-family="Arial" '
            f'fill="#fff">{num}</text></svg>')


def i_shield(num):
    return ('<svg width="27" height="27" viewBox="0 0 27 27">'
            '<path d="M13.5 25.6 C6.5 22.6 2 19.4 2 13.4 L2 8.6 C5.4 9.6 '
            '9.3 10.1 13.5 10.1 C17.7 10.1 21.6 9.6 25 8.6 L25 13.4 '
            'C25 19.4 20.5 22.6 13.5 25.6 Z" fill="#003F87" stroke="#fff" '
            'stroke-width="1.2"/>'
            '<path d="M2 8.6 C2 5.4 3 3.4 4.2 2.2 C7.2 3.6 10.2 4.3 13.5 '
            '4.3 C16.8 4.3 19.8 3.6 22.8 2.2 C24 3.4 25 5.4 25 8.6 C21.6 '
            '9.6 17.7 10.1 13.5 10.1 C9.3 10.1 5.4 9.6 2 8.6 Z" '
            'fill="#CE1126" stroke="#fff" stroke-width="1.2"/>'
            f'<text x="13.5" y="20.4" text-anchor="middle" font-size="9" '
            f'font-weight="bold" font-family="Arial" fill="#fff">{num}'
            '</text></svg>')


# ---------------------------------------------------------------- page
CSS = """html,body{margin:0;width:1056px;height:816px;background:#fff;
font-family:Arial,Helvetica,sans-serif;overflow:hidden}
#title{position:absolute;top:9px;left:30px;font-size:17px;font-weight:bold;
color:#000}
#frame{position:absolute;top:38px;left:30px;right:30px;bottom:24px;
border:1.6px solid #000}
#map{position:absolute;inset:0;background:#fff}
.leaflet-container{background:#fff}
#scale{position:absolute;left:13px;bottom:12px;z-index:1200;background:#fff;
border:1.3px solid #000;padding:4px 12px 7px 12px}
#rose{position:absolute;right:13px;bottom:12px;z-index:1200;background:#fff;
border:1.3px solid #000;padding:2px 3px 0 3px}
.lblc{position:relative}
.lblc>span{position:absolute;white-space:nowrap;text-align:center;
display:inline-block;line-height:1.2}
.rl{color:#ffe500;font-weight:bold;font-size:11px;
text-shadow:-1px -1px 0 #000,1px -1px 0 #000,-1px 1px 0 #000,
1px 1px 0 #000,0 0 3px #000}
.rlbig{font-size:13px}
.yb{background:#FFFFBE;border:1px solid #000;color:#000;font-weight:bold;
font-size:9.5px;padding:1px 4px}
.yh{color:#000;font-weight:bold;font-size:9.5px;
text-shadow:-1.5px -1.5px 0 #FFF36E,1.5px -1.5px 0 #FFF36E,
-1.5px 1.5px 0 #FFF36E,1.5px 1.5px 0 #FFF36E,-1.5px 0 0 #FFF36E,
1.5px 0 0 #FFF36E,0 -1.5px 0 #FFF36E,0 1.5px 0 #FFF36E,0 0 4px #FFF36E}
.co.col{text-align:left}
.town{color:#1F5FBF;font-weight:bold;font-style:italic;font-size:16px;
text-shadow:-1.5px -1.5px 0 #fff,1.5px -1.5px 0 #fff,-1.5px 1.5px 0 #fff,
1.5px 1.5px 0 #fff,0 0 3px #fff}
.town.h{font-size:12px}
.hwyname{color:#9E3123;font-weight:bold;font-size:9.5px;
text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff}
.mn{color:#2E3338;font-size:10px;font-weight:bold;
text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff}
.mns{color:#4A5057;font-size:9px;font-weight:normal;
text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff}
.co{background:#BEE8FF;border:1px solid #000;color:#000;font-weight:bold;
font-size:12px;line-height:1.4;padding:7px 11px}
.ab{background:#FFFFBE;border:1px solid #000;color:#000;font-size:10.5px;
line-height:1.45;padding:3px 4px;text-align:left}
.ab b.hot{display:block;border:2px solid #E8112D;padding:0 3px;
font-weight:bold}
.ab span{display:block;padding:0 5px}
"""

JS = r"""(function(){
const P=window.P;
const map=L.map("map",{zoomControl:false,attributionControl:false,zoomSnap:1,
  minZoom:P.minz,maxZoom:P.maxz});
if(window.TILES){
  const BLANK="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAAB"+
    "AAEAAAICTAEAOw==";
  const Base=L.TileLayer.extend({getTileUrl:function(c){
    return window.TILES[P.kind+"/"+c.z+"/"+c.x+"/"+c.y]||BLANK;}});
  (new Base("",{minZoom:P.minz,maxZoom:P.maxz})).addTo(map);
}
map.fitBounds(P.fb,{animate:false});
function cpt(ll){return map.latLngToContainerPoint(L.latLng(ll[0],ll[1]));}
function cll(p){return map.containerPointToLatLng(L.point(p[0],p[1]));}
function lbl(ll,html,cls,ox,oy,z){
  const la=(ll.lat!==undefined)?ll.lat:ll[0],
    lo=(ll.lng!==undefined)?ll.lng:ll[1];
  const st="transform:translate(calc(-50% + "+(ox||0)+
    "px), calc(-50% + "+(oy||0)+"px))";
  return L.marker([la,lo],{interactive:false,icon:L.divIcon({
    className:"lblc",html:'<span class="'+(cls||"")+'" style="'+st+'">'+
    html+'</span>',iconSize:[0,0]}),zIndexOffset:z||0}).addTo(map);
}
for(const cls of P.order){
  const passes=P.style[cls], group=P.roads[cls];
  if(!passes||!group) continue;
  for(const spec of passes)
    for(const pts of group)
      L.polyline(pts,Object.assign({interactive:false},spec)).addTo(map);
}
if(P.study) L.polyline(P.study,{color:"#0455E8",weight:P.studyW||6,
  opacity:1,interactive:false}).addTo(map);
for(const s of (P.stations||[])){
  const ap=cpt(s.ll), bc=[ap.x+s.off[0],ap.y+s.off[1]];
  L.polyline([s.ll,cll(bc)],{color:"#000",weight:1.3,
    interactive:false}).addTo(map);
  let rows="";
  for(const r of s.rows){
    const t=r[0]+" AADT = "+r[1];
    rows+=(r[0]===s.hot)?'<b class="hot">'+t+'</b>':'<span>'+t+'</span>';
  }
  lbl(cll(bc),rows,"ab",0,0,300);
  lbl(s.ll,'<svg width="13" height="13"><rect x="2.8" y="2.8" '+
    'width="7.4" height="7.4" transform="rotate(45 6.5 6.5)" '+
    'fill="#1F6FDE" stroke="#0A2E66" stroke-width="1.4"/></svg>',
    "",0,0,400);
}
for(const c of (P.callouts||[])){
  const ap=cpt(c.a), bc=[ap.x+c.off[0],ap.y+c.off[1]];
  const hw=c.needle?3:11;
  const m=lbl(cll(bc),c.html,"co"+(c.needle?" col":""),0,0,500);
  const el=m.getElement().querySelector("span");
  const r=el.getBoundingClientRect(),
    mr=document.getElementById("map").getBoundingClientRect();
  const b={x:r.left-mr.left+r.width/2,y:r.top-mr.top+r.height/2,
    w:r.width,h:r.height};
  const dx=ap.x-b.x, dy=ap.y-b.y;
  const tx=dx!==0?(b.w/2)/Math.abs(dx):1e9,
    ty=dy!==0?(b.h/2)/Math.abs(dy):1e9;
  const t=Math.min(tx,ty), ex=b.x+dx*t, ey=b.y+dy*t;
  let b1,b2;
  if(tx<ty){b1=[ex,Math.max(b.y-b.h/2+3,ey-hw)];
    b2=[ex,Math.min(b.y+b.h/2-3,ey+hw)];}
  else{b1=[Math.max(b.x-b.w/2+3,ex-hw),ey];
    b2=[Math.min(b.x+b.w/2-3,ex+hw),ey];}
  L.polygon([cll(b1),cll(b2),cll([ap.x,ap.y])],{color:"#000",weight:1,
    fillColor:"#BEE8FF",fillOpacity:1,interactive:false}).addTo(map);
}
for(const l of (P.labels||[]))
  lbl(l.ll,l.html,l.cls,l.ox,l.oy,l.z||0);
(function(){
  const z=map.getZoom(), c=map.getCenter();
  const ftpp=40075016.686*Math.cos(c.lat*Math.PI/180)/
    Math.pow(2,z+8)*3.28084;
  let best=P.scaleFt||0;
  if(!best){const cands=[1000,2000,2500,4000,5000,10000,20000,40000];
    best=cands[0];
    for(const t of cands)
      if(Math.abs(t/ftpp-330)<Math.abs(best/ftpp-330)) best=t;}
  const w=best/ftpp;
  function fmtn(x){return x.toLocaleString("en-US");}
  function lab(x,v){return '<span style="position:absolute;top:0;left:'+
    x+'px;transform:translateX(-50%);font-size:10px">'+fmtn(v)+
    '</span>';}
  document.getElementById("scale").innerHTML=
    '<div style="position:relative;height:25px;width:'+(w+44)+'px">'+
    '<div style="position:absolute;left:0;top:13px;width:'+w+
    'px;height:7px;border:1px solid #000;background:#fff"></div>'+
    '<div style="position:absolute;left:1px;top:14px;width:'+(w/4)+
    'px;height:5px;background:#000"></div>'+
    '<div style="position:absolute;left:'+(w/2)+'px;top:14px;width:'+
    (w/2-1)+'px;height:5px;background:#000"></div>'+
    lab(0,0)+lab(w/4,best/4)+lab(w/2,best/2)+lab(w,best)+
    '<span style="position:absolute;left:'+(w+8)+
    'px;top:12px;font-size:10px">Feet</span></div>';
})();
window._map=map;
})();"""


def vendor(name):
    return (resources.files("safety_eval") / "vendor" / name).read_text(
        encoding="utf-8")


def build(out, name, payload, tiles=None):
    title = f"Study {STUDY_NO} {name} {TITLE_LL}"
    tile_js = (f"window.TILES={json.dumps(tiles)};" if tiles else "")
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>{vendor('leaflet.min.css')}</style><style>{CSS}</style></head><body>
<div id="title">{title}</div>
<div id="frame"><div id="map"></div>
<div id="scale"></div>
<div id="rose">{rose_svg()}</div></div>
<script>{vendor('leaflet.min.js')}</script>
<script>{tile_js}window.P={json.dumps(payload)};</script>
<script>{JS}</script></body></html>"""
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"  -> {out} ({len(html) // 1024} KB)")


# ============================================================ 1 LOCATION
LB = (35.2665, -82.1525, 35.2845, -82.1125)
loc_roads = clip(LB, lambda w: "us74" if is74(w) else (
    "minor" if w["tags"]["highway"] in
    ("secondary", "tertiary", "unclassified", "residential",
     "motorway_link") else None))
loc_labels = named_labels(LB, ("tertiary", "unclassified", "residential"),
                          5, "rl", minsep=120,
                          skip=("Golden Maple Drive", "Lone Cypress Trail",
                                "Majesty Rock Bend", "Apple Tree Lane"))
for t in (-82.147, -82.118):
    v = nearest_vertex(is74, (35.276, t))
    if v:
        loc_labels.append({"ll": v, "html": "US 74", "cls": "rl rlbig",
                           "ox": 0, "oy": -17})
loc_payload = {
    "minz": 14, "maxz": 16, "kind": "a",
    "fb": [[LB[0], LB[1]], [LB[2], LB[3]]],
    "order": ["minor", "us74"],
    "style": {
        "minor": [{"color": "#3F3F3F", "weight": 3.4, "opacity": 0.85},
                  {"color": "#F2F2F2", "weight": 2.0, "opacity": 0.95}],
        "us74": [{"color": "#4A4A4A", "weight": 7.8, "opacity": 0.95,
                  "dashArray": "7 7"},
                 {"color": "#FFD400", "weight": 5.2, "opacity": 1}]},
    "roads": loc_roads,
    "study": STUDY, "studyW": 7,
    "labels": loc_labels,
    "callouts": [{
        "a": [35.275639, -82.132762], "off": [-250, -138],
        "html": ("Location of Section Study<br>"
                 "US 74 from MP 12.800 to MP 13.815<br>"
                 "<span style='display:block;height:6px'></span>"
                 "2024 AADT = 18,500")}],
    "scaleFt": 4000,
}
print("Location Map tiles...")
import os  # noqa: E402
if os.path.exists(f"{SP}/loc_tiles.json"):
    tiles = json.load(open(f"{SP}/loc_tiles.json"))
    print(f"  {len(tiles)} tiles (cached)")
else:
    tiles, misses = fetch_tiles({"line": [[LB[0], LB[1]], [LB[2], LB[3]]]},
                                kinds=("a",), zooms=(14, 15, 16))
    print(f"  {len(tiles)} tiles ({misses} missed)")
    json.dump(tiles, open(f"{SP}/loc_tiles.json", "w"))
build(f"{SP}/{STUDY_NO}_LocationMap.html", "Location Map",
      loc_payload, tiles)

# ================================================================ 2 AREA
AB = (35.238, -82.225, 35.322, -82.055)


def area_cls(w):
    hw = w["tags"]["highway"]
    if isi26(w):
        return "i26"
    if is74(w):
        return "us74"
    if hw == "motorway_link":
        return "link"
    if hw == "secondary":
        return "sec"
    if hw in ("tertiary", "unclassified"):
        return "minor"
    if hw == "residential":
        return "res"
    return None


area_roads = clip(AB, area_cls)
area_labels = named_labels(
    AB, ("tertiary", "unclassified"), 15, "yh", minsep=105,
    skip=("Golden Maple Drive", "Lone Cypress Trail", "Majesty Rock Bend",
          "Apple Tree Lane", "Wolverine Trail", "Government Complex Drive",
          "Landrum Road", "Landrum Rd"))
for p in PLACES:
    nm = p["tags"].get("name", "")
    if not (AB[0] < p["lat"] < AB[2] and AB[1] < p["lon"] < AB[3]):
        continue
    town = p["tags"].get("place") == "town"
    area_labels.append({"ll": [round(p["lat"], 5), round(p["lon"], 5)],
                        "html": nm, "cls": "town" + ("" if town else " h"),
                        "ox": 0, "oy": 0, "z": 700})
shields = []
for tgt, ref, svg in [((35.263, -82.19), "us74", us_shield("74")),
                      ((35.284, -82.095), "us74", us_shield("74")),
                      ((35.27, -82.181), "NC 108", nc_shield("108")),
                      ((35.305, -82.163), "NC 108", nc_shield("108")),
                      ((35.252, -82.093), "NC 9", nc_shield("9")),
                      ((35.292, -82.121), "NC 9", nc_shield("9")),
                      ((35.245, -82.218), "I 26", i_shield("26"))]:
    pred = (is74 if ref == "us74" else isi26 if ref == "I 26"
            else (lambda w, r=ref: w["tags"].get("ref") == r))
    v = nearest_vertex(pred, tgt)
    if v:
        shields.append({"ll": v, "html": svg, "cls": "", "ox": 0, "oy": 0,
                        "z": 800})
hn = nearest_vertex(is74, (35.2685, -82.158))
if hn:
    shields.append({"ll": hn, "html": "(SGT W DEAN ARLEDGE MEMORIAL HWY)",
                    "cls": "hwyname", "ox": 0, "oy": 15, "z": 600})
area_payload = {
    "minz": 10, "maxz": 17,
    "fb": [[AB[0], AB[1]], [AB[2], AB[3]]],
    "order": ["res", "minor", "link", "sec", "i26", "us74"],
    "style": {
        "res": [{"color": "#DCDCDC", "weight": 1.2, "opacity": 1}],
        "minor": [{"color": "#A0A0A0", "weight": 3.4, "opacity": 1},
                  {"color": "#FFEE8C", "weight": 2.2, "opacity": 1}],
        "link": [{"color": "#BDBDBD", "weight": 1.8, "opacity": 1}],
        "sec": [{"color": "#8A5A17", "weight": 4.4, "opacity": 1},
                {"color": "#E8A33D", "weight": 3.0, "opacity": 1}],
        "i26": [{"color": "#2B2B2B", "weight": 6.0, "opacity": 1},
                {"color": "#7A8FA6", "weight": 4.2, "opacity": 1}],
        "us74": [{"color": "#701A12", "weight": 5.4, "opacity": 1},
                 {"color": "#C0504D", "weight": 3.8, "opacity": 1}]},
    "roads": area_roads,
    "study": STUDY, "studyW": 5,
    "labels": area_labels + shields,
    "scaleFt": 20000,
}
build(f"{SP}/{STUDY_NO}_AreaMap.html", "Area Map", area_payload)

# ================================================================ 3 AADT
DB = (35.244, -82.205, 35.302, -82.088)


def aadt_cls(w):
    hw = w["tags"]["highway"]
    if is74(w):
        return "us74"
    if isi26(w):
        return "sec"
    if hw in ("motorway_link", "secondary_link"):
        return "link"
    if hw == "secondary":
        return "sec"
    if hw in ("tertiary", "unclassified"):
        return "minor"
    if hw == "residential":
        return "res"
    return None


aadt_roads = clip(DB, aadt_cls)
aadt_labels = named_labels(
    DB, ("tertiary", "unclassified"), 7, "mns", minsep=120,
    skip=("Golden Maple Drive", "Lone Cypress Trail", "Majesty Rock Bend",
          "Apple Tree Lane", "Wolverine Trail", "Government Complex Drive",
          "East Mills Street", "West Mills Street", "Pea Ridge Road"))
aadt_labels = [
    l for l in aadt_labels
    if all(abs(l["ll"][0] - s["ll"][0]) > 0.009
           or abs(l["ll"][1] - s["ll"][1]) > 0.014 for s in MAINS)]
for t in (-82.178, -82.097):
    v = nearest_vertex(is74, (35.27, t))
    if v:
        aadt_labels.append({"ll": v, "html": "US 74", "cls": "rl rlbig",
                            "ox": 0, "oy": -16})
for ref, tgt in [("NC 108", (35.266, -82.181)), ("NC 108", (35.293, -82.163)),
                 ("NC 9", (35.255, -82.094)), ("NC 9", (35.289, -82.135))]:
    v = nearest_vertex(lambda w, r=ref: w["tags"].get("ref") == r, tgt)
    if v:
        aadt_labels.append({"ll": v, "html": ref, "cls": "mn",
                            "ox": 14, "oy": -12})
stations = [
    dict(MAINS[0], off=[-6, 62], hot="2024"),
    dict(MAINS[1], off=[30, 66], hot="2024"),
    dict(MAINS[2], off=[-26, 64], hot="2024"),
]
aadt_payload = {
    "minz": 10, "maxz": 17,
    "fb": [[DB[0], DB[1]], [DB[2], DB[3]]],
    "order": ["res", "minor", "link", "sec", "us74"],
    "style": {
        "res": [{"color": "#D8D8D8", "weight": 1.1, "opacity": 1}],
        "minor": [{"color": "#A8AEB5", "weight": 2.0, "opacity": 1}],
        "link": [{"color": "#B7B7B7", "weight": 1.7, "opacity": 1}],
        "sec": [{"color": "#8F969E", "weight": 2.6, "opacity": 1}],
        "us74": [{"color": "#6F6F6F", "weight": 7.0, "opacity": 1,
                  "dashArray": "7 7"},
                 {"color": "#FFD400", "weight": 4.6, "opacity": 1}]},
    "roads": aadt_roads,
    "study": STUDY, "studyW": 6,
    "stations": stations,
    "labels": aadt_labels,
    "callouts": [
        {"a": STUDY[(len(STUDY) * 3) // 4], "off": [120, -150],
         "html": ("Location of Section Study<br>"
                  "US 74 from MP 12.800 to MP 13.815<br>"
                  "<span style='display:block;height:6px'></span>"
                  "2024 AADT = 18,500")},
        {"a": STUDY[len(STUDY) // 10], "off": [-175, -105], "needle": True,
         "html": ("Assumed AADT equal to the<br>"
                  "US 74 station east of NC 108<br>"
                  "2024 AADT = 18,500")}],
    "scaleFt": 10000,
}
build(f"{SP}/{STUDY_NO}_AADTMap.html", "AADT Map", aadt_payload)
print("done")
