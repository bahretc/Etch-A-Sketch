import json, math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

BASE = '/tmp/claude-0/-home-user-Etch-A-Sketch/4e077ce8-b4e0-5cdc-9d6d-9c8dc9ebd0c5/scratchpad/'
seg = json.load(open(BASE + 'dl/q_NCDOT_2025_AADTandTrafficSegments_gdb_0.json'))
LAT0, LON0 = 35.657816, -78.717261          # study intersection (signal 05-1723)
FT_LAT = 364000.0
FT_LON = 364000.0 * math.cos(math.radians(LAT0))
def xy(lon, lat): return ((lon - LON0) * FT_LON, (lat - LAT0) * FT_LAT)

NAMES = {'40001375092': 'SR 1375 (Lake Wheeler Rd)', '40001390092': 'SR 1390 (Optimist Farm Rd)',
         '40001503092': 'SR 1503 (Donny Brook Rd)', '40001392092': 'SR 1392 (Ransdell Rd)',
         '40001404092': 'SR 1404 (Johnson Pond Rd)', '20000401092': 'US 401 (Fayetteville Rd)',
         '40001010092': 'SR 1010 (Ten Ten Rd)'}
fig = plt.figure(figsize=(11.4, 10.0), dpi=150)
ax = fig.add_axes([0.0, 0.0, 1.0, 1.0]); ax.set_facecolor('#f4f4f4'); fig.patch.set_facecolor('#f4f4f4')
routes = {}
for f in seg['features']:
    rid = f['attributes']['RouteID']
    for path in f['geometry']['paths']:
        pts = [xy(lon, lat) for lon, lat in path]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color='#9a9a9a', lw=5, solid_capstyle='round', zorder=1)
        routes.setdefault(rid, []).extend(pts)
# NC 540 (not a segment in this layer): approximate crossing of SR 1375 ~0.3 mi north (per NCDOT ITS CCTV location 35.6617,-78.7158)
x540, y540 = xy(-78.7158, 35.6617)
ax.plot([x540 - 6000, x540 + 6000], [y540 + 1500, y540 - 1500], color='#c9c9c9', lw=9, zorder=0, ls='--')
ax.text(x540 + 1900, y540 - 420, 'NC 540 (opened 9/2024)', fontsize=9, color='#777', rotation=-14, ha='center', va='top', zorder=2)

def label_route(rid, text, frac=0.5, dy=130, fontsize=10, color='#444', pick=None):
    pts = routes.get(rid)
    if not pts: return
    pts = sorted(pts, key=lambda p: p[0]) if pick is None else pick(pts)
    i = int(len(pts) * frac); i = max(1, min(len(pts) - 2, i))
    (x1, y1), (x2, y2) = pts[i - 1], pts[i + 1]
    ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
    if ang > 90: ang -= 180
    if ang < -90: ang += 180
    ax.text(pts[i][0], pts[i][1] + dy, text, fontsize=fontsize, color=color, rotation=ang, ha='center', va='bottom', zorder=3)

# Lake Wheeler: sort by y (north-south road)
label_route('40001375092', 'SR 1375 (Lake Wheeler Rd)', frac=0.86, dy=0, pick=lambda p: sorted(p, key=lambda q: q[1]))
label_route('40001375092', 'SR 1375 (Lake Wheeler Rd)', frac=0.22, dy=0, pick=lambda p: sorted(p, key=lambda q: q[1]))
label_route('40001390092', 'SR 1390 (Optimist Farm Rd)', frac=0.45, dy=150)
label_route('40001503092', 'SR 1503 (Donny Brook Rd)', frac=0.32, dy=150)
label_route('40001392092', 'SR 1392 (Ransdell Rd)', frac=0.5, dy=0, pick=lambda p: sorted(p, key=lambda q: q[1]))
label_route('40001404092', 'SR 1404 (Johnson Pond Rd)', frac=0.5, dy=0, pick=lambda p: sorted(p, key=lambda q: q[1]))
label_route('20000401092', 'US 401 (Fayetteville Rd)', frac=0.5, dy=0, pick=lambda p: sorted(p, key=lambda q: q[1]))

stations = [
    ('Leg #1 (North): 0920000868\nSR 1375 N of SR 1390\n2025 AADT 8,900', -78.716963, 35.661593, '#7030a0', (-4400, 1950)),
    ('Leg #2 (South): 0920000991\nSR 1375 S of SR 1503\n2025 AADT 7,400', -78.719543, 35.652661, '#0070c0', (-4300, -1000)),
    ('Leg #3 (West): 0920001913\nSR 1390 W of SR 1404 (Johnson Pond Rd)\n2025 AADT 4,800 (~1 mi west of intersection)', -78.734516, 35.659047, '#00b050', (900, 1450)),
    ('Leg #4 (East): 0920001914\nSR 1503 E of SR 1392 (Ransdell Rd)\n2025 AADT 2,400', -78.714671, 35.657057, '#ff0000', (-900, -3650)),
]
for text, lon, lat, col, (dx, dy) in stations:
    x, y = xy(lon, lat)
    ax.plot(x, y, 'o', ms=15, mfc=col, mec='white', mew=2, zorder=5)
    ax.annotate(text, xy=(x, y), xytext=(x + dx, y + dy), fontsize=10, ha='left', va='center', zorder=6,
                bbox=dict(boxstyle='round,pad=0.4', fc='white', ec=col, lw=2),
                arrowprops=dict(arrowstyle='-', color='#333', lw=1, shrinkB=8))
ax.plot(0, 0, 'o', ms=16, mfc='white', mec='black', mew=3, zorder=7)
ax.annotate('Study intersection\n(SR 1375 MP 4.70, signal 05-1723)', xy=(0, 0), xytext=(-3700, 700), fontsize=10, ha='left', va='center', zorder=7,
            arrowprops=dict(arrowstyle='-', color='#333', lw=1, shrinkB=9))
# extent (aspect 1.14)
W = 11200; H = W / 1.14
cx, cy = -2300, 100
ax.set_xlim(cx - W / 2, cx + W / 2); ax.set_ylim(cy - H / 2, cy + H / 2); ax.set_aspect('equal'); ax.axis('off')
# title
ax.text(0.015, 0.975, 'AADT count stations used: SR 1375 (Lake Wheeler Rd) at SR 1390 (Optimist Farm Rd)/SR 1503 (Donny Brook Rd)',
        transform=ax.transAxes, fontsize=13, fontweight='bold', va='top')
ax.text(0.015, 0.945, 'NCDOT 2025 AADT Stations and Traffic Segments (state roads shown). Unincorporated Wake County near Fuquay-Varina; W-5601HP (05-08-203).',
        transform=ax.transAxes, fontsize=10, color='#555', va='top')
# north arrow & scale bar
ax.annotate('', xy=(0.955, 0.93), xytext=(0.955, 0.86), xycoords='axes fraction', arrowprops=dict(arrowstyle='-|>', color='black', lw=2))
ax.text(0.955, 0.94, 'N', transform=ax.transAxes, ha='center', fontsize=13, fontweight='bold')
x0 = cx - W / 2 + 500; y0 = cy - H / 2 + 450
for i, ft in enumerate([0, 1000, 2000]):
    ax.text(x0 + ft, y0 + 170, f'{ft:,}' + (' ft' if ft == 2000 else ''), fontsize=10, ha='center')
ax.plot([x0, x0 + 2000], [y0, y0], color='black', lw=2)
for ft in (0, 1000, 2000): ax.plot([x0 + ft, x0 + ft], [y0 - 90, y0 + 90], color='black', lw=2)
fig.savefig(BASE + 'out/aadt_station_map_05-08-203.png', dpi=150, facecolor=fig.get_facecolor())
print('saved')
