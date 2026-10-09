#!/usr/bin/env python3
"""Location map, area map and collision diagram for TEAAS study 41000079736.

Outputs in ./maps/:
  1_location_map.png   county-scale street map with the study intersection marked
  2_area_map.png       aerial area map with the 150 ft Y-line and the NCDOT AADT stations
  3_collision_diagram.png   schematic collision diagram of the 22 analyzed crashes
  4_crash_location_map.png  aerial close-up with the geocoded analyzed crashes plotted
  41000079736_maps.pdf      all figures as one PDF
Basemap tiles: OpenStreetMap (location) and Esri World Imagery (area). Tiles are cached in ./maps/.tiles/.
"""
import csv, io, json, math, os, urllib.request
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, RegularPolygon, FancyArrowPatch, Rectangle, Circle
from matplotlib.path import Path as MPath
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "maps"; CACHE = OUT / ".tiles"
STUDY = "41000079736"
TITLE = "NC 180/NC 226 (S Post Rd) at SR 1103 (Pleasant Dr / Pleasant Hill Church Rd)"
SUB = "Cleveland County, Division 12  |  TEAAS Study 41000079736  |  9/1/2021 - 8/31/2026 (5 yr), Y-line 150 ft"
LAT, LON = 35.246324, -81.509409
BEAR_MAIN = 22.0     # NC 180/NC 226 axis, degrees clockwise from north (toward the north leg)
BEAR_SIDE = 333.0    # SR 1103 axis, toward the Pleasant Dr (northwest) leg
OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ESRI_IMG = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ESRI_STREET = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"


# ----------------------------------------------------------------------------- tiles
def px(lat, lon, z):
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile(url, z, x, y):
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (url.split("//")[1].split("/")[0].replace(".", "_") + f"_{z}_{x}_{y}.png")
    if not key.exists():
        req = urllib.request.Request(url.format(z=z, x=x, y=y), headers={"User-Agent": "hsip-map-script/1.0 (NCDOT crash analysis)"})
        key.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    return Image.open(key).convert("RGB")


def basemap(url, z, half_w_m, half_h_m):
    """Stitched image centred on the study point. Returns image, and a lat/lon -> image px function."""
    mpp = 156543.03392 * math.cos(math.radians(LAT)) / 2 ** z
    cx, cy = px(LAT, LON, z)
    x0, x1 = cx - half_w_m / mpp, cx + half_w_m / mpp
    y0, y1 = cy - half_h_m / mpp, cy + half_h_m / mpp
    tx0, tx1, ty0, ty1 = int(x0 // 256), int(x1 // 256), int(y0 // 256), int(y1 // 256)
    im = Image.new("RGB", (256 * (tx1 - tx0 + 1), 256 * (ty1 - ty0 + 1)))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            im.paste(tile(url, z, tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    im = im.crop((int(x0 - tx0 * 256), int(y0 - ty0 * 256), int(x1 - tx0 * 256), int(y1 - ty0 * 256)))
    def to_px(lat, lon):
        X, Y = px(lat, lon, z)
        return X - x0, Y - y0
    return im, to_px, mpp


def scalebar(ax, mpp, x, y, miles, label):
    L = miles * 1609.344 / mpp
    ax.plot([x, x + L], [y, y], color="k", lw=3, solid_capstyle="butt")
    ax.plot([x, x + L / 2], [y, y], color="w", lw=1.5, solid_capstyle="butt")
    for xx, t in ((x, "0"), (x + L, label)):
        ax.text(xx, y - 6, t, ha="center", va="bottom", fontsize=8, color="k",
                bbox=dict(fc="w", ec="none", alpha=0.8, pad=1))


def north(ax, x, y):
    ax.annotate("", xy=(x, y - 40), xytext=(x, y), arrowprops=dict(arrowstyle="-|>", lw=2, color="k"))
    ax.text(x, y - 46, "N", ha="center", va="bottom", fontsize=11, fontweight="bold")


def marker(ax, x, y, s=14):
    ax.plot(x, y, marker="*", ms=s * 1.6, color="#d00000", mec="k", mew=0.8, zorder=10)


# ----------------------------------------------------------------------------- 1. location map
def location_map(pdf):
    im, to_px, mpp = basemap(OSM, 12, 12000, 9000)
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.imshow(im); ax.set_axis_off()
    x, y = to_px(LAT, LON); marker(ax, x, y, 18)
    ax.annotate("Study intersection\nNC 180/NC 226 at SR 1103", xy=(x, y), xytext=(x + 70, y + 110), fontsize=10, fontweight="bold",
                bbox=dict(fc="w", ec="#d00000", lw=1.2), arrowprops=dict(arrowstyle="->", color="#d00000", lw=1.5))
    scalebar(ax, mpp, 40, im.height - 40, 2, "2 mi"); north(ax, im.width - 50, 70)
    fig.suptitle("Location Map", fontsize=15, fontweight="bold", y=0.985)
    ax.set_title(f"{TITLE}\n{SUB}", fontsize=9.5, pad=6)
    fig.text(0.99, 0.01, "Basemap: © OpenStreetMap contributors", ha="right", fontsize=7, color="#444")
    fig.tight_layout(rect=(0, 0.015, 1, 0.97))
    fig.savefig(OUT / "1_location_map.png", dpi=150); pdf.savefig(fig); plt.close(fig)


# ----------------------------------------------------------------------------- 2. area map
def area_map(pdf, aadt):
    im, to_px, mpp = basemap(ESRI_IMG, 17, 1050, 820)
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.imshow(im); ax.set_axis_off()
    x, y = to_px(LAT, LON)
    r = 150 * 0.3048 / mpp
    ax.add_patch(Circle((x, y), r, fill=False, ec="#ffd400", lw=2.2, ls="--", zorder=9))
    ax.text(x + r + 6, y - r, "150 ft Y-line", color="#ffd400", fontsize=9, fontweight="bold", va="bottom",
            bbox=dict(fc="k", ec="none", alpha=0.45, pad=1.5))
    marker(ax, x, y, 14)
    # road labels along each leg
    def along(bearing, d_m):
        return to_px(LAT + d_m * math.cos(math.radians(bearing)) / 111320, LON + d_m * math.sin(math.radians(bearing)) / (111320 * math.cos(math.radians(LAT))))
    for bearing, text, rot in ((BEAR_MAIN, "NC 180 / NC 226\nS Post Rd", -BEAR_MAIN + 90), (BEAR_MAIN + 180, "NC 180 / NC 226\nS Post Rd", -BEAR_MAIN + 90),
                               (BEAR_SIDE, "SR 1103\nPleasant Dr", -(BEAR_SIDE - 360) + 90 - 180), (BEAR_SIDE + 180, "SR 1103\nPleasant Hill Church Rd", -(BEAR_SIDE - 360) + 90 - 180)):
        lx, ly = along(bearing, 330)
        ax.text(lx, ly, text, rotation=rot, ha="center", va="center", fontsize=8.5, color="w", fontweight="bold",
                bbox=dict(fc="k", ec="none", alpha=0.5, pad=1.5), zorder=8)
    # AADT stations
    for leg in aadt["legs"]:
        yr = max(leg["aadt"]); val = leg["aadt"][yr]
        sx, sy = to_px(leg["lat"], leg["lon"])
        inside = 0 <= sx < im.width and 0 <= sy < im.height
        if inside:
            ax.plot(sx, sy, "o", ms=9, color="#00b0ff", mec="k", zorder=10)
            ax.annotate(f"Sta. {leg['station']}\nAADT {yr}: {val:,}", xy=(sx, sy), xytext=(sx + 30, sy + (40 if sy > y else -40)), fontsize=8,
                        bbox=dict(fc="w", ec="#00b0ff", lw=1.2), arrowprops=dict(arrowstyle="-", color="#00b0ff"), zorder=11)
        else:  # station off the map: note it at the edge of the leg
            bearing = math.degrees(math.atan2((leg["lon"] - LON) * math.cos(math.radians(LAT)), leg["lat"] - LAT)) % 360
            ex, ey = along(bearing, 520)
            dist_ft = math.hypot((leg["lat"] - LAT) * 364000, (leg["lon"] - LON) * math.cos(math.radians(LAT)) * 364000)
            ax.text(ex, ey, f"Sta. {leg['station']} ({dist_ft/5280:.1f} mi off map)\nAADT {yr}: {val:,}", fontsize=8, ha="center",
                    bbox=dict(fc="w", ec="#00b0ff", lw=1.2), zorder=11)
    scalebar(ax, mpp, 40, im.height - 40, 0.1, "0.1 mi"); north(ax, im.width - 50, 70)
    fig.suptitle("Area Map", fontsize=15, fontweight="bold", y=0.985)
    ax.set_title(f"{TITLE}\n{SUB}", fontsize=9.5, pad=6)
    fig.text(0.99, 0.01, "Imagery: Esri, Maxar, Earthstar Geographics  |  AADT: NCDOT Traffic Survey Group", ha="right", fontsize=7, color="#444")
    fig.tight_layout(rect=(0, 0.015, 1, 0.97))
    fig.savefig(OUT / "2_area_map.png", dpi=150); pdf.savefig(fig); plt.close(fig)


# ----------------------------------------------------------------------------- 3. collision diagram
# Schematic: NC 180/NC 226 drawn vertical, SR 1103 horizontal (true skew is about 49 deg; see the rotated north arrow).
DIRV = {"N": (0, 1), "NE": (0, 1), "S": (0, -1), "SW": (0, -1), "W": (-1, 0), "NW": (-1, 0), "E": (1, 0), "SE": (1, 0)}
APPROACH = {"S": "N leg", "SW": "N leg", "N": "S leg", "NE": "S leg", "E": "NW leg", "SE": "NW leg", "W": "SE leg", "NW": "SE leg"}
LEG_DIR = {"N leg": (0, 1), "S leg": (0, -1), "NW leg": (-1, 0), "SE leg": (1, 0)}
OBJ = {"58": "ditch", "59": "embankment", "56": "catch basin"}
SEVC = {"K": "#000000", "A": "#c00000", "B": "#e8740c", "C": "#b89b00", "PDO": "#2b6cb0"}


def severity(c):
    for k in "KABC":
        if int(c[k]) > 0: return k
    return "PDO"


def arrow(ax, p0, p1, color, stopped=False, lw=2.0, z=6):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>" if not stopped else "-", mutation_scale=13, lw=lw, color=color,
                                 ls="-" if not stopped else (0, (2, 1.5)), zorder=z, shrinkA=0, shrinkB=0))
    if stopped:  # stopped vehicle: bar across the front
        d = (p1[0] - p0[0], p1[1] - p0[1]); L = math.hypot(*d); n = (-d[1] / L, d[0] / L)
        ax.plot([p1[0] - n[0] * 6, p1[0] + n[0] * 6], [p1[1] - n[1] * 6, p1[1] + n[1] * 6], color=color, lw=2.4, zorder=z)


def turn_arrow(ax, p0, p1, t, color, lw=2.0, z=6):
    """Curved arrow from p0 to p1 that starts along travel direction t."""
    L = 0.6 * math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    ctrl = (p0[0] + t[0] * L, p0[1] + t[1] * L)
    path = MPath([p0, ctrl, p1], [MPath.MOVETO, MPath.CURVE3, MPath.CURVE3])
    ax.add_patch(mpatches.FancyArrowPatch(path=path, arrowstyle="-|>", mutation_scale=13, lw=lw, color=color, zorder=z))


def turn_end(cen, t, left, r=34):
    """End point of a turning path: r ahead of the start and r to the left/right."""
    n = (-t[1], t[0]) if left else (t[1], -t[0])
    return (cen[0] + n[0] * r, cen[1] + n[1] * r)


def collision_diagram(pdf, crashes):
    fig = plt.figure(figsize=(17, 11))
    ax = fig.add_axes([0.005, 0.02, 0.655, 0.90]); ax.set_aspect("equal"); ax.set_axis_off()
    ax.set_xlim(-600, 600); ax.set_ylim(-520, 520)
    for (w, h, c) in ((30, 1040, "#d9d9d9"), (1200, 24, "#d9d9d9")):
        ax.add_patch(Rectangle((-w / 2, -h / 2), w, h, fc=c, ec="#777", lw=1, zorder=1))
    ax.plot([0, 0], [-520, 520], color="#e6b800", lw=0.9, ls=(0, (6, 4)), zorder=2)
    ax.plot([-600, 600], [0, 0], color="#e6b800", lw=0.9, ls=(0, (6, 4)), zorder=2)
    ax.add_patch(Rectangle((-15, -12), 30, 24, fc="#d9d9d9", ec="none", zorder=2.5))
    for x, y in ((-24, -20), (24, 20)):  # STOP signs on the SR 1103 approaches (right side of the approaching driver)
        ax.add_patch(RegularPolygon((x, y), 8, radius=8, fc="#c00000", ec="w", lw=0.8, zorder=7))
        ax.text(x, y, "STOP", ha="center", va="center", fontsize=3.4, color="w", fontweight="bold", zorder=8)
    ax.text(14, 60, "45 mph", fontsize=6.5, ha="left", va="center", zorder=9, rotation=90)
    for (x, y, text, r) in ((0, 490, "NC 180 / NC 226 (S Post Rd)  -  to NC 226 (Earl Rd) / Shelby", 0),
                            (0, -490, "NC 180 / NC 226 (S Post Rd)  -  to SR 1236 (Idlewild Rd)", 0),
                            (-572, 0, "SR 1103 (Pleasant Dr)  -  to SR 2384", 90), (572, 0, "SR 1103 (Pleasant Hill Church Rd)  -  to SR 2205", 90)):
        ax.text(x, y, text, rotation=r, ha="center", va="center", fontsize=8, fontweight="bold", bbox=dict(fc="w", ec="#777", alpha=0.95), zorder=9)
    # true north arrow (NC 180 is drawn vertical; true north is 22 deg counter-clockwise from the page top)
    nx, ny = -math.sin(math.radians(BEAR_MAIN)), math.cos(math.radians(BEAR_MAIN))
    bx, by = -520, 430
    ax.annotate("", xy=(bx + nx * 70, by + ny * 70), xytext=(bx, by), arrowprops=dict(arrowstyle="-|>", lw=2, color="k"))
    ax.text(bx + nx * 82, by + ny * 82, "N", ha="center", va="center", fontsize=12, fontweight="bold")
    ax.text(bx, by - 22, "true north\n(schematic, not to scale)", ha="center", va="top", fontsize=6.5)
    # assign each crash to the approach leg of its primary unit
    groups = {}
    for c in crashes:
        u1 = c["units"][0]
        side = [u for u in c["units"] if u["dir"] in ("E", "W", "SE", "NW")]
        prim = u1
        if c["Type"].startswith(("ANGLE", "LEFT TURN, DIFF", "RIGHT TURN")) and side and u1["mnvr"] not in ("8", "7"):
            prim = side[0]
        c["leg"] = APPROACH[prim["dir"]]
        groups.setdefault(c["leg"], []).append(c)
    for leg, cs in groups.items():
        u = LEG_DIR[leg]; t = (-u[0], -u[1]); n = (t[1], -t[0])   # t: travel toward the intersection; n: driver's right
        for k, c in enumerate(cs):
            side = 1 if k % 2 == 0 else -1
            dist = (215 if leg in ("N leg", "S leg") else 125) + 92 * (k // 2)
            cen = (u[0] * dist + n[0] * 60 * side, u[1] * dist + n[1] * 60 * side)
            sev = severity(c); col = SEVC[sev]; typ = c["Type"]
            if typ.startswith("REAR END"):
                a, b = c["units"][0], c["units"][1]; tv = DIRV[a["dir"]]
                arrow(ax, (cen[0] - tv[0] * 50, cen[1] - tv[1] * 50), cen, col)
                arrow(ax, (cen[0] + tv[0] * 4, cen[1] + tv[1] * 4), (cen[0] + tv[0] * 36, cen[1] + tv[1] * 36), col, stopped=(b["mnvr"] == "1"))
            elif typ.startswith("FIXED OBJECT"):
                a = c["units"][0]; tv = DIRV[a["dir"]]; p0 = (cen[0] - tv[0] * 50, cen[1] - tv[1] * 50)
                if a["mnvr"] == "7": turn_arrow(ax, p0, turn_end(cen, tv, False, 26), tv, col); obj = turn_end(cen, tv, False, 34)
                else: arrow(ax, p0, cen, col); obj = (cen[0] + tv[0] * 6, cen[1] + tv[1] * 6)
                ax.add_patch(Rectangle((obj[0] - 5, obj[1] - 5), 10, 10, fc="k", zorder=7))
                ax.text(obj[0] + tv[0] * 16 + 6, obj[1] + tv[1] * 16, OBJ.get(a["obj"], "object"), fontsize=5.5, ha="left", va="center", zorder=8)
            else:
                for un in c["units"]:
                    tv = DIRV[un["dir"]]; p0 = (cen[0] - tv[0] * 50, cen[1] - tv[1] * 50)
                    if un["mnvr"] == "8": turn_arrow(ax, p0, turn_end(cen, tv, True), tv, col)
                    elif un["mnvr"] == "7": turn_arrow(ax, p0, turn_end(cen, tv, False), tv, col)
                    else: arrow(ax, p0, cen, col, stopped=(un["mnvr"] == "1"))
            ax.plot(*cen, "o", ms=3.5, color=col, zorder=7)
            cond = (" Night" if c["Light"] in ("4", "5", "6") else "") + (" Wet" if c["RoadSurf"] == "2" else "")
            lab = f"#{c['No']}  {c['Date'][:6]}{c['Date'][-2:]}\n{c['Time']}  {sev}\n{cond.strip() or '-'}"
            lp = (cen[0] + n[0] * 66 * side + u[0] * 6, cen[1] + n[1] * 66 * side + u[1] * 6)
            ax.text(lp[0], lp[1], lab, fontsize=5.8, ha="center", va="center", color=col, zorder=9, linespacing=1.15,
                    bbox=dict(fc="w", ec=col, lw=0.6, alpha=0.92, pad=1.2))
    # legend
    lx, ly = -590, -510
    ax.add_patch(Rectangle((lx, ly), 330, 150, fc="w", ec="#777", zorder=9))
    ax.text(lx + 8, ly + 140, "LEGEND", fontsize=8, fontweight="bold", va="top", zorder=10)
    arrow(ax, (lx + 12, ly + 112), (lx + 60, ly + 112), "k", z=10); ax.text(lx + 70, ly + 112, "moving vehicle (direction of travel)", fontsize=6.5, va="center", zorder=10)
    arrow(ax, (lx + 12, ly + 92), (lx + 60, ly + 92), "k", stopped=True, z=10); ax.text(lx + 70, ly + 92, "stopped vehicle", fontsize=6.5, va="center", zorder=10)
    turn_arrow(ax, (lx + 12, ly + 60), (lx + 46, ly + 84), (1, 0), "k", z=10); ax.text(lx + 70, ly + 70, "turning vehicle", fontsize=6.5, va="center", zorder=10)
    ax.add_patch(Rectangle((lx + 31, ly + 38), 9, 9, fc="k", zorder=10)); ax.text(lx + 70, ly + 42, "fixed object struck", fontsize=6.5, va="center", zorder=10)
    ax.text(lx + 8, ly + 22, "Colour = severity:", fontsize=6.5, va="center", zorder=10)
    xx = lx + 100
    for s_ in ("K", "A", "B", "C", "PDO"):
        ax.text(xx, ly + 22, s_, fontsize=7.5, fontweight="bold", color=SEVC[s_], va="center", zorder=10); xx += 26
    ax.text(lx + 8, ly + 8, "Night = dark, not lighted.  Wet = wet road surface.", fontsize=5.8, va="center", zorder=10)
    # crash table
    tx = fig.add_axes([0.665, 0.02, 0.33, 0.90]); tx.set_axis_off()
    n_inj = sum(1 for c in crashes if severity(c) != "PDO"); n_front = sum(1 for c in crashes if c["Type"].startswith(("ANGLE", "LEFT", "RIGHT", "HEAD")))
    n_night = sum(1 for c in crashes if c["Light"] in ("4", "5", "6")); n_wet = sum(1 for c in crashes if c["RoadSurf"] == "2")
    hdr = (f"{len(crashes)} crashes: {n_inj} injury ({sum(int(c['A']) for c in crashes)} A, {sum(int(c['B']) for c in crashes)} B, {sum(int(c['C']) for c in crashes)} C injuries), "
           f"{len(crashes)-n_inj} PDO\nFrontal impact (angle / left turn / right turn): {n_front} ({100*n_front/len(crashes):.0f}%)   Night: {n_night}   Wet: {n_wet}\n"
           "Traffic control: STOP on SR 1103;  NC 180/NC 226 free-flow, 45 mph")
    tx.text(0, 1.0, hdr, fontsize=8, va="top")
    rows = [("No", "Crash ID", "Date", "Time", "Type", "Sev", "Cond")]
    short = {"LEFT TURN, DIFFERENT ROADWAYS": "Left turn, diff. rdwy", "LEFT TURN, SAME ROADWAY": "Left turn, same rdwy", "RIGHT TURN, SAME ROADWAY": "Right turn, same rdwy",
             "REAR END, SLOW OR STOP": "Rear end, slow/stop", "FIXED OBJECT": "Fixed object", "ANGLE": "Angle"}
    for c in crashes:
        cond = ("N" if c["Light"] in ("4", "5", "6") else "") + ("W" if c["RoadSurf"] == "2" else "")
        rows.append((c["No"], c["CrashID"], c["Date"], c["Time"], short.get(c["Type"], c["Type"].title()), severity(c), cond))
    tbl = tx.table(cellText=rows[1:], colLabels=rows[0], loc="upper left", bbox=[0, 0.0, 1, 0.85], colWidths=[0.07, 0.18, 0.17, 0.1, 0.3, 0.08, 0.08],
                   cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(7)
    for (r, cidx), cell in tbl.get_celld().items():
        cell.set_edgecolor("#bbb")
        if r == 0: cell.set_text_props(fontweight="bold"); cell.set_facecolor("#eeeeee")
        elif cidx == 5: cell.set_text_props(color=SEVC[rows[r][5]], fontweight="bold")
        if cidx == 4 and r > 0: cell.set_text_props(ha="left"); cell._loc = "left"
    tx.text(0, -0.006, "Cond: N = night, W = wet.  Source: TEAAS Intersection Analysis Report, study 41000079736 (22 crashes after fiche review).", fontsize=6, va="top")
    fig.suptitle(f"Collision Diagram  -  {TITLE}", fontsize=14, fontweight="bold", y=0.975)
    fig.text(0.5, 0.945, SUB, ha="center", fontsize=9.5)
    fig.savefig(OUT / "3_collision_diagram.png", dpi=150); pdf.savefig(fig); plt.close(fig)


# ----------------------------------------------------------------------------- 4. crash location map
def crash_location_map(pdf, crashes):
    coords = {}
    with open(HERE / "review" / "fiche_screened.csv", newline="") as f:
        for r in csv.DictReader(f):
            coords[r["Crash ID"]] = r
    im, to_px, mpp = basemap(ESRI_IMG, 18, 330, 260)
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.imshow(im); ax.set_axis_off()
    x, y = to_px(LAT, LON)
    ax.add_patch(Circle((x, y), 150 * 0.3048 / mpp, fill=False, ec="#ffd400", lw=2.2, ls="--", zorder=9))
    ax.text(x + 150 * 0.3048 / mpp + 6, y, "150 ft Y-line", color="#ffd400", fontsize=9, fontweight="bold", va="center", bbox=dict(fc="k", ec="none", alpha=0.45, pad=1.5))
    missing, pts = [], []
    for c in crashes:
        r = coords.get(c["CrashID"])
        if not r or not r["Latitude"] or not r["Longitude"]:
            missing.append(c); continue
        cx, cy = to_px(float(r["Latitude"]), float(r["Longitude"]))
        if not (0 <= cx < im.width and 0 <= cy < im.height):
            missing.append(c); c["_off"] = round(float(r["Dist_ft"])) if r["Dist_ft"] else None; continue
        pts.append((math.atan2(cy - y, cx - x), cx, cy, c))
    pts.sort(key=lambda p: p[0])
    R = 150 * 0.3048 / mpp + 70
    for i, (ang, cx, cy, c) in enumerate(pts):   # labels on a ring around the intersection, evenly spaced, in angular order
        a = -math.pi / 2 + 2 * math.pi * i / len(pts) + (pts[0][0] + math.pi / 2)
        lx, ly = x + R * math.cos(a), y + R * math.sin(a)
        sev = severity(c)
        ax.plot(cx, cy, "o", ms=10, color=SEVC[sev], mec="w", mew=1.2, zorder=10)
        ax.annotate(f"#{c['No']}", xy=(cx, cy), xytext=(lx, ly), fontsize=8, fontweight="bold", color="w", ha="center", va="center",
                    bbox=dict(fc=SEVC[sev], ec="w", lw=0.8, pad=1.8), arrowprops=dict(arrowstyle="-", color="w", lw=0.9, shrinkB=0), zorder=11)
    marker(ax, x, y, 12)
    txt = "Crash numbers follow the TEAAS report / collision diagram.  Colour = severity (" + ", ".join(f"{s}" for s in SEVC) + ")."
    if missing:
        txt += "\nNot plotted (no coordinates on the DMV-349 or outside this map): " + ", ".join(
            f"#{c['No']}" + (f" ({c['_off']:,} ft away as geocoded)" if c.get("_off") else "") for c in missing)
    ax.text(8, im.height - 8, txt, fontsize=7.5, va="bottom", ha="left", color="w", bbox=dict(fc="k", ec="none", alpha=0.55, pad=3), zorder=12, wrap=True)
    leg = [plt.Line2D([], [], marker="o", ls="", ms=9, color=SEVC[s], mec="w", label=s) for s in SEVC]
    ax.legend(handles=leg, loc="upper left", fontsize=8, title="Severity", title_fontsize=8, framealpha=0.9)
    scalebar(ax, mpp, im.width - 170, im.height - 40, 100 / 5280, "100 ft"); north(ax, im.width - 50, 70)
    fig.suptitle("Crash Location Map", fontsize=15, fontweight="bold", y=0.985)
    ax.set_title(f"{TITLE}\n{SUB}", fontsize=9.5, pad=6)
    fig.text(0.99, 0.01, "Imagery: Esri, Maxar, Earthstar Geographics  |  Crash coordinates: NCDOT DMV-349 geocodes via TEAAS detailed fiche", ha="right", fontsize=7, color="#444")
    fig.tight_layout(rect=(0, 0.015, 1, 0.97))
    fig.savefig(OUT / "4_crash_location_map.png", dpi=150); pdf.savefig(fig); plt.close(fig)


# ----------------------------------------------------------------------------- AADT
def aadt_calc(aadt):
    lines = ["Intersection entering AADT = (sum of the AADT on every leg) / 2", ""]
    latest, y2024 = 0, 0
    for leg in aadt["legs"]:
        yr = max(leg["aadt"]); latest += leg["aadt"][yr]
        y2024 += leg["aadt"].get("2024", leg["aadt"][yr])
        lines.append(f"  {leg['leg']:50} station {leg['station']}  AADT {yr}: {leg['aadt'][yr]:>6,}")
    lines += ["", f"  Sum of legs (latest year per station) = {latest:,}  ->  entering AADT = {latest/2:,.0f} vpd",
              f"  Sum of legs (2024 where published)    = {y2024:,}  ->  entering AADT = {y2024/2:,.0f} vpd"]
    return "\n".join(lines), latest / 2


def main():
    OUT.mkdir(exist_ok=True)
    aadt = json.loads((HERE / "aadt.json").read_text())
    crashes = []
    with open(HERE / "data" / f"{STUDY}_CrashAnalysis_22crashes.csv", newline="") as f:
        for r in csv.DictReader(f):
            r["units"] = [{"dir": r[f"U{i}_dir"], "mnvr": r[f"U{i}_mnvr"], "speed": r[f"U{i}_speed"], "obj": r.get(f"U{i}_obj", "")}
                          for i in (1, 2, 3) if r[f"U{i}_dir"]]
            crashes.append(r)
    with PdfPages(OUT / f"{STUDY}_maps.pdf") as pdf:
        location_map(pdf); area_map(pdf, aadt); collision_diagram(pdf, crashes); crash_location_map(pdf, crashes)
    text, ent = aadt_calc(aadt)
    (OUT / "aadt_calculation.txt").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
