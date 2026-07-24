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

    # 1-page results sheet manual cells
    if args.results:
        import shutil as _sh

        from .results_sheet import (RESULTS_1T, RESULTS_2T,
                                    build_results_edits, load_results_yaml)
        from .xlsx_patch import verify_integrity, xlsx_patch
        rdata = load_results_yaml(args.results)
        rsheet = RESULTS_2T if args.target2 else RESULTS_1T
        tmp = args.output + ".results.tmp"
        xlsx_patch(args.output, tmp,
                   edits={rsheet: build_results_edits(args.template, rdata, rsheet)})
        _sh.move(tmp, args.output)
        rep = verify_integrity(args.template, args.output)
        if not rep.ok:
            raise RuntimeError(f"Integrity failed after results: {rep.problems}")
        print(f"Results sheet populated ({rsheet}).")

    # Binned Crashes sheet: every fiche crash under exactly one period banner
    if args.binned:
        if not (args.setup and args.fiche):
            raise SystemExit("--binned requires --setup (period dates) and --fiche")
        import shutil as _sh

        from .binned_sheet import assign_bins, build_binned_rows_xml
        from .periods import compute_whole_month_periods
        from .setup_sheet import load_setup_yaml
        from .xlsx_patch import replace_sheet_rows, verify_integrity
        sdata = load_setup_yaml(args.setup)
        if not (sdata.teaas_date and sdata.construction_months
                and sdata.construction_end):
            raise SystemExit("--binned needs teaas_date, construction_months, "
                             "and construction_end in the setup YAML")
        periods = compute_whole_month_periods(
            sdata.teaas_date, sdata.construction_months, sdata.construction_end)
        from .fiche_parser import parse_fiche
        fiche_all = parse_fiche(args.fiche)
        mp_by_id = {}
        for mp_path in (args.before_mp, args.after_mp):
            if mp_path:
                from .teaas import parse_import_list
                mp_by_id.update(parse_import_list(mp_path))
        routes = ({r.strip() for r in args.bin_routes.split(",")}
                  if args.bin_routes else None)
        mp_range = None
        if args.bin_mp_range:
            lo, hi = (float(x) for x in args.bin_mp_range.split(":"))
            mp_range = (lo, hi)
        statuses = None
        if args.statuses_from:
            from .binned_sheet import (analysis_type_of, read_filtered_fiche,
                                       validate_statuses)
            statuses = read_filtered_fiche(args.statuses_from)
            validate_statuses(statuses, analysis_type_of(args.template))
            print(f"Using {len(statuses)} Filtered Fiche determinations from "
                  f"{args.statuses_from}")
        bins = assign_bins(fiche_all, {c.crash_id for c in before},
                           {c.crash_id for c in after}, periods,
                           study_routes=routes, mp_range=mp_range,
                           statuses=statuses)
        rows_xml = build_binned_rows_xml(args.template, bins, periods, mp_by_id)
        tmp = args.output + ".binned.tmp"
        replace_sheet_rows(args.output, tmp, "Binned Crashes", rows_xml,
                           from_row=1)
        _sh.move(tmp, args.output)
        rep = verify_integrity(args.template, args.output)
        if not rep.ok:
            raise RuntimeError(f"Integrity failed after binning: {rep.problems}")
        counts = {k: len(v) for k, v in bins.items()}
        print(f"Binned Crashes populated: {counts}")

    # Filtered Fiche review sheet (pre-screened; determinations stay blank)
    if args.filtered:
        if not args.fiche:
            raise SystemExit("--filtered requires --fiche")
        import shutil as _sh

        from .binned_sheet import analysis_type_of
        from .fiche_parser import parse_fiche
        from .filtered_sheet import (build_filtered_rows_xml, prescreen)
        from .xlsx_patch import replace_sheet_rows, verify_integrity
        fiche_all = parse_fiche(args.fiche)
        mp_by_id = {}
        from .teaas import parse_import_list
        for mp_path in (args.before_mp, args.after_mp):
            if mp_path:
                mp_by_id.update(parse_import_list(mp_path))
        routes = ({r.strip() for r in args.bin_routes.split(",")}
                  if args.bin_routes else None)
        mp_range = None
        if args.bin_mp_range:
            lo, hi = (float(x) for x in args.bin_mp_range.split(":"))
            mp_range = (lo, hi)
        groups = prescreen(fiche_all, {c.crash_id for c in before},
                           {c.crash_id for c in after}, mp_by_id,
                           routes, mp_range,
                           analysis_type=analysis_type_of(args.template))
        rows_xml = build_filtered_rows_xml(args.template, groups)
        tmp = args.output + ".filtered.tmp"
        replace_sheet_rows(args.output, tmp, "Filtered Fiche", rows_xml,
                           from_row=1)
        _sh.move(tmp, args.output)
        rep = verify_integrity(args.template, args.output)
        if not rep.ok:
            raise RuntimeError(f"Integrity failed after filtered: {rep.problems}")
        print("Filtered Fiche populated: "
              + str({k: len(v) for k, v in groups.items()}))
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


def _cmd_binder_index(args) -> int:
    import time

    from .binder import index_binder
    t0 = time.time()

    def _progress(done, total):
        if done % 50 == 0 or done == total:
            print(f"  {done}/{total} pages ({time.time() - t0:.0f}s)",
                  flush=True)

    idx = index_binder(args.binder, dpi=args.dpi, workers=args.workers,
                       progress=_progress if not args.quiet else None)
    if args.known_ids:
        from .binder import apply_reconciliation, reconcile_index
        from .config import Config
        from .teaas import parse_crash_id_list
        known: set[str] = set()
        for path in args.known_ids:
            known |= {c.crash_id
                      for c in parse_crash_id_list(path, Config.load())}
        suggestions = reconcile_index(idx, known)
        for read, true_id in sorted(suggestions.items()):
            print(f"  reconciled misread header {read} -> {true_id}")
        apply_reconciliation(idx, suggestions)
    idx.save(args.output)
    pages = sum(len(v) for v in idx.pages_by_crash.values())
    print(f"Indexed {len(idx.pages_by_crash)} crash report(s) across "
          f"{pages} page(s) -> {args.output}")
    if idx.unassigned:
        print(f"  ! {len(idx.unassigned)} leading page(s) had no crash ID "
              "and precede the first report; check them manually")
    for w in idx.warnings:
        print(f"  ! {w}")
    return 0


def _cmd_binder_get(args) -> int:
    from .binder import BinderIndex, export_crash_pdf
    idx = BinderIndex.load(args.index)
    pages = export_crash_pdf(idx, args.crash_id, args.output,
                             dpi=args.dpi, keep_zip=not args.no_keep_zip)
    print(f"Wrote {pages} redacted page(s) for crash {args.crash_id} "
          f"-> {args.output}")
    print("Redaction is a screening aid; spot-check the pages (docs/07).")
    return 0


def _cmd_parse_email(args) -> int:
    import os as _os

    import yaml

    from .assignment_email import (parse_assignment_email, to_assignment_dict,
                                   to_assumptions_dict)
    parsed = parse_assignment_email(args.input)
    if not parsed:
        print(f"No 'Assignment #N' blocks found in {args.input}")
        return 2
    _os.makedirs(args.outdir, exist_ok=True)
    for num, pa in sorted(parsed.items(), key=lambda kv: int(kv[0])):
        if args.assignment and num != args.assignment:
            continue
        for kind, build in (("assumptions", to_assumptions_dict),
                            ("assignment", to_assignment_dict)):
            out = _os.path.join(args.outdir, f"assignment_{num}_{kind}.yaml")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(f"# Draft parsed from {_os.path.basename(args.input)}"
                         f" (Assignment #{num}); review before use.\n")
                yaml.safe_dump(build(pa), fh, sort_keys=False,
                               allow_unicode=True)
            print(f"Wrote {out}")
        periods = ", ".join(f"{k} {a} - {b}"
                            for k, (a, b) in pa.periods.items())
        print(f"  #{num}: {pa.order_id} {pa.project_id}"
              + (f" (TIP #{pa.tip})" if pa.tip else "")
              + f" | {pa.county} Co / Div {pa.division}"
              + f" | {'intersection' if pa.intersection_study else 'section'}"
              + (f" | {periods}" if periods else ""))
        if pa.notes:
            print(f"     {len(pa.notes)} note(s)/question(s) carried through "
                  "verbatim; read them before building anything.")
    return 0


def _cmd_qc(args) -> int:
    from .qc import recount
    rep = recount(args.workbook, treatment=args.treatment)
    print("Tallies:")
    for k, v in rep.tallies.items():
        print(f"  {k}: {v}")
    for w in rep.warnings:
        print(f"  ! confirm: {w}")
    if rep.errors:
        print(f"{len(rep.errors)} mismatch(es); do NOT deliver until "
              "resolved (docs/03 QC habits):")
        for e in rep.errors:
            print(f"  E: {e}")
        return 2
    print("Recount clean: sheet tallies agree"
          + (f"; {len(rep.warnings)} item(s) for the engineer's pass"
             if rep.warnings else "") + ".")
    return 0


def _cmd_ledger(args) -> int:
    from .ledger import (DepartureCall, apply_call, check_consistency,
                         read_ledger, tally)
    ledger = read_ledger(args.workbook)
    if not ledger:
        print(f"No ledger columns (Correctable?/Departure) found in "
              f"{args.workbook}")
        return 2
    if args.set_departure or args.exclude:
        call = DepartureCall(
            crash_id=args.crash_id,
            departure=args.set_departure,
            correctable=(None if args.correctable is None
                         else args.correctable == "Y"),
            travel_dir=args.travel_dir,
            comment=args.comment,
            exclude=args.exclude,
        )
        touched = apply_call(args.workbook, args.output or args.workbook,
                             call, ledger)
        print(f"Applied to {touched} sheet(s) -> "
              f"{args.output or args.workbook}")
        return 0
    for sheet in ledger:
        print(f"{sheet}: {tally(ledger, sheet)}")
    errors, confirms = check_consistency(ledger, treatment=args.treatment)
    for e in errors:
        print(f"  E: {e}")
    for c in confirms:
        print(f"  ! confirm: {c}")
    print(f"{len(errors)} error(s), {len(confirms)} confirmation(s).")
    return 2 if errors else 0


def _cmd_assumptions(args) -> int:
    import os as _os

    from .assumptions_email import (default_filename,
                                    generate_assumptions_email,
                                    load_assumptions_yaml)
    data = load_assumptions_yaml(args.input)
    _os.makedirs(args.outdir, exist_ok=True)
    out = _os.path.join(args.outdir, default_filename(data))
    generate_assumptions_email(data, out)
    print(f"Wrote {out}")
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
    ft.add_argument("--results",
                    help="Results-sheet YAML (project identity block, "
                         "countermeasure text, Additional Information rows, "
                         "Items for Discussion).")
    ft.add_argument("--binned", action="store_true",
                    help="Also populate the Binned Crashes sheet (requires "
                         "--setup and --fiche).")
    ft.add_argument("--bin-routes", dest="bin_routes",
                    help="Study route names for prior-period binning, "
                         "comma-separated (e.g. 'SR 1003').")
    ft.add_argument("--bin-mp-range", dest="bin_mp_range",
                    help="Study milepost range lo:hi (e.g. 17.691:17.811). "
                         "Pre-screen only; superseded by --statuses-from.")
    ft.add_argument("--statuses-from", dest="statuses_from",
                    help="Workbook whose Filtered Fiche sheet carries the "
                         "engineer's IS/NIS/ADD determinations; these are "
                         "authoritative for binning.")
    ft.add_argument("--filtered", action="store_true",
                    help="Also generate the pre-screened Filtered Fiche "
                         "review sheet (statuses left blank for the engineer "
                         "except already-determined ID-list crashes).")
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

    bi = sub.add_parser(
        "binder-index",
        help="OCR-index a scanned DMV-349 binder (crash ID header box, "
             "psm 6, top-right crop) into a reusable JSON page index.")
    bi.add_argument("--binder", required=True, nargs="+",
                    help="Binder PDF part(s), in part order.")
    bi.add_argument("--output", required=True, help="Index JSON path.")
    bi.add_argument("--dpi", type=int, default=150)
    bi.add_argument("--workers", type=int, default=3)
    bi.add_argument("--known-ids", nargs="*",
                    help="TEAAS Crash ID List file(s); misread header IDs "
                         "sharing a 7+ digit run with a unique known ID "
                         "missing from the index are re-keyed (each fix is "
                         "printed and recorded in the index warnings).")
    bi.add_argument("--quiet", action="store_true")
    bi.set_defaults(func=_cmd_binder_index)

    bg = sub.add_parser(
        "binder-get",
        help="Extract one crash's pages from an indexed binder as a REDACTED "
             "image-only PDF (PII removed before anyone sees it).")
    bg.add_argument("--index", required=True, help="Index JSON from binder-index.")
    bg.add_argument("--crash-id", required=True)
    bg.add_argument("--output", required=True)
    bg.add_argument("--dpi", type=int, default=150)
    bg.add_argument("--no-keep-zip", action="store_true",
                    help="Redact ZIP codes too (kept by default).")
    bg.set_defaults(func=_cmd_binder_get)

    pe = sub.add_parser(
        "parse-email",
        help="Parse an assignment/assumptions email (.msg/.eml/.txt) into "
             "draft assumptions and assignment YAMLs, one pair per "
             "'Assignment #N' block (newest copy in the thread wins).")
    pe.add_argument("--input", required=True, help="Email file (.msg/.eml).")
    pe.add_argument("--outdir", default="output")
    pe.add_argument("--assignment", help="Only this assignment number.")
    pe.set_defaults(func=_cmd_parse_email)

    qc = sub.add_parser(
        "qc",
        help="Recount the workbook before delivering: Filtered Fiche vs "
             "Binned Crashes vs Before/After, the lane departure ledger "
             "across sheets, and 'N crashes' text quotes vs the tallies.")
    qc.add_argument("--workbook", required=True)
    qc.add_argument("--treatment", choices=["centerline", "edgeline", "dual"],
                    help="Enables the correctability coverage checks.")
    qc.set_defaults(func=_cmd_qc)

    lg = sub.add_parser(
        "ledger",
        help="Lane departure CL/R ledger: report or change a crash's "
             "Departure/Correctable/Target call on EVERY sheet it appears "
             "(Filtered Fiche, Before/After, Binned Crashes) in one "
             "template-preserving patch.")
    lg.add_argument("--workbook", required=True)
    lg.add_argument("--treatment", choices=["centerline", "edgeline", "dual"])
    lg.add_argument("--crash-id")
    lg.add_argument("--set-departure", choices=["Centerline", "Right"])
    lg.add_argument("--correctable", choices=["Y", "N"])
    lg.add_argument("--travel-dir")
    lg.add_argument("--comment")
    lg.add_argument("--exclude", action="store_true",
                    help="Side-street run-through: clear Target flags and "
                         "departure everywhere; requires --comment with the "
                         "rationale (docs/03).")
    lg.add_argument("--output", help="Write here instead of in place.")
    lg.set_defaults(func=_cmd_ledger)

    ae = sub.add_parser(
        "assumptions",
        help="Generate the assumptions email .docx from a YAML (docs/05 team "
             "template; periods computed from TEAAS date + construction).")
    ae.add_argument("--input", required=True, help="Assumptions YAML.")
    ae.add_argument("--outdir", default=".")
    ae.set_defaults(func=_cmd_assumptions)

    d = sub.add_parser("doctor", help="Report available optional backends.")
    d.set_defaults(func=_cmd_doctor)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
