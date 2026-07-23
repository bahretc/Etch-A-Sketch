"""Command-line interface for the NCDOT safety-evaluation automation."""
from __future__ import annotations

import argparse
import os
import sys

from .config import Config
from .ocr import available_backends
from .pipeline import run_from_files, write_markdown, write_workbook


def _cmd_run(args) -> int:
    cfg = Config.load(args.config)
    result = run_from_files(args.fiche, args.assignment, args.config, fmt=args.format)

    os.makedirs(args.outdir, exist_ok=True)
    stem = args.name or os.path.splitext(os.path.basename(args.assignment))[0]
    xlsx = os.path.join(args.outdir, f"{stem}_Evaluation.xlsx")
    md = os.path.join(args.outdir, f"{stem}_Report.md")
    write_workbook(result, cfg, xlsx)
    write_markdown(result, cfg, md)

    b = result.stats.get("before")
    a = result.stats.get("after")
    ba = result.before_after
    print(f"Parsed {len(result.crashes)} crashes.")
    if b and a:
        print(f"  Before: {b.total} crashes ({b.years:.1f} yr)   "
              f"After: {a.total} crashes ({a.years:.1f} yr)")
    if ba:
        print(f"  Overall reduction: {ba['total'].get('reduction_pct')}%")
    for w in result.warnings:
        print(f"  ! {w}")
    print(f"Wrote:\n  {xlsx}\n  {md}")
    return 0


def _cmd_parse(args) -> int:
    from .fiche_parser import parse_fiche
    crashes = parse_fiche(args.fiche, fmt=args.format)
    print(f"Parsed {len(crashes)} crashes.")
    for c in crashes[: args.limit]:
        print(f"  {c.crash_id}  {c.date}  {c.on_road:<20} MP={c.mp} "
              f"T={c.t} S={c.s}")
    return 0


def _cmd_fill_template(args) -> int:
    from .eval_workbook import populate_evaluation_workbook
    from .teaas import enrich_from_fiche, parse_crash_id_list, parse_import_list
    from .xlsx_patch import recalc

    cfg = Config.load(args.config)
    before = parse_crash_id_list(args.before, cfg)
    after = parse_crash_id_list(args.after, cfg)

    # enrich C/F/L codes from the original fiche, joined by Crash ID
    if args.fiche:
        from .fiche_parser import parse_fiche
        fiche = parse_fiche(args.fiche)
        n = enrich_from_fiche(before + after, fiche)
        print(f"Enriched {n}/{len(before) + len(after)} crashes from the fiche.")

    # mileposts for Section workbooks (crash_id|<tab>MP import files)
    for crashes, mp_path in ((before, args.before_mp), (after, args.after_mp)):
        if mp_path:
            mps = parse_import_list(mp_path)
            for crash in crashes:
                if crash.crash_id in mps:
                    crash.mp = mps[crash.crash_id]

    # classify targets when requested
    if args.target1 or args.target2:
        from .classify import classify_targets
        wanted = [t for t in (args.target1, args.target2) if t]
        for crash in before + after:
            crash.target_types = classify_targets(crash, wanted, cfg)

    report = populate_evaluation_workbook(
        args.template, args.output, before, after,
        target1_name=args.target1, target2_name=args.target2,
    )
    print(f"Populated {len(before)} before / {len(after)} after crashes "
          f"into {args.output}")

    # Evaluation Set-up sheet (dates, representative years, AADT tables)
    if args.setup:
        import shutil as _sh

        from .setup_sheet import build_setup_edits, load_setup_yaml
        from .xlsx_patch import verify_integrity, xlsx_patch
        data = load_setup_yaml(args.setup)
        tmp = args.output + ".setup.tmp"
        xlsx_patch(args.output, tmp,
                   edits={"Evaluation Set-up": build_setup_edits(args.template, data)})
        _sh.move(tmp, args.output)
        rep = verify_integrity(args.template, args.output)
        if not rep.ok:
            raise RuntimeError(f"Integrity failed after setup: {rep.problems}")
        print("Evaluation Set-up populated.")
    print(f"Integrity: OK ({report.checked_members} drawings/media members "
          "byte-identical)")
    if args.recalc:
        ok = recalc(args.output)
        print("Recalc pass:", "done" if ok else "SKIPPED (LibreOffice unavailable)")
        if ok:
            from .xlsx_patch import verify_integrity
            rep2 = verify_integrity(args.template, args.output)
            print("Post-recalc integrity:",
                  "OK" if rep2.ok else f"FAILED: {rep2.problems}")
    return 0


def _cmd_aadt(args) -> int:
    from .aadt_arcgis import STATIONS_URL, query_stations, stations_to_csv
    point = None
    if args.point:
        lon, lat = (float(x) for x in args.point.split(","))
        point = (lon, lat)
    stations = query_stations(
        where=args.where, point=point, radius_meters=args.radius,
        service_url=args.service_url or STATIONS_URL)
    with open(args.output, "w") as fh:
        fh.write(stations_to_csv(stations))
    print(f"{len(stations)} station(s) -> {args.output}")
    for s in stations[:5]:
        yrs = sorted(s.years)
        span = f"{yrs[0]}-{yrs[-1]}" if yrs else "no years"
        print(f"  {s.station_id}  {s.route:<18} {s.county:<12} {span}")
    return 0


def _cmd_redact(args) -> int:
    from .redact import redact_file
    report = redact_file(args.input, args.output,
                         keep_zip=not args.no_keep_zip, dpi=args.dpi)
    print(f"Redacted {report.boxes} region(s) across {report.pages} page(s) "
          f"-> {args.output}")
    for reason, n in sorted(report.by_reason.items()):
        print(f"  {reason}: {n}")
    for w in report.warnings:
        print(f"  ! {w}")
    print("Output is image-only (no text layer). Spot-check before sharing; "
          "OCR can miss handwriting or poor scans.")
    return 0


def _cmd_doctor(args) -> int:
    print("OCR / PDF backends:")
    for name, ok in available_backends().items():
        print(f"  {'[ok]' if ok else '[--]'} {name}")
    try:
        import openpyxl  # noqa
        print("  [ok] openpyxl")
    except Exception:
        print("  [--] openpyxl (workbook output unavailable)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="safety-eval",
        description="Automate NCDOT before/after safety evaluations from a "
                    "TEAAS fiche + assignment.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Run the full evaluation pipeline.")
    r.add_argument("--fiche", required=True, help="Fiche file (csv/txt/pdf).")
    r.add_argument("--assignment", required=True, help="Assignment YAML file.")
    r.add_argument("--config", help="Optional config override YAML.")
    r.add_argument("--format", default="auto",
                   choices=["auto", "csv", "teaas", "pdf"])
    r.add_argument("--outdir", default="output")
    r.add_argument("--name", help="Output file stem.")
    r.set_defaults(func=_cmd_run)

    pa = sub.add_parser("parse", help="Parse a fiche and print a preview.")
    pa.add_argument("--fiche", required=True)
    pa.add_argument("--format", default="auto",
                    choices=["auto", "csv", "teaas", "pdf"])
    pa.add_argument("--limit", type=int, default=10)
    pa.set_defaults(func=_cmd_parse)

    ft = sub.add_parser(
        "fill-template",
        help="Populate a real NCDOT Evaluation Workbook template (columns A-M "
             "of Before/After) from TEAAS Crash ID List exports.")
    ft.add_argument("--template", required=True, help="Pristine template xlsx.")
    ft.add_argument("--before", required=True,
                    help="TEAAS 5-col Crash ID List for the before period.")
    ft.add_argument("--after", required=True,
                    help="TEAAS 5-col Crash ID List for the after period.")
    ft.add_argument("--output", required=True)
    ft.add_argument("--fiche",
                    help="Original fiche (csv/txt/pdf) to enrich C/F/L codes "
                         "by Crash ID.")
    ft.add_argument("--before-mp", dest="before_mp",
                    help="Milepost import file for the before period "
                         "(crash_id|<tab>MP), Section workbooks.")
    ft.add_argument("--after-mp", dest="after_mp",
                    help="Milepost import file for the after period.")
    ft.add_argument("--target1", help="Target-1 crash type name (config key).")
    ft.add_argument("--target2", help="Target-2 crash type name, if defined.")
    ft.add_argument("--setup",
                    help="Evaluation Set-up YAML (TEAAS date, construction "
                         "period, representative years, AADT tables).")
    ft.add_argument("--config", help="Optional config override YAML.")
    ft.add_argument("--recalc", action="store_true",
                    help="Run the single LibreOffice headless recalc pass.")
    ft.set_defaults(func=_cmd_fill_template)

    aq = sub.add_parser(
        "aadt",
        help="Query NCDOT AADT stations (ArcGIS service behind the AADT web "
             "map) and write a CSV of yearly volumes.")
    aq.add_argument("--where", default="1=1",
                    help="ArcGIS SQL filter, e.g. \"COUNTY='JOHNSTON'\".")
    aq.add_argument("--point", help="lon,lat to search around (WGS84).")
    aq.add_argument("--radius", type=float, default=800.0,
                    help="Search radius in meters (default 800).")
    aq.add_argument("--service-url", dest="service_url",
                    help="Override the feature-service layer URL.")
    aq.add_argument("--output", default="aadt_stations.csv")
    aq.set_defaults(func=_cmd_aadt)

    rd = sub.add_parser(
        "redact",
        help="Redact PII (names, addresses, DOB, phone, DL numbers) from an "
             "uploaded crash report (PDF/TIFF/image). ZIP codes and crash IDs "
             "are kept. Output is an image-only PDF.")
    rd.add_argument("--input", required=True, help="Crash report PDF/TIFF/image.")
    rd.add_argument("--output", required=True, help="Redacted PDF path.")
    rd.add_argument("--no-keep-zip", action="store_true",
                    help="Also redact ZIP codes (kept by default).")
    rd.add_argument("--dpi", type=int, default=200,
                    help="Rasterization DPI for PDF input (default 200).")
    rd.set_defaults(func=_cmd_redact)

    d = sub.add_parser("doctor", help="Report available optional backends.")
    d.set_defaults(func=_cmd_doctor)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
