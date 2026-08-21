"""Annotated aerial for the 10-18-223 (W-5710AM) one-page report.

Builds the image that fills the Map/Satellite Views box of the printed
1-pager: an Esri World Imagery mosaic (z17) around the SR 1001 / SR 1617
junction, an OSM street-map inset locating the site, and the four
approach callouts carrying the speed limits and the AADT figures from
the approved assumptions. The crop is sized to the box the print leaves
(measured per-print by safety_eval.report_pdf.measure_map_region, about
281 x 202 pt, aspect 1.39), so the image drops in without letterboxing.

AADT sources: SR 1001 north leg 2,100 vpd (2022 station), SR 1001 south
leg 3,500 vpd (2021 station), SR 1617 / SR 1619 1,400 vpd (2019
station, minor-road estimate rounded to the nearest hundred).
"""
import math
import os
import sys
import urllib.request

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, "/home/user/Etch-A-Sketch")

from safety_eval.crash_map import _UA, TILE_SOURCES  # noqa: E402

SP = ("/tmp/claude-0/-home-user-Etch-A-Sketch/"
      "4d83860a-51f4-5f7b-a60e-765168dfbb13/scratchpad/aerial")
os.makedirs(SP, exist_ok=True)

#: The approved junction point (assignment email).
LAT, LON = 35.081578, -80.500362
Z = 17                       # aerial zoom
COLS, ROWS = 3, 6            # tile mosaic footprint (768 x 1536 px)
CROP_TOP, CROP_H = 763, 550  # window matching the printed box's aspect

F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

#: (cx, cy) in the cropped image; text is the engineer's callout block.
CALLOUTS = [
    ((600, 58), ["SR 1001 (Sikes Mill Road)", "55 mph",
                 "AADT (Year)", "2,100 vpd (2022)"]),
    ((330, 172), ["SR 1617 (Tom Boyd Road)", "45 mph",
                  "AADT (Year)", "1,400 vpd (2019)"]),
    ((615, 395), ["SR 1619 (Tom Boyd Road)", "45 mph",
                  "AADT (Year)", "1,400 vpd (2019)"]),
    ((190, 480), ["SR 1001 (Sikes Mill Road)", "55 mph",
                  "AADT (Year)", "3,500 vpd (2021)"]),
]
NORTH_ARROW = (732, 470)
ATTRIBUTION_Y = 528          # "Esri World Imagery", bottom left


def tilexy(lat, lon, z):
    n = 2 ** z
    return ((lon + 180) / 360 * n,
            (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def fetch(url, out):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as fh:
        blob = fh.read()
    with open(out, "wb") as fh:
        fh.write(blob)


def build_mosaic():
    fx, fy = tilexy(LAT, LON, Z)
    x0, y0 = int(fx) - COLS // 2, int(fy) - ROWS // 2 - 1
    mosaic = Image.new("RGB", (COLS * 256, ROWS * 256))
    for dx in range(COLS):
        for dy in range(ROWS):
            fetch(TILE_SOURCES["a"].format(z=Z, x=x0 + dx, y=y0 + dy),
                  f"{SP}/tt.jpg")
            mosaic.paste(Image.open(f"{SP}/tt.jpg"), (dx * 256, dy * 256))
    print("mosaic", mosaic.size,
          "junction at", int((fx - x0) * 256), int((fy - y0) * 256))
    mosaic.save(f"{SP}/mosaic.png")
    return mosaic


def build_inset():
    fx, fy = tilexy(LAT, LON, 13)
    fetch(TILE_SOURCES["s"].format(z=13, x=int(fx), y=int(fy)),
          f"{SP}/osm.png")
    osm = Image.open(f"{SP}/osm.png").convert("RGB")
    px, py = int((fx % 1) * 256), int((fy % 1) * 256)
    lft = max(0, min(256 - 150, px - 75))
    top = max(0, min(256 - 110, py - 55))
    inset = osm.crop((lft, top, lft + 150, top + 110)).resize((210, 154))
    d = ImageDraw.Draw(inset)
    d.ellipse([100, 70, 114, 84], outline="red", width=3)
    inset.save(f"{SP}/inset.png")
    return inset


def annotate(mosaic, inset):
    img = mosaic.crop((0, CROP_TOP, 768, CROP_TOP + CROP_H))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(F, 14)

    def callout(cx, cy, lines):
        widths = [d.textlength(t, font=f) for t in lines]
        w = int(max(widths)) + 14
        h = 18 * len(lines) + 8
        x0, y0 = int(cx - w / 2), int(cy - h / 2)
        d.rectangle([x0, y0, x0 + w, y0 + h], fill="white",
                    outline="black", width=2)
        for i, t in enumerate(lines):
            d.text((cx - widths[i] / 2, y0 + 5 + 18 * i), t, font=f,
                   fill="black")

    for (cx, cy), lines in CALLOUTS:
        callout(cx, cy, lines)

    ax, ay = NORTH_ARROW
    d.polygon([(ax, ay - 24), (ax - 8, ay + 5), (ax, ay - 2),
               (ax + 8, ay + 5)], fill="white", outline="black")
    d.text((ax - 6, ay + 7), "N", font=ImageFont.truetype(FB, 15),
           fill="white", stroke_width=2, stroke_fill="black")
    d.text((8, ATTRIBUTION_Y), "Esri World Imagery",
           font=ImageFont.truetype(F, 12),
           fill="white", stroke_width=2, stroke_fill="black")

    small = inset.resize((160, 118))
    img.paste(small, (6, 6))
    d.rectangle([6, 6, 166, 124], outline="black", width=2)
    img.save(f"{SP}/annotated.png")
    print("annotated", img.size, "->", f"{SP}/annotated.png")


if __name__ == "__main__":
    annotate(build_mosaic(), build_inset())
