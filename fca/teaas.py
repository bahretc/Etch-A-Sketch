"""Parsers for TEAAS (Traffic Engineering Accident Analysis System) exports."""
from __future__ import annotations

import csv
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

CRASH_ID_RE = re.compile(r"^\d{9}$")

FICHE_COLS = ["muni_code", "on_road", "miles", "dir", "from_road", "toward_road",
              "mp_road", "mp", "ma", "crash_id", "date", "T", "C", "F", "L", "S"]


def _num(s: str, default=None):
    s = (s or "").strip()
    if s == "":
        return default
    try:
        return int(s) if re.fullmatch(r"-?\d+", s) else float(s)
    except ValueError:
        return default


@dataclass
class FicheRow:
    muni_code: str
    on_road: str
    miles: float | None
    dir: str
    from_road: str
    toward_road: str
    mp_road: str
    mp: float | None
    ma: str
    crash_id: int
    date: str          # YYYY-MM-DD
    T: int | None
    C: int | None
    F: int | None
    L: int | None
    S: str
    order: int = 0     # position in the fiche report

    @property
    def unmileposted(self) -> bool:
        return self.mp is None or abs(self.mp - 999.999) < 1e-6

    @property
    def date_dt(self) -> datetime | None:
        try:
            return datetime.strptime(self.date, "%Y-%m-%d")
        except ValueError:
            return None


@dataclass
class FicheReport:
    rows: list[FicheRow]
    county: str = ""
    county_code: str = ""
    division: str = ""
    municipality: str = ""
    begin_date: str = ""
    end_date: str = ""
    years: str = ""
    roads: list[tuple[str, str]] = field(default_factory=list)   # (name, code)

    def by_id(self) -> dict[int, FicheRow]:
        return {r.crash_id: r for r in self.rows}


def parse_fiche(path: str) -> FicheReport:
    """Parse the TEAAS Fiche Report CSV export (page-oriented, repeated headers)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        raw = list(csv.reader(f))
    rep = FicheReport(rows=[])
    i = 0
    seen_crit = False
    while i < len(raw):
        r = raw[i]
        if not seen_crit and len(r) >= 9 and r[0].startswith("County") and "County Code" in r[1]:
            v = raw[i + 1]
            rep.county, rep.county_code, rep.division, rep.municipality = v[1], v[2], v[3], v[4]
            rep.begin_date, rep.end_date, rep.years = v[6], v[7], v[8]
            seen_crit = True
            i += 2
            continue
        if not rep.roads and len(r) == 2 and r[0] == "Road Name" and r[1] == "Road Code":
            j = i + 1
            while j < len(raw) and len(raw[j]) == 2 and not raw[j][0].startswith("Muni"):
                if re.fullmatch(r"\d{8}", raw[j][1] or ""):
                    rep.roads.append((raw[j][0].strip(), raw[j][1].strip()))
                j += 1
            i = j
            continue
        if len(r) == 16 and CRASH_ID_RE.match(r[9] or ""):
            rep.rows.append(FicheRow(
                muni_code=r[0].strip(), on_road=r[1].strip(), miles=_num(r[2]), dir=r[3].strip(),
                from_road=r[4].strip(), toward_road=r[5].strip(), mp_road=r[6].strip(),
                mp=_num(r[7]), ma=r[8].strip(), crash_id=int(r[9]), date=r[10].strip(),
                T=_num(r[11]), C=_num(r[12]), F=_num(r[13]), L=_num(r[14]), S=r[15].strip(),
                order=len(rep.rows)))
        i += 1
    return rep


@dataclass
class DetailedRow:
    municipality: str
    on_road: str
    miles: float | None
    dir: str
    from_road: str
    toward_road: str
    mp_road: str
    mp: float | None
    ma: str
    crash_id: int
    date: str
    T: int | None
    C: int | None
    F: int | None
    L: int | None
    S: str
    lat: float | None
    lon: float | None
    source: str
    raw: list[str]

    @property
    def latlon(self) -> tuple[float, float] | None:
        if self.lat is None or self.lon is None:
            return None
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            return None
        return (self.lat, self.lon)


def parse_detailed_fiche(path: str) -> tuple[list[str], dict[int, DetailedRow]]:
    """Parse the Detailed Fiche CSV (one row per crash, with coordinates). Returns (header, {id: row})."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.reader(f)
        header = next(rd)
        out: dict[int, DetailedRow] = {}
        for r in rd:
            if len(r) < 19 or not CRASH_ID_RE.match(r[9] or ""):
                continue
            out[int(r[9])] = DetailedRow(
                municipality=r[0].strip(), on_road=r[1].strip(), miles=_num(r[2]), dir=r[3].strip(),
                from_road=r[4].strip(), toward_road=r[5].strip(), mp_road=r[6].strip(), mp=_num(r[7]),
                ma=r[8].strip(), crash_id=int(r[9]), date=r[10].strip(), T=_num(r[11]), C=_num(r[12]),
                F=_num(r[13]), L=_num(r[14]), S=r[15].strip(), lat=_num(r[16]), lon=_num(r[17]),
                source=r[18].strip(), raw=r)
    return header, out


@dataclass
class StripUnit:
    unit: int
    veh_type: int | None
    alcohol: int | None
    speed: int | None
    dir: str
    maneuver: int | None
    obj_struck: str


@dataclass
class StripCrash:
    acc_no: int
    crash_id: int
    mp: float | None
    date: str
    acc_type: str
    damage: int | None
    K: int | None
    A: int | None
    B: int | None
    C: int | None
    road_surface: str
    light: str
    weather: str
    road_char: str
    road_circ: str
    tc_device: str
    tc_oper: str
    units: list[StripUnit] = field(default_factory=list)

    @property
    def severity(self) -> str:
        if (self.K or 0) > 0:
            return "K"
        if (self.A or 0) > 0:
            return "A"
        if (self.B or 0) > 0:
            return "B"
        if (self.C or 0) > 0:
            return "C"
        return "O"


@dataclass
class StripReport:
    raw: list[list[str]]
    crashes: list[StripCrash]
    kind: str = ""          # "Strip Analysis Report" or "Intersection Analysis Report"
    county: str = ""
    city: str = ""
    begin_date: str = ""
    end_date: str = ""
    study: str = ""
    location: str = ""
    summary: dict = field(default_factory=dict)   # label -> list of values

    def ids(self) -> list[int]:
        return [c.crash_id for c in self.crashes]


def parse_strip(path: str) -> StripReport:
    """Parse the TEAAS Strip (or Intersection) Analysis Report CSV export."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        raw = list(csv.reader(f))
    rep = StripReport(raw=raw, crashes=[])
    is_strip = "Strip" in " ".join(raw[0]) if raw else False
    rep.kind = "Strip Analysis Report" if is_strip else "Intersection Analysis Report"
    cur = None
    for r in raw:
        if not r:
            continue
        if r[0] == "County:" and len(r) >= 4:
            rep.county, rep.city = r[1], r[3]
        elif r[0] == "Date:" and len(r) >= 6:
            rep.begin_date, rep.end_date, rep.study = r[1], r[3], r[5]
        elif r[0] == "Location:" and len(r) >= 2:
            rep.location = r[1]
        elif r[0] == "Unit" and cur is not None and len(r) >= 14:
            cur.units.append(StripUnit(unit=_num(r[1]), veh_type=_num(r[3]), alcohol=_num(r[5]),
                                       speed=_num(r[7]), dir=r[10].strip(), maneuver=_num(r[12]),
                                       obj_struck=(r[14].strip() if len(r) > 14 else "")))
        elif re.fullmatch(r"\d+", r[0] or "") and len(r) >= 12 and CRASH_ID_RE.match(r[1] or ""):
            if is_strip:
                # Acc No, Crash ID, Milepost, Date, Type, $, Damage, F, A, B, C, R, L, W, Ch, Ci, Dv, Op
                vals = r
                mp = _num(vals[2]); off = 1
            else:
                vals = r
                mp = None; off = 0
            cur = StripCrash(
                acc_no=int(vals[0]), crash_id=int(vals[1]), mp=mp, date=vals[2 + off].strip(),
                acc_type=vals[3 + off].strip(), damage=_num(vals[5 + off]),
                K=_num(vals[6 + off]), A=_num(vals[7 + off]), B=_num(vals[8 + off]), C=_num(vals[9 + off]),
                road_surface=vals[10 + off] if len(vals) > 10 + off else "",
                light=vals[11 + off] if len(vals) > 11 + off else "",
                weather=vals[12 + off] if len(vals) > 12 + off else "",
                road_char=vals[13 + off] if len(vals) > 13 + off else "",
                road_circ=vals[14 + off] if len(vals) > 14 + off else "",
                tc_device=vals[15 + off] if len(vals) > 15 + off else "",
                tc_oper=vals[16 + off] if len(vals) > 16 + off else "")
            rep.crashes.append(cur)
        elif len(r) >= 2 and r[0] in ("Annual ADT =", "Total Length =", "Total Crash Rate", "Fatal Crash Rate",
                                       "Severity Index =", "EPDO Crash Index =", "Total Vehicle Exposure ="):
            rep.summary[r[0].rstrip(" =")] = r[1:]
    return rep


@dataclass
class IdRow:
    crash_id: int
    on_rd_cd: str
    severity: int | None
    date: str
    type_code: int | None


def parse_initial_ids(path: str) -> list[IdRow]:
    """Parse the TEAAS crash ID export (pipe-delimited: CRASH ID|ON RD CD|SVRTY|DATE|TYPE|)."""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            parts = [p.strip() for p in line.strip().split("|")]
            if len(parts) >= 5 and CRASH_ID_RE.match(parts[0]):
                out.append(IdRow(int(parts[0]), parts[1], _num(parts[2]), parts[3], _num(parts[4])))
    return out


@dataclass
class Feature:
    mp: float
    feature_id: str
    name: str
    kind: str
    distance_to_next: float | None
    direction: str
    beyond: bool


def parse_features_pdf(path: str) -> tuple[dict, list[Feature]]:
    """Parse a TEAAS Features Report PDF with pdftotext -layout."""
    text = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout
    header = {}
    feats: list[Feature] = []
    line_re = re.compile(r"^\s*(\d+\.\d{3})\s+(\S+)\s+(.*?)\s{2,}(.*)$")
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z ]+?)\s+(\d{8})\s+(\d+\.\d+)\s+(\d+\.\d+)\s*$", line)
        if m and not header:
            header = {"county": m.group(1).strip(), "route_id": m.group(2),
                      "begin_mp": float(m.group(3)), "end_mp": float(m.group(4))}
            continue
        m = line_re.match(line)
        if not m:
            continue
        mp, fid, name, rest = m.groups()
        kind = ""
        km = re.search(r"(At grade intersection,\s+\d legs|Grade separation, no ramps|Bridge)", rest)
        if km:
            kind = re.sub(r"\s+", " ", km.group(1))
        dm = re.search(r"(\d+\.\d{3})\s+(South and East|North and East|North and West|South and West)?\s*(Y)?\s*$", rest)
        dist = float(dm.group(1)) if dm else None
        direction = dm.group(2) or "" if dm else ""
        beyond = bool(dm and dm.group(3))
        feats.append(Feature(float(mp), fid, name.strip(), kind, dist, direction, beyond))
    return header, feats


# ----------------------------------------------------------- crash type index

TYPE_INDEX = [
    (0, "unknown"), (1, "ROR-R"), (2, "ROR-L"), (3, "ROR-T"), (4, "jackknife"), (5, "overturn"),
    (13, "other"), (14, "pedestrian"), (15, "cyclist"), (16, "RR"), (17, "animal"), (18, "MO"),
    (19, "FO"), (20, "PMV"), (21, "RE"), (22, "RE-T"), (23, "LTSR"), (24, "LTDR"), (25, "RTSR"),
    (26, "RTDR"), (27, "head-on"), (28, "SSSD"), (29, "SSOD"), (30, "angle"), (31, "backing"), (32, "other"),
]
TYPE_NAMES = {k: v for k, v in TYPE_INDEX}

TYPE_LONG = {
    0: "Unknown", 1: "Ran off road - right", 2: "Ran off road - left", 3: "Ran off road - straight",
    4: "Jackknife", 5: "Overturn/rollover", 13: "Other non-collision", 14: "Pedestrian", 15: "Pedalcyclist",
    16: "Railroad train", 17: "Animal", 18: "Movable object", 19: "Fixed object", 20: "Parked motor vehicle",
    21: "Rear end, slow or stop", 22: "Rear end, turn", 23: "Left turn, same roadway",
    24: "Left turn, different roadways", 25: "Right turn, same roadway", 26: "Right turn, different roadways",
    27: "Head on", 28: "Sideswipe, same direction", 29: "Sideswipe, opposite direction", 30: "Angle",
    31: "Backing up", 32: "Other collision with vehicle",
}
SEVERITY_LONG = {"K": "Fatal (K)", "A": "Class A injury", "B": "Class B injury", "C": "Class C injury",
                 "O": "Property damage only", "": "Unknown"}
LIGHT = {1: "daylight", 2: "dusk", 3: "dawn", 4: "dark, lighted", 5: "dark, not lighted", 6: "dark, unknown lighting"}
