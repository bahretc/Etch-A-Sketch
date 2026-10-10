"""Screen a TEAAS fiche against the study limits.

Every fiche crash gets a flag:
  IS   in the initial (TEAAS) study and nothing about its coding looks wrong
  IS?  in the initial study but the coding or coordinates need checking in the report
  ?    not in the initial study, but one or more triggers say it may belong in the section
  NIS  not in the initial study and nothing points at the section

Triggers (mirroring the TSU working vocabulary):
  In study    crash ID is in the TEAAS ID export
  IS-verify   IS crash whose milepost / coordinates do not agree with the section
  Window      mileposted on the study route within window_mi outside the limits
  Between     the description (from road, toward road, miles) implies a milepost inside
              the limits, or just outside them, regardless of the coded MP
  DMV         Detailed Fiche coordinates project onto the route inside the limits
  Combo       MP 999.999 crash coded with section road names / intersection roads on the route
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .geo import FT_PER_MILE, Polyline, dist_ft
from .teaas import (DetailedRow, FicheRow, Feature, TYPE_NAMES, parse_detailed_fiche, parse_features_pdf,
                    parse_fiche, parse_initial_ids, parse_strip)


@dataclass
class Study:
    cfg: dict
    root: str
    fiche: object
    detailed: dict[int, DetailedRow]
    detailed_header: list[str]
    strip: object
    initial_ids: list
    features: list[Feature]
    features_header: dict
    centerline: Polyline

    @property
    def study_id(self) -> str:
        return self.cfg["study_id"]

    @property
    def begin_mp(self) -> float:
        return self.cfg["limits"]["begin_mp"]

    @property
    def end_mp(self) -> float:
        return self.cfg["limits"]["end_mp"]

    @property
    def route_name(self) -> str:
        return self.cfg["route"]["name"]

    def path(self, key: str) -> str:
        return os.path.join(self.root, self.cfg["inputs"][key])


def load_study(root: str) -> Study:
    with open(os.path.join(root, "study.json")) as f:
        cfg = json.load(f)
    inputs = cfg["inputs"]
    p = lambda k: os.path.join(root, inputs[k])
    fiche = parse_fiche(p("fiche"))
    header, detailed = parse_detailed_fiche(p("detailed_fiche"))
    strip = parse_strip(p("strip"))
    ids = parse_initial_ids(p("initial_ids"))
    fh, feats = parse_features_pdf(p("features_pdf")) if inputs.get("features_pdf") else ({}, [])
    return Study(cfg=cfg, root=root, fiche=fiche, detailed=detailed, detailed_header=header, strip=strip,
                 initial_ids=ids, features=feats, features_header=fh,
                 centerline=Polyline([tuple(x) for x in cfg["centerline"]]))


# ------------------------------------------------------------------ results

@dataclass
class Screened:
    row: FicheRow
    flag: str                      # IS / IS? / ? / NIS
    triggers: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    in_initial: bool = False
    implied_mp: float | None = None      # from the description
    dmv_mp: float | None = None          # from coordinates projected on the route
    dmv_offset_ft: float | None = None
    latlon: tuple[float, float] | None = None
    priority: int = 99                   # lower = review first
    priority_label: str = ""
    comment: str = ""                    # for the fiche sheet Comment column

    @property
    def trigger(self) -> str:
        return "+".join(self.triggers)

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


def _route_feature_mps(study: Study) -> dict[str, float]:
    """Feature name -> milepost on the study route, with the study's revised mileposts applied."""
    mps: dict[str, float] = {}
    for f in study.features:
        if f.name not in mps and f.kind.startswith("At grade"):
            mps[f.name] = f.mp
    mps.update(study.cfg.get("revised_mps", {}))
    for f in study.cfg.get("features", []):
        for n in f.get("fiche_names", []):
            mps.setdefault(n, f["mp"])
    return mps


def _fmt_mp(mp: float) -> str:
    return f"{mp:.3f}"


def _ft(mi: float) -> str:
    return f"{abs(mi) * FT_PER_MILE:,.0f} ft"


def screen(study: Study) -> list[Screened]:
    cfg = study.cfg
    sc = cfg["screen"]
    begin, end = study.begin_mp, study.end_mp
    window = sc.get("window_mi", 0.1)
    route = cfg["route"]["name"]
    aliases = set(cfg["route"].get("fiche_aliases", [route]))
    local_munis = set(sc.get("local_muni_codes", []))
    keywords = [k.upper() for k in sc.get("section_keywords", [])]
    int_names = set(sc.get("intersection_names", []))
    other_on = set(sc.get("other_on_roads_to_test", []))
    initial = {r.crash_id for r in study.initial_ids}
    feature_mps = _route_feature_mps(study)
    # roads that meet the study route but are not themselves at the MP-0 intersection,
    # so a crash "toward" one of them is travelling along the study route
    route_end = study.features_header.get("end_mp", max(feature_mps.values()) if feature_mps else 0.0)
    # names seen as from/toward on crashes mileposted on another route are shared with that route
    shared = set()
    for rr in study.fiche.rows:
        if rr.on_road in other_on and rr.mp_road == rr.on_road and rr.mp is not None and not rr.unmileposted:
            shared.update({rr.from_road, rr.toward_road})
    terminal = {n for n, mp in feature_mps.items() if mp <= 0.0 or mp >= route_end - 1e-6} | int_names
    weak_names = (set(sc.get("weak_route_names", [])) | (shared & set(feature_mps))) - terminal
    route_only = {n for n, mp in feature_mps.items()
                  if 0.0 < mp < route_end - 1e-6 and n not in int_names and n not in weak_names}
    route_only |= {route}
    limit_tol = sc.get("limit_tol_mi", 0.005)
    begin_desc = cfg["limits"].get("begin_desc", "begin limit")
    end_desc = cfg["limits"].get("end_desc", "end limit")
    pl = study.centerline
    dmv_pad = sc.get("dmv_mp_pad", 0.02)
    dmv_off = sc.get("dmv_offset_ft", 250)

    def inside(mp: float, pad: float = 0.0) -> bool:
        return begin - pad <= mp <= end + pad

    def where(mp: float) -> str:
        if inside(mp):
            return "inside the section"
        if inside(mp, limit_tol):
            return (f"at the begin limit (MP {_fmt_mp(begin)}, {begin_desc})" if mp < begin
                    else f"at the end limit (MP {_fmt_mp(end)}, {end_desc})")
        if mp < begin:
            return f"{_ft(begin - mp)} before the begin limit (MP {_fmt_mp(begin)}, {begin_desc})"
        return f"{_ft(mp - end)} past the end limit (MP {_fmt_mp(end)}, {end_desc})"

    out: list[Screened] = []
    for r in study.fiche.rows:
        s = Screened(row=r, flag="NIS", in_initial=r.crash_id in initial)
        d = study.detailed.get(r.crash_id)
        s.latlon = d.latlon if d else None
        if s.latlon:
            pr = pl.project(s.latlon)
            if pr.offset_ft <= dmv_off and -0.05 <= pr.along_mi <= pl.length_ft / FT_PER_MILE + 0.05:
                s.dmv_mp, s.dmv_offset_ft = pr.along_mi, pr.offset_ft
        on_route = r.on_road in aliases and r.muni_code in local_munis
        on_route_by_mp = r.mp_road == route
        if on_route_by_mp:
            on_route = True
        # a crash coded on another road but "toward" (or "from") a road that only meets the study route
        cross_strong = r.on_road in other_on and (r.toward_road in route_only or r.from_road in route_only)
        cross_weak = (r.on_road in other_on and not cross_strong
                      and (r.toward_road in weak_names or r.from_road in weak_names))
        cross_coded = cross_strong or cross_weak
        upper = " | ".join([r.on_road, r.from_road, r.toward_road]).upper()
        has_keyword = any(k in upper for k in keywords)

        # ---- implied milepost from the description
        if on_route or cross_coded or has_keyword:
            frm = feature_mps.get(r.from_road)
            to = feature_mps.get(r.toward_road)
            miles = r.miles or 0.0
            if frm is not None:
                if to is not None and to != frm:
                    s.implied_mp = frm + miles if to > frm else frm - miles
                elif r.dir and r.dir[0] in "SE":
                    s.implied_mp = frm + miles
                elif r.dir and r.dir[0] in "NW":
                    s.implied_mp = frm - miles
                else:
                    s.implied_mp = frm

        # ---- IS crashes
        if s.in_initial:
            s.flag, s.priority = "IS", 0
            s.triggers.append("In study")
            coded_ok = r.mp is not None and not r.unmileposted and inside(r.mp)
            if coded_ok:
                s.reasons.append("In initial study - at study MP")
            elif r.unmileposted:
                s.reasons.append("In initial study - MP 999.999; verify location in report")
                s.flag = "IS?"; s.triggers.append("IS-verify")
            else:
                s.reasons.append(f"In initial study but coded MP {_fmt_mp(r.mp)} is {where(r.mp)}; verify in report")
                s.flag = "IS?"; s.triggers.append("IS-verify")
            if s.dmv_mp is not None and r.mp is not None and not r.unmileposted and abs(s.dmv_mp - r.mp) > 0.05:
                s.reasons.append(f"{d.source} coordinates project to MP {_fmt_mp(s.dmv_mp)} ({_ft(abs(s.dmv_mp - r.mp))} from coded MP {_fmt_mp(r.mp)}); confirm location in report, in the section either way" if inside(s.dmv_mp) else f"{d.source} coordinates project to MP {_fmt_mp(s.dmv_mp)}, {where(s.dmv_mp)}; confirm location in report")
                if s.flag == "IS":
                    s.flag = "IS?"; s.triggers.append("IS-verify")
            s.priority_label = "In study"
            s.comment = "" if s.flag == "IS" else "; ".join(s.reasons[1:])
            out.append(s)
            continue

        # ---- NIS triggers (reasons kept per trigger, written out in a fixed order)
        fired: dict[str, str] = {}
        desc = (f"{r.on_road} {r.miles if r.miles is not None else 0:g} mi {r.dir} from "
                f"{r.from_road or '-'} toward {r.toward_road or '-'}").replace("  ", " ")
        coded = "MP 999.999" if r.unmileposted else f"coded MP {_fmt_mp(r.mp)}"
        # Between: description implies a location in or near the section
        if s.implied_mp is not None and (on_route or cross_coded):
            imp = s.implied_mp
            differs = r.unmileposted or r.mp is None or abs(imp - r.mp) > 0.003
            tail = ""
            if cross_weak:
                tail = (f" - crash is coded on {r.on_road}; {r.toward_road if r.toward_road in weak_names else r.from_road}"
                        f" meets both {r.on_road} and {route}, so the description fits either route")
            elif cross_strong:
                tail = f" - crash is coded on {r.on_road}, but {r.toward_road if r.toward_road in route_only else r.from_road} is only on {route}"
            if inside(imp, limit_tol) and differs:
                fired["Between"] = f"description ({desc}) implies MP {_fmt_mp(imp)}, {where(imp)}; {coded}{tail}"
            elif inside(imp, window) and differs and not (imp <= 0.0005 and r.on_road not in aliases):
                fired["Between"] = f"description ({desc}) implies MP {_fmt_mp(imp)}, {where(imp)}; {coded}{tail}"
        # Window: mileposted on the route near the limits
        if on_route_by_mp and r.mp is not None and not r.unmileposted:
            if inside(r.mp):
                fired["Window"] = f"{route} MP {_fmt_mp(r.mp)} is inside the section but the crash is not in the initial study - check"
            elif inside(r.mp, window):
                if r.mp <= 0.0005 and "Between" not in fired:
                    fired["Window"] = (f"{route} MP {_fmt_mp(r.mp)} is the {cfg['intersection']['name']} intersection, "
                                       f"{_ft(begin - r.mp)} before the begin limit (MP {_fmt_mp(begin)}, {begin_desc})"
                                       f" - an intersection crash unless the report puts it past the driveway")
                elif r.mp > 0.0005:
                    fired["Window"] = f"{route} MP {_fmt_mp(r.mp)} is {where(r.mp)} - within {window} mi"
        # DMV: coordinates on the route inside (or at) the limits
        if (s.dmv_mp is not None and inside(s.dmv_mp, dmv_pad)
                and (inside(s.dmv_mp, limit_tol) or s.dmv_offset_ft <= sc.get("dmv_window_offset_ft", 100))
                and not (s.dmv_mp <= 0.0005 and s.dmv_offset_ft > 40)):
            fired["DMV"] = (f"{d.source} coordinates ({s.latlon[0]:.6f}, {s.latlon[1]:.6f}) project onto {route} at MP "
                            f"{_fmt_mp(s.dmv_mp)} ({s.dmv_offset_ft:.0f} ft off the centerline), {where(s.dmv_mp)}"
                            + ("" if on_route else f" - crash is coded on {r.on_road or 'another road'}"))
        # Combo: unmileposted crash coded with section / intersection road names
        if r.unmileposted and r.muni_code in local_munis:
            names = {r.from_road, r.toward_road}
            if has_keyword:
                hits = [n for n in [r.on_road, r.from_road, r.toward_road] if any(k in n.upper() for k in keywords)]
                fired["Combo"] = f"MP 999.999 crash coded with a section road ({', '.join(hits)})"
            elif r.on_road in aliases and (names & int_names or names & route_only or names & weak_names):
                fired["Combo"] = f"MP 999.999 crash on {r.on_road} coded from {r.from_road or '-'} toward {r.toward_road or '-'} (study route roads)"

        if not fired:
            out.append(s)
            continue
        s.flag = "?"
        order = ["Between", "DMV", "Combo", "Window"]
        s.triggers = [t for t in order if t in fired]
        s.reasons = [fired[t] for t in s.triggers]
        # coordinate veto: coordinates that sit well away from the section outrank the description
        conflict = None
        trusted = d is not None and d.source in ("DMV349", "DMV349CLEANED", "NCDOT_TSU")
        if s.latlon and s.dmv_mp is None and trusted and not (on_route_by_mp and r.mp is not None and not r.unmileposted):
            far = min(dist_ft(s.latlon, pl.point_at_mi(begin)), dist_ft(s.latlon, pl.point_at_mi(end)),
                      dist_ft(s.latlon, pl.point_at_mi((begin + end) / 2)))
            if far > 1500:
                conflict = f"{d.source} coordinates ({s.latlon[0]:.6f}, {s.latlon[1]:.6f}) are {far:,.0f} ft from the section"
        # priority
        def strictly(mp):
            return mp is not None and inside(mp)
        def at_limit(mp):
            return mp is not None and inside(mp, limit_tol) and not inside(mp)
        imp, dmv = s.implied_mp, s.dmv_mp
        desc_ok = "Between" in fired and not cross_weak
        near_int = (dmv if dmv is not None else (imp if imp is not None else (r.mp if r.mp is not None and not r.unmileposted else 1.0)))
        if conflict:
            s.priority = 5
            s.reasons.append(conflict)
        elif ("DMV" in fired and strictly(dmv)) or (desc_ok and strictly(imp)):
            s.priority = 1
        elif ("DMV" in fired and at_limit(dmv)) or ("Between" in fired and (strictly(imp) or at_limit(imp))) or "Combo" in fired:
            s.priority = 2
        elif near_int is not None and near_int <= sc.get("intersection_zone_mi", 0.012) and not strictly(near_int):
            s.priority = 4
        elif "Between" in fired or "DMV" in fired or "Window" in fired:
            s.priority = 3
        else:
            s.priority = 5
        if s.priority == 2 and ("Combo" in fired and not ("Between" in fired or "DMV" in fired)) and near_int <= sc.get("intersection_zone_mi", 0.012):
            s.priority = 4
        s.priority_label = {1: "Likely ADD - locates inside the section",
                            2: "Possible ADD - at a limit or by description only; review the report",
                            3: "Window - just outside the limits",
                            4: f"At the {cfg['intersection']['name'].split(' /')[0]} intersection - likely NIS",
                            5: "Check - description and coordinates disagree"}[s.priority]
        s.reasons.insert(0, s.priority_label)
        s.comment = s.reason
        out.append(s)
    return out


def review_list(screened: list[Screened]) -> list[Screened]:
    """Rows for the Review IDs sheet: all IS/IS? crashes first, then the '?' candidates by priority."""
    is_rows = [s for s in screened if s.flag in ("IS", "IS?")]
    is_rows.sort(key=lambda s: (s.flag != "IS", s.row.mp if s.row.mp is not None else 999))
    cands = [s for s in screened if s.flag == "?"]
    cands.sort(key=lambda s: (s.priority, -(s.implied_mp if s.implied_mp is not None else (s.dmv_mp if s.dmv_mp is not None else (s.row.mp if s.row.mp is not None and not s.row.unmileposted else -1))), s.row.date))
    return is_rows + cands


def summary_counts(screened: list[Screened]) -> dict[str, int]:
    c: dict[str, int] = {}
    for s in screened:
        c[s.flag] = c.get(s.flag, 0) + 1
    return c
