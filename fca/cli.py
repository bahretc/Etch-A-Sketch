"""Command line: python -m fca build studies/<study_id> [--no-maps]"""
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
    b.add_argument("--tile-cache", default=os.environ.get("FCA_TILE_CACHE", os.path.join(os.path.expanduser("~"), ".cache", "fca-tiles")))
    s = sub.add_parser("screen", help="print the screening result only")
    s.add_argument("study_dir")
    args = ap.parse_args(argv)

    study = load_study(args.study_dir)
    screened = screen(study)
    sid = study.study_id
    if args.cmd == "screen":
        from .screen import review_list
        for sc in review_list(screened):
            r = sc.row
            print(f"{sc.flag:<3} p{sc.priority} {r.crash_id} {r.date} {r.on_road} MP={r.mp} | {sc.trigger} | {sc.reason}")
        print(summary_counts(screened))
        return 0
    out = os.path.join(args.study_dir, "outputs")
    os.makedirs(out, exist_ok=True)
    info = build_workbook(study, screened, os.path.join(out, f"{sid}_Fiche.xlsx"))
    ids = write_review_ids(study, screened, os.path.join(out, f"{sid}_ReviewIDs.txt"))
    print(f"workbook: {info['path']}  rows={info['fiche_rows']} counts={info['counts']} review={info['review_rows']}")
    print(f"review ids ({len(ids)}): {', '.join(map(str, ids))}")
    if not args.no_maps:
        from .figures import build_figures
        from .maps import map_html
        from .geo import TileCache
        paths = build_figures(study, screened, out, args.tile_cache)
        html = os.path.join(out, f"{sid}_CrashMap.html")
        map_html(study, screened, TileCache(args.tile_cache), html)
        for p in paths + [html]:
            print(f"map: {p}")
    with open(os.path.join(out, f"{sid}_screening.json"), "w") as fh:
        json.dump([{"crash_id": s.row.crash_id, "flag": s.flag, "triggers": s.triggers, "priority": s.priority,
                    "reason": s.reason, "implied_mp": s.implied_mp, "dmv_mp": s.dmv_mp, "dmv_offset_ft": s.dmv_offset_ft,
                    "latlon": s.latlon} for s in screened if s.flag != "NIS"], fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
