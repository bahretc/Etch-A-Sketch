"""Location check: report coordinates and property addresses against the
coded milepost (docs/03).

TEAAS mileposts a crash from the officer's distance and direction to a
reference road, and on 260307016EA that put nine of 22 crashes in the wrong
place, some by half a mile. Two other things on the DMV-349 pin the spot
better: the report's own latitude and longitude, and any property address
in the narrative or property damage block (a mailbox, a yard, a driveway,
a school bus stop). This module

* geocodes addresses with the Census Bureau geocoder (public, no key),
* snaps coordinates and geocoded points to the route centerline
  (``route_geometry.Centerline.snap``), and
* compares the resulting milepost with the coded one so the engineer can
  decide RE / ADD / NIS with the evidence laid out.

Nothing here changes a determination; it writes a report.
"""
from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

CENSUS_URL = ("https://geocoding.geo.census.gov/geocoder/locations/"
              "onelineaddress")
_UA = {"User-Agent": "safety-eval location-check"}


@dataclass
class GeocodeHit:
    address: str
    lat: float | None
    lon: float | None
    matched: str = ""


def geocode(address: str, timeout: int = 60) -> GeocodeHit:
    """One-line address -> WGS84 point from the Census geocoder."""
    qs = urllib.parse.urlencode({"address": address,
                                 "benchmark": "Public_AR_Current",
                                 "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(
            f"{CENSUS_URL}?{qs}", headers=_UA), timeout=timeout) as fh:
        payload = json.loads(fh.read().decode("utf-8"))
    matches = payload.get("result", {}).get("addressMatches", [])
    if not matches:
        return GeocodeHit(address, None, None)
    c = matches[0]["coordinates"]
    return GeocodeHit(address, float(c["y"]), float(c["x"]),
                      matches[0].get("matchedAddress", ""))


@dataclass
class LocationRow:
    crash_id: str
    coded_mp: float | None
    coord_mp: float | None
    offset_ft: int | None
    address: str = ""
    address_mp: float | None = None
    note: str = ""

    @property
    def differs(self) -> bool:
        """The coordinate milepost is more than the tolerance from the coded
        one (set by :func:`check_crashes`)."""
        return self.note.startswith("differs")


def read_detailed_fiche(path: str) -> list[dict]:
    """Rows of the Detailed Fiche CSV as dicts (header row detected)."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    for i, r in enumerate(rows):
        if r and r[0].strip().lower() == "municipality":
            header = [c.strip() for c in r]
            return [dict(zip(header, x)) for x in rows[i + 1:] if len(x) >= 10]
    raise ValueError("Detailed Fiche header row not found")


def check_crashes(detailed_rows: list[dict], crash_ids, centerline,
                  tolerance_mi: float = 0.05,
                  max_offset_ft: int = 150) -> list[LocationRow]:
    """Coded milepost vs the milepost of the report coordinates.

    Rows without coordinates say so; a coordinate more than
    ``max_offset_ft`` off the centerline is reported but not trusted
    (the crash may be on a cross street, or the point is a slip estimate).
    """
    want = {str(c) for c in crash_ids}
    out = []
    for r in detailed_rows:
        cid = str(r.get("Crash ID", "")).strip()
        if cid not in want:
            continue
        try:
            coded = float(r.get("MP", ""))
        except ValueError:
            coded = None
        if coded is not None and coded >= 999:
            coded = None
        try:
            lat, lon = float(r["Latitude"]), float(r["Longitude"])
        except (KeyError, ValueError):
            out.append(LocationRow(cid, coded, None, None,
                                   note="no coordinates on the record"))
            continue
        mp, off = centerline.snap(lat, lon)
        if off > max_offset_ft:
            note = f"coordinates {off} ft off the route; not used"
        elif coded is None:
            note = "not mileposted; coordinates give the milepost"
        elif abs(coded - mp) > tolerance_mi:
            note = f"differs by {abs(coded - mp):.3f} mi"
        else:
            note = "agrees"
        out.append(LocationRow(cid, coded, mp, off, note=note))
    return out


def check_addresses(addresses: list[tuple[str, str]], centerline,
                    geocoder=geocode) -> list[LocationRow]:
    """``[(crash_id, address), ...]`` -> milepost of each geocoded address."""
    out = []
    for cid, addr in addresses:
        hit = geocoder(addr)
        if hit.lat is None:
            out.append(LocationRow(str(cid), None, None, None, address=addr,
                                   note="no geocoder match"))
            continue
        mp, off = centerline.snap(hit.lat, hit.lon)
        out.append(LocationRow(str(cid), None, None, off, address=addr,
                               address_mp=mp, note=hit.matched))
    return out


def report_markdown(coord_rows: list[LocationRow],
                    address_rows: list[LocationRow] | None = None) -> str:
    lines = ["| Crash | Coded MP | Coordinate MP | Offset | Note |",
             "|---|---|---|---|---|"]
    for r in coord_rows:
        lines.append(
            f"| {r.crash_id} | {'' if r.coded_mp is None else f'{r.coded_mp:.3f}'} "
            f"| {'' if r.coord_mp is None else f'{r.coord_mp:.3f}'} "
            f"| {'' if r.offset_ft is None else f'{r.offset_ft} ft'} | {r.note} |")
    if address_rows:
        lines += ["", "| Crash | Address | Address MP | Offset | Match |",
                  "|---|---|---|---|---|"]
        for r in address_rows:
            lines.append(
                f"| {r.crash_id} | {r.address} "
                f"| {'' if r.address_mp is None else f'{r.address_mp:.3f}'} "
                f"| {'' if r.offset_ft is None else f'{r.offset_ft} ft'} "
                f"| {r.note} |")
    return "\n".join(lines)


def write_csv(path: str, rows: list[LocationRow]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["crash_id", "coded_mp", "coord_mp", "offset_ft",
                    "address", "address_mp", "note"])
        for r in rows:
            w.writerow([r.crash_id, r.coded_mp, r.coord_mp, r.offset_ft,
                        r.address, r.address_mp, r.note])


def parse_address_list(path: str) -> list[tuple[str, str]]:
    """``<crash id>|<address>`` lines (``#`` comments ignored)."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            cid, addr = line.split("|", 1)
            out.append((cid.strip(), addr.strip()))
    return out
