"""Package maps for HSIP Study 41000079305 in the consultant figure format.

Chrome modeled on the HSIP Study 41000074368 figures (and slip
240816037AA siblings): bordered page, map frame, info table
(PH # / Work Order / Division / County / Location Description /
Latitude / Longitude), bottom title block (logo, study number and
date, map name, figure number), red bordered study location box top
left with a red leader, thin red ellipse around the study section,
white rotated road label boxes on aerial, plain black north arrow,
small legend and scale bar.

Figure 1 Location Map (aerial), Figure 2 Area Map (grey street
vector), Figure 3 AADT Map (roads with mainline count stations).
"""
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
STUDY_NO = "41000079305"
DATE = "08/15/2026"
TBL = {"ph": "", "wo": STUDY_NO, "div": "14", "county": "Polk",
       "desc": "US 74 from MP 12.800 to MP 13.815",
       "lat": "35.275639", "lon": "-82.132762"}

cl = json.load(open(f"{REPO}/centerline_us74.geojson"))
CO = cl["features"][0]["geometry"]["coordinates"]
STUDY = [[round(c[1], 6), round(c[0], 6)] for c in CO if 12.8 <= c[2] <= 13.815]

osm = json.load(open(f"{SP}/osm2.json"))
WAYS = [e for e in osm["elements"] if e["type"] == "way"
        and "highway" in e.get("tags", {})]
PLACES = [e for e in osm["elements"] if e["type"] == "node"]
RELS = [e for e in osm["elements"] if e["type"] == "relation"]

SRNUM = {"SMITH-WALDROP RD": "1528", "SMITH WALDROP RD": "1528",
         "POST OFFICE RD": "1166", "HUGH CHAMPION RD": "1525",
         "WALKER RD": "1533", "S PEAK ST": "1534", "TURNER RD": "1334",
         "MEADOWLARK LN": "1566", "BILL COLLINS RD": "1526",
         "SILVER CREEK RD": "1138", "LANDRUM RD": "1520",
         "BLANTON ST": "1535", "SMITH DAIRY RD": "1519",
         "JOHN SHEHAN RD": "1330", "SCHOOL RD": "1321",
         "SANDY PLAINS RD": "1005", "WILL GREEN RD": "1335",
         "FLOYD BLACKWELL RD": "1337", "HORSEPOWER LN": "1322",
         "OLD RUTHERFORDTON RD": "1368", "HAYES RD": "1534",
         "HOUSTON RD": "1137", "WALKER ST": "1137"}
_ABBR = ((" ROAD", " RD"), (" STREET", " ST"), (" LANE", " LN"),
         (" DRIVE", " DR"), (" PARKWAY", " PKWY"), (" TRAIL", " TRL"),
         (" AVENUE", " AVE"), (" HIGHWAY", " HWY"), (" COURT", " CT"))


def abbrev(name):
    up = name.upper()
    for a, b in _ABBR:
        if up.endswith(a):
            up = up[: -len(a)] + b
    return up


def srnum(name):
    return SRNUM.get(abbrev(name))


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


def muni_lines(b):
    path = f"{SP}/muni_ways.json"
    if not os.path.exists(path):
        return []
    lines = []
    for w in json.load(open(path)):
        g = w.get("geometry") or []
        if len(g) >= 2 and any(
                b[0] <= p["lat"] <= b[2] and b[1] <= p["lon"] <= b[3]
                for p in g):
            lines.append([[round(p["lat"], 5), round(p["lon"], 5)]
                          for p in g])
    return lines


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


def named_way_label(name):
    def pred(w):
        return w["tags"].get("name", "").upper() == name.upper()
    return pred


def sr_number_labels(b, cap=14, minsep=80):
    latpx = 606 / (b[2] - b[0])
    lonpx = 1004 / (b[3] - b[1])
    by = defaultdict(list)
    for w in WAYS:
        nm = w["tags"].get("name")
        if not nm or not srnum(nm):
            continue
        if w["tags"]["highway"] not in ("tertiary", "unclassified",
                                        "residential", "secondary"):
            continue
        g = [p for p in (w.get("geometry") or [])
             if b[0] <= p["lat"] <= b[2] and b[1] <= p["lon"] <= b[3]]
        if len(g) >= 2:
            by[srnum(nm)].append(g)
    placed, out = [], []
    for num, segs in sorted(by.items(), key=lambda x: -max(len(s) for s in x[1])):
        if len(out) >= cap:
            break
        seg = max(segs, key=len)
        i = len(seg) // 2
        mid = seg[i]
        if not (b[0] + 0.045 * (b[2]-b[0]) <= mid["lat"] <= b[2] - 0.045 * (b[2]-b[0])
                and b[1] + 0.05 * (b[3]-b[1]) <= mid["lon"] <= b[3] - 0.05 * (b[3]-b[1])):
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
                    "html": num, "cls": "srn", "rot": round(ang, 1),
                    "ox": 0, "oy": -9})
    return out


def us_shield(num):
    return ('<svg width="26" height="24" viewBox="0 0 26 24">'
            '<path d="M13 22.8 C8.2 19.9 2.2 17.8 2.2 9.7 C2.2 6.8 3 4.8 4 '
            '3.7 C6.3 4.8 8.7 5.2 13 5.2 C17.3 5.2 19.7 4.8 22 3.7 C23 4.8 '
            '23.8 6.8 23.8 9.7 C23.8 17.8 17.8 19.9 13 22.8 Z" fill="#fff" '
            'stroke="#000" stroke-width="1.5"/>'
            f'<text x="13" y="15.8" text-anchor="middle" font-size="9.5" '
            f'font-weight="bold" font-family="Arial" fill="#000">{num}'
            '</text></svg>')


def nc_shield(num):
    fs = 7.5 if len(num) > 2 else 9
    return ('<svg width="26" height="26" viewBox="0 0 26 26">'
            '<rect x="5" y="5" width="16" height="16" '
            'transform="rotate(45 13 13)" fill="#000" stroke="#fff" '
            'stroke-width="1"/>'
            f'<text x="13" y="{13 + fs * 0.36:.1f}" text-anchor="middle" '
            f'font-size="{fs}" font-weight="bold" font-family="Arial" '
            f'fill="#fff">{num}</text></svg>')


def i_shield(num):
    return ('<svg width="26" height="26" viewBox="0 0 26 26">'
            '<path d="M13 24.6 C6.3 21.7 2 18.6 2 12.9 L2 8.3 C5.3 9.3 9 '
            '9.7 13 9.7 C17 9.7 20.7 9.3 24 8.3 L24 12.9 C24 18.6 19.7 '
            '21.7 13 24.6 Z" fill="#003F87" stroke="#fff" '
            'stroke-width="1.1"/>'
            '<path d="M2 8.3 C2 5.2 3 3.3 4.1 2.1 C7 3.5 9.9 4.1 13 4.1 '
            'C16.1 4.1 19 3.5 21.9 2.1 C23 3.3 24 5.2 24 8.3 C20.7 9.3 17 '
            '9.7 13 9.7 C9 9.7 5.3 9.3 2 8.3 Z" fill="#CE1126" '
            'stroke="#fff" stroke-width="1.1"/>'
            f'<text x="13" y="19.6" text-anchor="middle" font-size="8.5" '
            f'font-weight="bold" font-family="Arial" fill="#fff">{num}'
            '</text></svg>')


CSS = """html,body{margin:0;width:1056px;height:816px;background:#fff;
font-family:Arial,Helvetica,sans-serif;overflow:hidden;color:#000}
#page{position:absolute;inset:12px;border:1.6px solid #000}
#frame{position:absolute;top:10px;left:10px;right:10px;height:612px;
border:1.5px solid #000;overflow:hidden}
#map{position:absolute;inset:0;background:#F4F3F0}
.leaflet-container{background:#F4F3F0}
#tbl{position:absolute;left:10px;right:10px;top:634px}
#tbl table{width:100%;border-collapse:collapse}
#tbl th{background:#D9D9D9;border:1.2px solid #000;font-size:11px;
padding:4px 2px}
#tbl td{border:1.2px solid #000;font-size:10.5px;padding:9px 2px;
text-align:center}
#ttl{position:absolute;left:10px;right:10px;bottom:8px;height:70px;
display:flex;border:1.2px solid #000}
#ttl>div{border-left:1.2px solid #000;display:flex;flex-direction:column;
justify-content:center;align-items:center;text-align:center}
#ttl>div:first-child{border-left:none}
#logo{width:26%;font-size:30px;font-weight:bold;color:#00447C;
letter-spacing:0.04em}
#tmid{width:34%;font-size:13.5px;font-weight:bold;line-height:1.5}
#tname{width:25%;font-size:13.5px;font-weight:bold}
#tfig{width:15%;font-size:13.5px;font-weight:bold}
#studybox{position:absolute;top:12px;left:12px;z-index:1300;
background:#fff;border:1.6px solid #C00000;padding:5px 12px;
font-size:11px;line-height:1.45;text-align:center}
#north{position:absolute;top:12px;right:12px;z-index:1300;background:#fff;
border:1px solid #666;padding:3px 6px 1px;text-align:center}
#legend{position:absolute;right:12px;bottom:44px;z-index:1300;
background:#fff;border:1.2px solid #000;padding:4px 10px 6px;
font-size:10.5px}
#legend .h{font-weight:bold;font-size:11.5px;text-align:center;
margin-bottom:3px}
#legend .r{display:flex;align-items:center;gap:7px;margin-top:2px}
#scale{position:absolute;right:12px;bottom:10px;z-index:1300;
background:rgba(255,255,255,.92);border:1px solid #888;
padding:2px 8px 4px}
#attrib{position:absolute;left:12px;bottom:10px;z-index:1300;
color:#555;font-size:8.5px;background:rgba(255,255,255,.75);
padding:1px 5px}
#leader{position:absolute;inset:0;z-index:1200;pointer-events:none}
.lblc{position:relative}
.lblc>span{position:absolute;white-space:nowrap;text-align:center;
display:inline-block;line-height:1.2}
.wb{background:#fff;border:1px solid #000;color:#000;font-weight:bold;
font-size:10.5px;padding:2px 9px}
.srn{color:#3D4147;font-weight:bold;font-size:9.5px;
text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,
1px 1px 0 #fff,0 0 2px #fff}
.tn{color:#1F1F1F;font-weight:bold;font-size:12.5px;
letter-spacing:0.06em;
text-shadow:-1.5px -1.5px 0 #fff,1.5px -1.5px 0 #fff,
-1.5px 1.5px 0 #fff,1.5px 1.5px 0 #fff,0 0 3px #fff}
.tn small{display:block;font-size:10px;font-weight:normal;
letter-spacing:0}
.tn.h{font-size:10.5px}
.ab{background:#fff;border:1px solid #000;color:#000;font-size:10.5px;
line-height:1.45;padding:3px 4px;text-align:left}
.ab b.hot{display:block;border:2px solid #C00000;padding:0 3px;
font-weight:bold}
.ab span{display:block;padding:0 5px}
.rb{background:#fff;border:1.6px solid #C00000;color:#000;
font-size:10.5px;line-height:1.45;padding:5px 10px;text-align:center}
"""

JS = r"""(function(){
const P=window.P;
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
for(const cls of P.order||[]){
  const passes=P.style[cls], group=P.roads[cls];
  if(!passes||!group) continue;
  for(const spec of passes)
    for(const pts of group)
      L.polyline(pts,Object.assign({interactive:false},spec)).addTo(map);
}
for(const pts of P.muni||[])
  L.polyline(pts,{color:"#7A7A7A",weight:1.6,dashArray:"6 4",
    interactive:false}).addTo(map);
// red ellipse around the study section
const p0=cpt(P.study[0]), p1=cpt(P.study[P.study.length-1]);
const ecx=(p0.x+p1.x)/2, ecy=(p0.y+p1.y)/2;
const ea=Math.hypot(p1.x-p0.x,p1.y-p0.y)/2+P.ellPad, eb=P.ellB;
const eang=Math.atan2(p1.y-p0.y,p1.x-p0.x)*180/Math.PI;
lbl(cll([ecx,ecy]),
  '<svg width="'+(2*ea+12)+'" height="'+(2*eb+12)+'">'+
  '<ellipse cx="'+(ea+6)+'" cy="'+(eb+6)+'" rx="'+ea+'" ry="'+eb+
  '" fill="none" stroke="#D40000" stroke-width="2.6"/></svg>',
  "",0,0,eang,600);
for(const s of (P.stations||[])){
  const ap=cpt(s.ll), bc=[ap.x+s.off[0],ap.y+s.off[1]];
  L.polyline([s.ll,cll(bc)],{color:"#000",weight:1.2,
    interactive:false}).addTo(map);
  let rows="";
  for(const r of s.rows){
    const t=r[0]+" AADT = "+r[1];
    rows+=(r[0]===s.hot)?'<b class="hot">'+t+'</b>':'<span>'+t+'</span>';
  }
  lbl(cll(bc),rows,"ab",0,0,0,300);
  lbl(s.ll,'<svg width="13" height="13"><rect x="2.8" y="2.8" '+
    'width="7.4" height="7.4" transform="rotate(45 6.5 6.5)" '+
    'fill="#1F6FDE" stroke="#0A2E66" stroke-width="1.4"/></svg>',
    "",0,0,0,400);
}
for(const c of (P.notes||[])){
  const ap=cpt(c.a), bc=[ap.x+c.off[0],ap.y+c.off[1]];
  L.polyline([c.a,cll(bc)],{color:"#000",weight:1.2,
    interactive:false}).addTo(map);
  lbl(cll(bc),c.html,"rb",0,0,0,500);
}
for(const l of (P.labels||[]))
  lbl(l.ll,l.html,l.cls,l.ox,l.oy,l.rot||0,l.z||0);
// red leader from study box to the ellipse
(function(){
  const box=document.getElementById("studybox");
  const fr=document.getElementById("frame").getBoundingClientRect();
  const br=box.getBoundingClientRect();
  const x0=br.right-fr.left-6, y0=br.bottom-fr.top-4;
  const t=cpt(P.leaderTo);
  const svg=document.getElementById("leader");
  svg.setAttribute("width",fr.width);svg.setAttribute("height",fr.height);
  svg.innerHTML='<line x1="'+x0+'" y1="'+y0+'" x2="'+t.x+'" y2="'+t.y+
    '" stroke="#C00000" stroke-width="1.6"/>';
})();
// scale bar
(function(){
  const z=map.getZoom(), c=map.getCenter();
  const ftpp=40075016.686*Math.cos(c.lat*Math.PI/180)/
    Math.pow(2,z+8)*3.28084;
  const totFt=P.scaleUnit==="Miles"?P.scaleTot*5280:P.scaleTot;
  const w=totFt/ftpp;
  function lab(x,v){return '<span style="position:absolute;top:0;left:'+
    x+'px;transform:translateX(-50%);font-size:9px">'+
    v.toLocaleString("en-US")+'</span>';}
  document.getElementById("scale").innerHTML=
    '<div style="position:relative;height:20px;width:'+(w+34)+'px">'+
    '<div style="position:absolute;left:0;top:11px;width:'+w+
    'px;height:5px;border:1px solid #000;background:#fff"></div>'+
    '<div style="position:absolute;left:1px;top:12px;width:'+(w/2)+
    'px;height:3px;background:#3b3b3b"></div>'+
    lab(0,0)+lab(w/2,P.scaleTot/2)+lab(w,P.scaleTot)+
    '<span style="position:absolute;left:'+(w+6)+
    'px;top:10px;font-size:9px">'+P.scaleUnit+'</span></div>';
})();
window._map=map;
})();"""

NORTH = ('<svg width="22" height="34" viewBox="0 0 22 34">'
         '<polygon points="11,1 18,24 11,18 4,24" fill="#111"/>'
         '<text x="11" y="33" text-anchor="middle" font-size="11" '
         'font-weight="bold" font-family="Arial" fill="#111">N</text>'
         '</svg>')
GL_ELL = ('<svg width="26" height="14"><ellipse cx="13" cy="7" rx="11" '
          'ry="5.5" fill="none" stroke="#D40000" stroke-width="2"/></svg>')
GL_MUNI = ('<svg width="26" height="8"><line x1="1" y1="4" x2="25" y2="4" '
           'stroke="#7A7A7A" stroke-width="1.6" '
           'stroke-dasharray="6 4"/></svg>')
GL_STA = ('<svg width="26" height="13"><rect x="9.3" y="2.8" width="7.4" '
          'height="7.4" transform="rotate(45 13 6.5)" fill="#1F6FDE" '
          'stroke="#0A2E66" stroke-width="1.4"/></svg>')


def vendor(name):
    return (resources.files("safety_eval") / "vendor" / name).read_text(
        encoding="utf-8")


def build(out, name, fig, payload, legend_rows, tiles=None, attrib=""):
    tile_js = (f"window.TILES={json.dumps(tiles)};" if tiles else "")
    leg = "".join(f'<div class="r">{g}<span>{t}</span></div>'
                  for g, t in legend_rows)
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{name} - HSIP Study {STUDY_NO}</title>
<style>{vendor('leaflet.min.css')}</style><style>{CSS}</style></head><body>
<div id="page">
<div id="frame"><div id="map"></div>
<svg id="leader"></svg>
<div id="studybox"><b>Study Location:</b><br>US 74, Polk County<br>
MP 12.800 to MP 13.815</div>
<div id="north">{NORTH}</div>
<div id="legend"><div class="h">Legend</div>{leg}</div>
<div id="scale"></div>
{f'<div id="attrib">{attrib}</div>' if attrib else ''}</div>
<div id="tbl"><table><tr><th style="width:9%">PH #</th>
<th style="width:12%">Work Order</th><th style="width:8%">Division</th>
<th style="width:9%">County</th>
<th style="width:43%">Location Description</th>
<th style="width:9.5%">Latitude</th>
<th style="width:9.5%">Longitude</th></tr>
<tr><td>{TBL['ph']}</td><td>{TBL['wo']}</td><td>{TBL['div']}</td>
<td>{TBL['county']}</td><td>{TBL['desc']}</td><td>{TBL['lat']}</td>
<td>{TBL['lon']}</td></tr></table></div>
<div id="ttl"><div id="logo">VHB</div>
<div id="tmid">HSIP Study &ndash; {STUDY_NO}<br>{DATE}</div>
<div id="tname">{name}</div><div id="tfig">Figure {fig}</div></div>
</div>
<script>{vendor('leaflet.min.js')}</script>
<script>{tile_js}window.P={json.dumps(payload)};</script>
<script>{JS}</script></body></html>"""
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"  -> {out} ({len(html) // 1024} KB)")


# ============================================================ 1 LOCATION
LB = (35.2665, -82.1525, 35.2845, -82.1125)
loc_labels = []
for tgt in ((35.2705, -82.147), (35.2825, -82.118)):
    v, rot = vertex_and_rot(is74, tgt)
    if v:
        loc_labels.append({"ll": v, "html": "US 74", "cls": "wb",
                           "rot": rot, "ox": 0, "oy": -22, "z": 700})
for nm, disp, tgt, oy in [
        ("Bill Collins Road", "SR 1526 (Bill Collins Rd)",
         (35.2735, -82.1435), -18),
        ("Smith Waldrop Road", "SR 1528 (Smith-Waldrop Rd)",
         (35.2812, -82.138), -18),
        ("Hugh Champion Road", "SR 1525 (Hugh Champion Rd)",
         (35.2755, -82.1155), -18)]:
    v, rot = vertex_and_rot(named_way_label(nm), tgt)
    if v:
        loc_labels.append({"ll": v, "html": disp, "cls": "wb", "rot": rot,
                           "ox": 0, "oy": oy, "z": 650})
loc_payload = {
    "minz": 14, "maxz": 16,
    "fb": [[LB[0], LB[1]], [LB[2], LB[3]]],
    "order": [], "style": {}, "roads": {},
    "study": STUDY, "ellPad": 26, "ellB": 46,
    "leaderTo": STUDY[0],
    "labels": loc_labels,
    "scaleTot": 4000, "scaleUnit": "Feet",
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
build(f"{SP}/{STUDY_NO}_LocationMap.html", "Location Map", 1, loc_payload,
      [(GL_ELL, "Study Section")], tiles,
      attrib="Esri, Maxar, Earthstar Geographics")

# ================================================================ 2 AREA
AB = (35.238, -82.225, 35.322, -82.055)


def area_cls(w):
    hw = w["tags"]["highway"]
    if isi26(w) or is74(w):
        return "hwy"
    if hw in ("motorway_link", "secondary_link"):
        return "link"
    if hw == "secondary":
        return "sec"
    if hw in ("tertiary", "unclassified"):
        return "minor"
    if hw == "residential":
        return "res"
    return None


area_labels = sr_number_labels(AB, cap=14)
for p in PLACES:
    nm = (p["tags"].get("name") or "").upper()
    if not (AB[0] < p["lat"] < AB[2] and AB[1] < p["lon"] < AB[3]):
        continue
    town = p["tags"].get("place") == "town"
    pop = p["tags"].get("population")
    html = nm + (f"<small>Pop. {int(pop):,}</small>" if pop and town else "")
    ox, oy = (30, 14) if nm == "BEULAH" else (0, 12) if nm == "MILL SPRING" \
        else (0, 0)
    area_labels.append({"ll": [round(p["lat"], 5), round(p["lon"], 5)],
                        "html": html, "cls": "tn" + ("" if town else " h"),
                        "ox": ox, "oy": oy, "z": 800})
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
    "minz": 10, "maxz": 17,
    "fb": [[AB[0], AB[1]], [AB[2], AB[3]]],
    "order": ["res", "minor", "link", "sec", "hwy"],
    "style": {
        "res": [{"color": "#DCDCDC", "weight": 1.1, "opacity": 1}],
        "minor": [{"color": "#C4C4C4", "weight": 1.9, "opacity": 1}],
        "link": [{"color": "#C9C9C9", "weight": 1.4, "opacity": 1}],
        "sec": [{"color": "#9FA4AA", "weight": 2.6, "opacity": 1}],
        "hwy": [{"color": "#141414", "weight": 4.6, "opacity": 1},
                {"color": "#FFFFFF", "weight": 1.5, "opacity": 1}]},
    "roads": clip(AB, area_cls),
    "muni": muni_lines(AB),
    "study": STUDY, "ellPad": 12, "ellB": 20,
    "leaderTo": STUDY[0],
    "labels": area_labels,
    "scaleTot": 2, "scaleUnit": "Miles",
}
build(f"{SP}/{STUDY_NO}_AreaMap.html", "Area Map", 2, area_payload,
      [(GL_ELL, "Study Section"), (GL_MUNI, "Municipal Boundary")])

# ================================================================ 3 AADT
DB = (35.244, -82.205, 35.302, -82.088)
aadt_labels = sr_number_labels(DB, cap=9)
for tgt in ((35.2645, -82.178), (35.284, -82.097)):
    v, rot = vertex_and_rot(is74, tgt)
    if v:
        aadt_labels.append({"ll": v, "html": "US 74", "cls": "wb",
                            "rot": rot, "ox": 0, "oy": -20, "z": 700})
for tgt, ref, svg in [((35.266, -82.181), "NC 108", nc_shield("108")),
                      ((35.293, -82.163), "NC 108", nc_shield("108")),
                      ((35.255, -82.094), "NC 9", nc_shield("9")),
                      ((35.284, -82.13), "NC 9", nc_shield("9"))]:
    v, _ = vertex_and_rot(lambda w, r=ref: w["tags"].get("ref") == r, tgt)
    if v:
        aadt_labels.append({"ll": v, "html": svg, "cls": "", "ox": 0,
                            "oy": 0, "z": 900})
STA = [
    {"ll": [35.259, -82.19343], "off": [-4, 66], "hot": "2024",
     "rows": [["2024", "21,000"], ["2023", "20,000"], ["2022", "17,500"]]},
    {"ll": [35.26306, -82.17387], "off": [40, 70], "hot": "2024",
     "rows": [["2024", "18,500"], ["2023", "19,000"], ["2022", "17,000"]]},
    {"ll": [35.28569, -82.105], "off": [-30, 68], "hot": "2024",
     "rows": [["2024", "15,500"], ["2023", "18,000"], ["2022", "15,500"]]},
]
aadt_payload = {
    "minz": 10, "maxz": 17,
    "fb": [[DB[0], DB[1]], [DB[2], DB[3]]],
    "order": ["res", "minor", "link", "sec", "hwy"],
    "style": area_payload["style"],
    "roads": clip(DB, area_cls),
    "muni": [],
    "study": STUDY, "ellPad": 12, "ellB": 24,
    "leaderTo": STUDY[0],
    "stations": STA,
    "notes": [{"a": STUDY[len(STUDY) // 2], "off": [-30, -128],
               "html": ("Assumed AADT equal to the US 74<br>"
                        "station east of NC 108<br>"
                        "<b>2024 AADT = 18,500</b>")}],
    "labels": aadt_labels,
    "scaleTot": 2, "scaleUnit": "Miles",
}
build(f"{SP}/{STUDY_NO}_AADTMap.html", "AADT Map", 3, aadt_payload,
      [(GL_ELL, "Study Section"), (GL_STA, "AADT Count Station")])
print("done")
