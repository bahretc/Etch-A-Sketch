"""Package maps for study 41000079305 in the current VHB figure format.

Matched to the engineer's newest deliverable set (slip M260408001,
with the 41000078675 section set informing section-specific idioms):
full bleed map over a white footer strip (WO Number and NCDOT
Division left, Study Area centered, Coordinates right, the vhb
logo bottom right, italic data source line), NC county locator inset
with a red pin at the study, plain north arrow, route shields.

Location Map - aerial; yellow circle X markers at Begin Study and
               End Study with white label boxes and leaders (the
               house section idiom); road names dark with white halo.
Area Map     - soft web style vector: pale green land, white roads
               with grey casings, blue grey highways, streams and
               ponds in blue, town names, shields, red map pin.
AADT Map     - AADT Mapping Application look on a white canvas:
               station dots colored by route class with the standard
               legend, numbered badges, one attribute panel per
               mainline station with leader lines and the governing
               2024 row boxed in red, the study route traced cyan,
               and a red ellipse around the study section.
"""
import base64
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, "/home/user/Etch-A-Sketch")
from importlib import resources  # noqa: E402

from safety_eval.crash_map import fetch_tiles  # noqa: E402

SP = ("/tmp/claude-0/-home-user-Etch-A-Sketch/"
      "4d83860a-51f4-5f7b-a60e-765168dfbb13/scratchpad/map79305")
REPO = "/home/user/Etch-A-Sketch/examples/41000079305"
WO = "41000079305"
PH = "74S00010"
DIVISION = "14"
COORDS = "35.275639, -82.132762"
DESC = ["US 74 from 0.075 miles east of SR 1526 (Bill Collins Rd) "
        "[MP 12.800]",
        "to 0.100 miles east of Mile Marker 166 [MP 13.815]",
        "in Polk County"]


def data_path(name):
    for base in (SP, f"{REPO}/mapdata"):
        cand = f"{base}/{name}"
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(name)


cl = json.load(open(f"{REPO}/centerline_us74.geojson"))
CO = cl["features"][0]["geometry"]["coordinates"]
STUDY = [[round(c[1], 6), round(c[0], 6)] for c in CO if 12.8 <= c[2] <= 13.815]
MID = STUDY[len(STUDY) // 2]

osm = json.load(open(data_path("osm2.json")))
WAYS = [e for e in osm["elements"] if e["type"] == "way"
        and "highway" in e.get("tags", {})]
PLACES = [e for e in osm["elements"] if e["type"] == "node"]

aadt = json.load(open(data_path("aadt_raw.json")))
LOGO_B64 = base64.b64encode(open(data_path("vhb_logo.png"), "rb")
                            .read()).decode()

_SUFF = (("Road", "Rd"), ("Street", "St"), ("Lane", "Ln"),
         ("Drive", "Dr"), ("Parkway", "Pkwy"), ("Trail", "Trl"),
         ("Avenue", "Ave"), ("Highway", "Hwy"), ("Court", "Ct"),
         ("Circle", "Cir"), ("Place", "Pl"), ("Terrace", "Ter"))


def abbr(name):
    for a, b in _SUFF:
        if name.endswith(" " + a):
            return name[: -len(a)] + b
    return name


def is74(w):
    ref = w["tags"].get("ref", "")
    return "US 74" in ref and "I 26" not in ref


def isi26(w):
    return "I 26" in w["tags"].get("ref", "")


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


def road_name_labels(b, cap, cls_css, minsep=70, oy=-11, skip=()):
    latpx = 706 / (b[2] - b[0])
    lonpx = 1056 / (b[3] - b[1])
    by = defaultdict(list)
    for w in WAYS:
        nm = w["tags"].get("name")
        if not nm or nm in skip or is74(w) or isi26(w):
            continue
        if nm.startswith("State Road "):
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


def assemble_rings(ways_pts):
    segs = [[tuple(p) for p in w] for w in ways_pts]
    rings = []
    while segs:
        cur = segs.pop()
        changed = True
        while changed and cur[0] != cur[-1]:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == cur[-1]:
                    cur += s[1:]
                elif s[-1] == cur[-1]:
                    cur += list(reversed(s[:-1]))
                elif s[-1] == cur[0]:
                    cur = s[:-1] + cur
                elif s[0] == cur[0]:
                    cur = list(reversed(s[1:])) + cur
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if len(cur) >= 4 and cur[0] == cur[-1]:
            rings.append([list(p) for p in cur])
    return rings


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
            '21.7 13 24.6 Z" fill="#3B6FB5" stroke="#fff" '
            'stroke-width="1.1"/>'
            '<path d="M2 8.3 C2 5.2 3 3.3 4.1 2.1 C7 3.5 9.9 4.1 13 4.1 '
            'C16.1 4.1 19 3.5 21.9 2.1 C23 3.3 24 5.2 24 8.3 C20.7 9.3 17 '
            '9.7 13 9.7 C9 9.7 5.3 9.3 2 8.3 Z" fill="#C8452E" '
            'stroke="#fff" stroke-width="1.1"/>'
            f'<text x="13" y="19.6" text-anchor="middle" font-size="8.5" '
            f'font-weight="bold" font-family="Arial" fill="#fff">{num}'
            '</text></svg>')


PIN = ('<svg width="26" height="36" viewBox="0 0 26 36">'
       '<path d="M13 1 C6.4 1 1.5 6 1.5 12.2 C1.5 20.6 13 34 13 34 '
       'C13 34 24.5 20.6 24.5 12.2 C24.5 6 19.6 1 13 1 Z" fill="#D93025" '
       'stroke="#A11B12" stroke-width="1"/>'
       '<circle cx="13" cy="12.2" r="4.4" fill="#fff"/></svg>')


def locator_svg():
    d = json.load(open(data_path("counties.json")))
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
        paths.append(f'<path d="{" ".join(dd)}" fill="#fff" '
                     'stroke="#8A8A8A" stroke-width="0.5"/>')
    px, py = xy(-82.132762, 35.275639)
    pin = (f'<path d="M{px:.1f} {py - 9:.1f} c-3 0 -5 2.1 -5 4.7 '
           f'c0 3.3 5 8.8 5 8.8 c0 0 5 -5.5 5 -8.8 c0 -2.6 -2 -4.7 '
           f'-5 -4.7 z" fill="#D93025" transform="translate(0,-4)"/>')
    return (f'<svg width="{W:.0f}" height="{H:.0f}" '
            f'viewBox="0 0 {W:.0f} {H:.0f}">{"".join(paths)}{pin}</svg>')


CSS = """html,body{margin:0;width:1056px;height:816px;background:#fff;
font-family:'Segoe UI',Arial,Helvetica,sans-serif;overflow:hidden;
color:#000}
#map{position:absolute;top:0;left:0;right:0;height:706px;
background:#fff}
.leaflet-container{background:#fff}
#footer{position:absolute;left:0;right:0;top:706px;bottom:0;
background:#fff}
#fl{position:absolute;left:16px;top:9px;font-size:12.5px;
line-height:1.62}
#fc{position:absolute;left:22%;right:22%;top:8px;text-align:center;
font-size:11.5px;line-height:1.5}
.fh{font-weight:bold;font-size:12.5px}
#fr{position:absolute;right:26px;top:8px;font-size:12px;
line-height:1.6;text-align:center}
#vhb{position:absolute;right:10px;bottom:2px;height:50px}
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
<div id="map"></div>
<svg id="leader"></svg>
<div id="locator">{locator_svg()}</div>
{panels}{alegend}
<div id="north">{NORTH}</div>
<div id="footer">
<div id="fl"><b>WO Number</b> {WO}<br><b>PH Number</b> {PH}<br><b>NCDOT Division</b> {DIVISION}</div>
<div id="fc"><span class="fh">Study Area</span><br>{DESC[0]}<br>{DESC[1]}<br>
{DESC[2]}</div>
<div id="fr"><span class="fh">Coordinates</span><br>{COORDS}</div>
<img id="vhb" src="data:image/png;base64,{LOGO_B64}" alt="vhb">
<div id="ds">Data Source: {datasource}</div>
</div>
<script>{vendor('leaflet.min.js')}</script>
<script>{tile_js}window.P={json.dumps(payload)};</script>
<script>{JS}</script></body></html>"""
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"  -> {out} ({len(html) // 1024} KB)")


# ============================================================ 1 LOCATION
LB = (35.2660, -82.1530, 35.2850, -82.1120)
loc_labels = road_name_labels(LB, 16, "rn", minsep=78,
                              skip=("Golden Maple Drive",))
for tgt in ((35.2700, -82.1480), (35.2828, -82.1165)):
    v, _ = vertex_and_rot(is74, tgt)
    if v:
        loc_labels.append({"ll": v, "html": us_shield("74"), "cls": "",
                           "ox": 0, "oy": 0, "z": 850})
loc_payload = {
    "minz": 14, "maxz": 16,
    "fb": [[LB[0], LB[1]], [LB[2], LB[3]]],
    "order": [], "style": {}, "roads": {},
    "limits": [
        {"ll": STUDY[0], "off": [116, 46], "txt": "Begin Study"},
        {"ll": STUDY[-1], "off": [-108, -42], "txt": "End Study"}],
    "labels": loc_labels,
}
print("Location Map tiles...")
if os.path.exists(f"{SP}/loc_tiles.json"):
    tiles = json.load(open(f"{SP}/loc_tiles.json"))
    print(f"  {len(tiles)} tiles (cached)")
else:
    tiles, misses = fetch_tiles({"line": [[LB[0], LB[1]], [LB[2], LB[3]]]},
                                kinds=("a",), zooms=(14, 15, 16))
    print(f"  {len(tiles)} tiles ({misses} missed)")
    json.dump(tiles, open(f"{SP}/loc_tiles.json", "w"))
build(f"{SP}/{WO}_LocationMap.html", "Location Map", loc_payload, tiles,
      datasource="Esri, Maxar, Earthstar Geographics")

# ================================================================ 2 AREA
AB = (35.238, -82.225, 35.322, -82.055)


def area_cls(w):
    hw = w["tags"]["highway"]
    if isi26(w) or is74(w):
        return "hwy"
    if hw == "secondary":
        return "sec"
    if hw in ("tertiary", "unclassified"):
        return "minor"
    if hw in ("residential", "motorway_link", "secondary_link"):
        return "res"
    return None


muni_fill = []
try:
    _mw = json.load(open(data_path("muni_ways.json")))
    ways_pts = [[[round(p["lat"], 5), round(p["lon"], 5)]
                 for p in w.get("geometry") or []]
                for w in _mw]
    muni_fill = assemble_rings([w for w in ways_pts if len(w) >= 2])
    print(f"muni rings: {len(muni_fill)}")
except FileNotFoundError:
    pass

water_line, water_poly = [], []
try:
    for w in json.load(open(data_path("water.json"))):
        g = [[round(p["lat"], 5), round(p["lon"], 5)]
             for p in w.get("geometry") or []]
        if len(g) < 2:
            continue
        if w.get("tags", {}).get("natural") == "water":
            water_poly.append(g)
        else:
            water_line.append(g)
    print(f"water: {len(water_line)} lines, {len(water_poly)} polys")
except FileNotFoundError:
    pass

area_labels = []
for p in PLACES:
    nm = p["tags"].get("name", "")
    if not (AB[0] < p["lat"] < AB[2] and AB[1] < p["lon"] < AB[3]):
        continue
    town = p["tags"].get("place") == "town"
    area_labels.append({"ll": [round(p["lat"], 5), round(p["lon"], 5)],
                        "html": nm, "cls": "tn" + ("" if town else " h"),
                        "ox": 30 if nm == "Beulah" else 0,
                        "oy": 14 if nm in ("Beulah", "Mill Spring") else 0,
                        "z": 800})
for tgt, ref, svg in [((35.263, -82.19), "us74", us_shield("74")),
                      ((35.284, -82.095), "us74", us_shield("74")),
                      ((35.268, -82.181), "NC 108", nc_shield("108")),
                      ((35.305, -82.163), "NC 108", nc_shield("108")),
                      ((35.252, -82.093), "NC 9", nc_shield("9")),
                      ((35.290, -82.140), "NC 9", nc_shield("9")),
                      ((35.245, -82.218), "I 26", i_shield("26"))]:
    pred = (is74 if ref == "us74" else isi26 if ref == "I 26"
            else (lambda w, r=ref: w["tags"].get("ref") == r))
    v, _ = vertex_and_rot(pred, tgt)
    if v:
        area_labels.append({"ll": v, "html": svg, "cls": "", "ox": 0,
                            "oy": 0, "z": 900})
area_payload = {
    "minz": 10, "maxz": 17, "mapbg": "#E9F0E6",
    "fb": [[AB[0], AB[1]], [AB[2], AB[3]]],
    "order": ["res", "minor", "sec", "hwy"],
    "style": {
        "res": [{"color": "#DFE3E0", "weight": 1.8, "opacity": 1},
                {"color": "#FFFFFF", "weight": 1.0, "opacity": 1}],
        "minor": [{"color": "#CFD5D2", "weight": 3.0, "opacity": 1},
                  {"color": "#FFFFFF", "weight": 1.8, "opacity": 1}],
        "sec": [{"color": "#C0C7CD", "weight": 4.0, "opacity": 1},
                {"color": "#FFFFFF", "weight": 2.5, "opacity": 1}],
        "hwy": [{"color": "#7E93AC", "weight": 4.4, "opacity": 1},
                {"color": "#9FB1C6", "weight": 2.8, "opacity": 1}]},
    "roads": clip(AB, area_cls),
    "muniFill": muni_fill,
    "waterLine": water_line, "waterPoly": water_poly,
    "pin": MID, "pinSvg": PIN,
    "labels": area_labels,
}
build(f"{SP}/{WO}_AreaMap.html", "Area Map", area_payload,
      datasource="NCDOT, OpenStreetMap, VHB")

# ================================================================ 3 AADT
DB = (35.246, -82.206, 35.300, -82.094)


def adt_cls(w):
    hw = w["tags"]["highway"]
    if is74(w):
        return "us74"
    if isi26(w):
        return "hwy"
    if hw == "secondary":
        return "sec"
    if hw in ("tertiary", "unclassified"):
        return "minor"
    if hw in ("residential", "motorway_link", "secondary_link"):
        return "res"
    return None


CLASS_COLOR = {"1": "#3B6FB5", "2": "#E8112D", "3": "#B14FC5",
               "4": "#38A800", "8": "#000000"}
stations = []
for f in aadt["features"]:
    lon, lat = f["geometry"]["coordinates"]
    if not (DB[0] <= lat <= DB[2] and DB[1] <= lon <= DB[3]):
        continue
    c = CLASS_COLOR.get(str(f["properties"].get("Route", ""))[:1])
    if c:
        stations.append({"ll": [round(lat, 5), round(lon, 5)], "c": c})
print(f"AADT stations in frame: {len(stations)}")

MAINS = []
for f in aadt["features"]:
    p = f["properties"]
    if p.get("Route") == 20000074075 and p.get("LocationID") in (
            "0750000218", "0750000003", "0750000007"):
        lon, lat = f["geometry"]["coordinates"]
        MAINS.append({"id": p["LocationID"],
                      "ll": [round(lat, 5), round(lon, 5)],
                      "loc": (p.get("Location") or "").replace(
                          "US 74 ", "").upper(),
                      "props": p})
MAINS.sort(key=lambda s: s["ll"][1])

panels_html = ""
panel_leaders = []
numbered = []
PANEL_POS = {"0750000218": (10, 128), "0750000003": (398, 14),
             "0750000007": (688, 16)}
for n, st in enumerate(MAINS, start=1):
    numbered.append({"ll": st["ll"], "n": n})
    x, y = PANEL_POS[st["id"]]
    rows = ""
    for key, val in [("LocationID", st["id"]), ("COUNTY", "POLK"),
                     ("RTE_CLS", "US Routes"), ("ROUTE", "US 74"),
                     ("LOCATION", st["loc"])]:
        rows += f'<div class="row"><b>{key}</b><span>{val}</span></div>'
    for yy in range(2002, 2025):
        val = str(st["props"].get(f"AADT_{yy}") or "").strip()
        hot = ' hot' if yy == 2024 else ''
        rows += (f'<div class="row{hot}"><b>AADT_{yy}</b>'
                 f'<span>{val}</span></div>')
    pid = f"panel{n}"
    panels_html += (f'<div class="panel" id="{pid}" '
                    f'style="left:{x}px;top:{y}px">'
                    f'<div class="bd">{rows}</div></div>')
    panel_leaders.append({"id": pid, "ll": st["ll"]})

adt_labels = road_name_labels(DB, 11, "gn", minsep=95, oy=-10,
                              skip=("Golden Maple Drive",
                                    "Lone Cypress Trail"))
v, rot = vertex_and_rot(is74, (35.2705, -82.155))
if v:
    adt_labels.append({"ll": v, "html": "Sgt W Dean Arledge Memorial Hwy",
                       "cls": "gn", "rot": rot, "ox": 0, "oy": -12,
                       "z": 500})
for tgt in ((35.2618, -82.186), (35.2838, -82.103)):
    v, _ = vertex_and_rot(is74, tgt)
    if v:
        adt_labels.append({"ll": v, "html": us_shield("74"), "cls": "",
                           "ox": 0, "oy": 0, "z": 850})
for tgt, ref in [((35.270, -82.1815), "NC 108"), ((35.255, -82.097), "NC 9"),
                 ((35.290, -82.134), "NC 9")]:
    v, _ = vertex_and_rot(lambda w, r=ref: w["tags"].get("ref") == r, tgt)
    if v:
        adt_labels.append({"ll": v, "html": nc_shield(ref.split()[1]),
                           "cls": "", "ox": 0, "oy": 0, "z": 850})

adt_payload = {
    "minz": 10, "maxz": 17, "mapbg": "#FBFBFA",
    "fb": [[DB[0], DB[1]], [DB[2], DB[3]]],
    "order": ["res", "minor", "sec", "hwy", "us74"],
    "style": {
        "res": [{"color": "#E4E4E2", "weight": 1.4, "opacity": 1}],
        "minor": [{"color": "#D8D8D6", "weight": 3.0, "opacity": 1},
                  {"color": "#FFFFFF", "weight": 1.7, "opacity": 1}],
        "sec": [{"color": "#CFCFCD", "weight": 4.0, "opacity": 1},
                {"color": "#FFFFFF", "weight": 2.4, "opacity": 1}],
        "hwy": [{"color": "#CFCFCD", "weight": 4.6, "opacity": 1},
                {"color": "#FFFFFF", "weight": 2.8, "opacity": 1}],
        "us74": [{"color": "#C9C9C7", "weight": 5.4, "opacity": 1},
                 {"color": "#FFFFFF", "weight": 3.4, "opacity": 1},
                 {"color": "#5BC8F0", "weight": 2.8, "opacity": 0.95}]},
    "roads": clip(DB, adt_cls),
    "stations": stations,
    "numbered": numbered,
    "panelLeaders": panel_leaders,
    "redEllipse": {"pad": 14, "b": 26},
    "study": STUDY,
    "labels": adt_labels,
}
build(f"{SP}/{WO}_AADTMap.html", "AADT Map", adt_payload,
      panels=panels_html, legend=True,
      datasource="NCDOT AADT Mapping Application")
print("done")
