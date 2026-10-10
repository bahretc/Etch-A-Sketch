"""Command line: python -m fca build <study folder> [--no-maps]   (or: fca build <study folder>)"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .screen import load_study, screen, summary_counts
from .workbook import build_workbook, write_review_ids


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fca", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="screen the fiche, write the workbook, review list and maps")
    b.add_argument("study_dir")
    b.add_argument("--no-maps", action="store_true")
    b.add_argument("--determinations", help="JSONL of report determinations (default: <study>/review/determinations.jsonl)")
    b.add_argument("--tile-cache", default=os.environ.get("FCA_TILE_CACHE", os.path.join(os.path.expanduser("~"), ".cache", "fca-tiles")))
    s = sub.add_parser("screen", help="print the screening result only")
    s.add_argument("study_dir")
    args = ap.parse_args(argv)

    study = load_study(args.study_dir)
    screened = screen(study)
    sid = study.study_id
    det_path = getattr(args, "determinations", None) or os.path.join(args.study_dir, "review", "determinations.jsonl")
    dets = None
    if os.path.exists(det_path):
        from .review import load_determinations, apply_determinations
        dets = load_determinations(det_path)
        # keep the pre-review screening for the Review IDs sheet, then apply the decisions
        import copy
        pre = {s.row.crash_id: (s.priority_label, s.reason) for s in screened}
        apply_determinations(screened, dets)
        for s in screened:
            if s.row.crash_id in dets:
                s.priority_label, s.screen_reason = pre[s.row.crash_id]
    if args.cmd == "screen":
        from .screen import review_list
        for sc in review_list(screened):
            r = sc.row
            print(f"{sc.flag:<3} p{sc.priority} {r.crash_id} {r.date} {r.on_road} MP={r.mp} | {sc.trigger} | {sc.reason}")
        print(summary_counts(screened))
        return 0
    out = os.path.join(args.study_dir, "outputs")
    os.makedirs(out, exist_ok=True)
    if dets:
        from .review import write_review_outputs, decisions_for_map
        info = build_workbook(study, screened, os.path.join(out, f"{sid}_Fiche_reviewed.xlsx"), reviewed=dets)
        for p in write_review_outputs(study, screened, dets, out):
            print(f"review: {p}")
        counts = {k: sum(1 for d in dets.values() if d.decision == k) for k in ("IS", "ADD", "DEL", "NIS")}
        print(f"workbook: {info['path']}  rows={info['fiche_rows']} decisions={counts}")
        decisions = decisions_for_map(study, screened, dets)
    else:
        info = build_workbook(study, screened, os.path.join(out, f"{sid}_Fiche.xlsx"))
        ids = write_review_ids(study, screened, os.path.join(out, f"{sid}_ReviewIDs.txt"))
        print(f"workbook: {info['path']}  rows={info['fiche_rows']} counts={info['counts']} review={info['review_rows']}")
        print(f"review ids ({len(ids)}): {', '.join(map(str, ids))}")
        decisions = None
    if not args.no_maps:
        from .figures import build_figures
        from .maps import map_html
        from .geo import TileCache
        paths = build_figures(study, screened, out, args.tile_cache, decisions=decisions)
        html = os.path.join(out, f"{sid}_CrashMap.html")
        map_html(study, screened, TileCache(args.tile_cache), html, decisions=decisions)
        for p in paths + [html]:
            print(f"map: {p}")
    with open(os.path.join(out, f"{sid}_screening.json"), "w") as fh:
        json.dump([{"crash_id": s.row.crash_id, "flag": s.flag, "triggers": s.triggers, "priority": s.priority,
                    "reason": s.reason, "implied_mp": s.implied_mp, "dmv_mp": s.dmv_mp, "dmv_offset_ft": s.dmv_offset_ft,
                    "latlon": s.latlon} for s in screened if s.flag != "NIS"], fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
