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
    for num, pa in sorted(parsed.items(), key=lambda kv: (not str(kv[0]).isdigit(), int(kv[0]) if str(kv[0]).isdigit() else 0, str(kv[0]))):
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


def _cmd_archive_manifest(args) -> int:
    from .archive import build_manifest
    summary = build_manifest(args.inventory, args.emails, args.output,
                             docx_dir=args.docx)
    print(f"{summary['evaluations']} evaluation(s) in "
          f"{summary['clusters']} companion cluster(s) -> "
          f"{summary['manifest']}")
    for cluster in summary["multi_wo_clusters"]:
        print(f"  companions kept together: {', '.join(cluster)}")
    print(f"  split: {summary['split']}")
    for key, halves in sorted(summary["strata"].items()):
        print(f"  {key}: train {halves['train']} / verify {halves['verify']}")
    for flag, wos in summary["flags"].items():
        print(f"  ! {flag}: {len(wos)} ({', '.join(wos[:6])}"
              + (" ..." if len(wos) > 6 else "") + ")")
    return 0


def _cmd_bench(args) -> int:
    from . import bench

    def _progress(done, total):
        print(f"  {done}/{total}", flush=True)

    if args.stage == "extract":
        out = bench.extract_datasets(args.workbooks, args.manifest,
                                     args.outdir, msg_dir=args.msgs,
                                     progress=_progress)
        print(f"train {out['train']} / verify {out['verify']} records"
              f" ({out['with_assumptions']} with .msg assumptions)")
        for p in out["problems"]:
            print(f"  ! {p}")
        return 0
    if args.stage == "draft":
        out = bench.run_drafts(args.dataset, args.train, args.output,
                               model=args.model, k=args.exemplars,
                               mode=args.mode, rehearsal=args.rehearsal,
                               limit=args.limit, progress=_progress)
        print(f"drafted {out['drafted']} ({out['mode']}, {out['model']})")
        for wo, err in out["errors"].items():
            print(f"  ! {wo}: {err}")
        return 0
    if args.stage == "score":
        report = bench.score_run(args.drafts, args.dataset, args.train,
                                 args.output)
        s = report["summary"]
        print(f"{s['evaluations']} evaluation(s) | median similarity "
              f"{s['median_similarity']} (p25 {s['p25']} / p75 {s['p75']}) "
              f"| clean-gate rate {s['clean_gate_rate']}")
        for k, v in s["per_stratum_median"].items():
            print(f"  {k}: {v}")
        return 0
    print(f"Unknown stage {args.stage!r}")
    return 2


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
    if args.master:
        if not args.order_id:
            print("--order-id is required with --master")
            return 2
        from .master_eval import find_assignment, to_assumptions_data
        data = to_assumptions_data(find_assignment(args.master,
                                                   args.order_id))
        print("Draft from the Master Evaluation Spreadsheet; NCDOT's reply "
              "in the assignment thread is the authoritative record. "
              "Target crashes and time periods are left for the engineer.")
    elif args.input:
        data = load_assumptions_yaml(args.input)
    else:
        print("Provide --input YAML or --master + --order-id")
        return 2
    _os.makedirs(args.outdir, exist_ok=True)
    out = _os.path.join(args.outdir, default_filename(data))
    generate_assumptions_email(data, out)
    print(f"Wrote {out}")
    return 0


def _study_choices():
    from .study_type import choices
    return choices()


def _cmd_fiche_workbook(args) -> int:
    """Assemble the study workbook from the four TEAAS exports."""
    from .fiche_workbook import build_fiche_workbook

    out = args.out or f"{args.study}_Fiche.xlsx"
    counts = build_fiche_workbook(
        out, fiche_csv=args.fiche, initial_study_csv=args.initial_study,
        initial_id_txt=args.initial_ids, detailed_fiche_csv=args.detailed,
        study=args.study)
    from .study_type import get
    for sheet, n in counts.items():
        print(f"{n:>6} rows -> {sheet}")

    want_screen = any(v is not None
                      for v in (args.features, args.lo, args.hi))
    if want_screen:
        missing = [f for f, v in (("--features", args.features),
                                  ("--lo", args.lo), ("--hi", args.hi),
                                  ("--route", args.route)) if not v]
        if missing:
            print(f"screen skipped: {' '.join(missing)} required to run the "
                  "colour screen with the build")
            return 2
        import openpyxl

        from .fiche_screen import parse_features_report, screen_sheet
        from .fiche_workbook import parse_initial_ids
        ids = []
        if args.initial_ids:
            _, raw = parse_initial_ids(args.initial_ids)
            ids = [r[0] for r in raw]
        wb = openpyxl.load_workbook(out)
        ws = wb[f"{args.study}_Fiche" if args.study else "Fiche"]
        tally = screen_sheet(ws, parse_features_report(args.features),
                             args.lo, args.hi, ids, route=args.route,
                             study=args.study_type)
        wb.save(out)
        print("screened: " + "   ".join(f"{k} {v}"
                                        for k, v in tally.items()))
    print(f"wrote {out}   ({get(args.study_type)})")
    return 0


def _cmd_check_branches(args) -> int:
    """Refuse to pass while a status contradicts Initial Study membership."""
    from .fiche_workbook import parse_initial_ids
    from .qc import check_branch_vocabulary

    _, raw = parse_initial_ids(args.initial_ids)
    problems = check_branch_vocabulary(args.workbook, args.sheet,
                                       [r[0] for r in raw])
    if not problems:
        print("No branch violations.")
        return 0
    print(f"{len(problems)} branch violation(s):")
    for p in problems:
        print(f"  row {p['row']:>4}  {p['crash_id']}  {p['status']:<4} "
              f"{p['problem']}")
    return 2


def _cmd_teaas_import(args) -> int:
    from .teaas import crashes_from_workbook, write_period_imports

    if getattr(args, "initial_ids", None):
        from .fiche_workbook import parse_initial_ids
        from .qc import check_branch_vocabulary
        _, raw = parse_initial_ids(args.initial_ids)
        bad = check_branch_vocabulary(args.workbook, args.sheet or "",
                                      [r[0] for r in raw])
        if bad:
            print(f"Refusing to write: {len(bad)} branch violation(s). "
                  "Run check-branches.")
            return 2
    crashes = crashes_from_workbook(args.workbook)
    if not crashes:
        print(f"No Before/After crash rows found in {args.workbook}")
        return 2
    written = write_period_imports(args.outdir, crashes, prefix=args.prefix)
    for label in ("before", "after"):
        path, n = written[label]
        print(f"{n:>5} crashes -> {path}")
    if "held" in written:
        path, n = written["held"]
        print(f"{n:>5} HELD (no milepost, not imported) -> {path}")
        return 1
    return 0


def _cmd_apply_review(args) -> int:
    """Write the engineer's determinations onto the fiche working sheet."""
    import json

    from .fiche_screen import apply_hsip_review
    from .review_queue import Determination

    dets = []
    with open(args.determinations, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            dets.append(Determination(
                crash_id=str(d["crash_id"]), status=d["status"],
                new_mp=d.get("new_mp"), comment=d.get("comment", "")))
    initial = None
    if args.initial_ids:
        from .fiche_workbook import parse_initial_ids
        _, raw = parse_initial_ids(args.initial_ids)
        initial = [r[0] for r in raw]
    tally = apply_hsip_review(args.workbook, args.out or args.workbook, dets,
                              sheet=args.sheet,
                              analysis_type=args.analysis_type,
                              initial_ids=initial)
    print("  ".join(f"{k} {v}" for k, v in tally.items()))
    print(f"{len(dets)} determination(s) -> {args.out or args.workbook} "
          "(reviewed layout: banners, blocks, blank separators)")
    return 0


def _cmd_warrants(args) -> int:
    """Screen a reviewed HSIP fiche workbook and rebuild its Warrant sheet."""
    from . import hsip
    from .warrants import format_screen

    if args.initial_ids:
        from .fiche_workbook import parse_initial_ids
        from .qc import check_branch_vocabulary
        _, raw = parse_initial_ids(args.initial_ids)
        bad = check_branch_vocabulary(args.workbook, args.sheet or "",
                                      [r[0] for r in raw])
        if bad:
            print(f"Refusing to run: {len(bad)} branch violation(s). "
                  "Run check-branches.")
            return 2
    run = hsip.run_hsip(
        args.workbook, args.facility, args.lo, args.hi, sheet=args.sheet,
        multilane=args.multilane,
        overrides=hsip.parse_overrides(args.override),
        study_type=args.study_type, import_out=args.import_out,
        strip_zeros=not args.padded, save=not args.no_save,
        inclusive_minimums=args.inclusive_minimums)
    print(format_screen(run.screen))
    print()
    for line in run.finding_lines:
        print(f"  {line}")
    if run.import_lines:
        print(f"\n{run.import_lines} ADD/RE crashes -> {args.import_out}")
    for f in run.daylight_flags or ():
        print(f"  daylight check: {f['crash_id']} has L={f['l']} at "
              f"{f['time']:%H:%M} but {f['problem']} "
              f"(sunrise {f['sunrise']:%H:%M}, sunset {f['sunset']:%H:%M})")
    if args.report_out:
        text = hsip.format_report(run, study=args.study or "",
                                  route=args.route or "",
                                  county=args.county or "")
        with open(args.report_out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"report text -> {args.report_out}")
    if not args.no_save:
        print(f"\nWarrant sheet rebuilt in {args.workbook}")
    return 0


def _cmd_import_list(args) -> int:
    """The ADD+RE milepost import for a section HSIP study (docs/09)."""
    import openpyxl

    from . import hsip
    from .teaas import write_import_list

    if args.initial_ids:
        from .fiche_workbook import parse_initial_ids
        from .qc import check_branch_vocabulary
        _, raw = parse_initial_ids(args.initial_ids)
        bad = check_branch_vocabulary(args.workbook, args.sheet or "",
                                      [r[0] for r in raw])
        if bad:
            print(f"Refusing to write: {len(bad)} branch violation(s). "
                  "Run check-branches.")
            return 2
    wb = openpyxl.load_workbook(args.workbook)
    ws = wb[args.sheet or hsip.fiche_sheet_name(wb)]
    pairs = hsip.import_pairs(hsip.read_analysis_rows(ws))
    if not pairs:
        print("No ADD or RE crashes with a milepost; nothing to import.")
        return 1
    n = write_import_list(args.out, pairs, strip_zeros=not args.padded)
    print(f"{n} ADD/RE crashes -> {args.out}")
    return 0


def _cmd_feature_list(args) -> int:
    """Feature inclusions for TEAAS from '<text>|<milepost>' pair lines."""
    from .teaas import write_feature_list

    rows = []
    with open(args.pairs, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            sep = "|" if "|" in line else ","
            text, mp = line.rsplit(sep, 1)
            rows.append((text.strip(), float(mp)))
    n = write_feature_list(args.out, rows, truncate=args.truncate)
    print(f"{n} feature(s) -> {args.out} (verify against a live TEAAS "
          "import; docs/09)")
    return 0


def _cmd_crash_map(args) -> int:
    """Build the self-contained GIS crash map from a reviewed workbook."""
    from .crash_map import build_crash_map

    features = []
    if args.features_pairs:
        with open(args.features_pairs, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                sep = "|" if "|" in line else ","
                label, mp = line.rsplit(sep, 1)
                features.append((label.strip(), float(mp)))
    window = None
    if args.window:
        wlo, whi = (float(x) for x in args.window.split(":"))
        window = (wlo, whi, args.window_label or "")
    out = args.out or "CrashMap.html"
    targets = ({t.strip() for t in args.targets.split(",") if t.strip()}
               if args.targets else None)
    s = build_crash_map(out, args.workbook, args.route, args.lo, args.hi,
                        sheet=args.sheet, coords_source=args.coords,
                        features=features or None, window=window,
                        subtitle=args.subtitle or "",
                        county=args.county or "",
                        basemap=not args.no_basemap,
                        diagram=args.diagram, targets=targets,
                        centerline=args.centerline,
                        diagram_round=args.diagram_round)
    print(f"{s['crashes']} crashes on the map "
          + "  ".join(f"{k} {v}" for k, v in sorted(s["counts"].items())))
    print(f"{s['tiles']} basemap tiles embedded"
          + (f" ({s['misses']} failed, render blank)" if s["misses"] else "")
          + f"; {s['bytes'] / 1048576:.1f} MB -> {out}")
    if args.gis_out:
        from .crash_map import export_gis
        n, csv_path = export_gis(
            args.gis_out, args.workbook, args.route, args.lo, args.hi,
            sheet=args.sheet, coords_source=args.coords,
            centerline=args.centerline, targets=targets, window=window,
            route_id=args.route_id or "")
        print(f"{n} crashes at exact mileposts -> {args.gis_out} "
              f"(+ {csv_path})")
    return 0


def _cmd_assist_score(args) -> int:
    """Score decide-mode proposals against the engineer's determinations.

    The engineer's reviewed statuses are ground truth, full stop. The output
    is a measurement of the assist, never of the engineer.
    """
    from .review_assist import score_proposals

    s = score_proposals(args.proposals, args.workbook, sheet=args.sheet,
                        status_col=args.status_col, id_col=args.id_col)
    if not s["scored"]:
        print("Nothing to score: no proposal matched a reviewed crash.")
        return 1
    print(f"Scored {s['scored']} proposal(s) against the engineer's review "
          f"(ground truth): {s['agree']}/{s['scored']} agree "
          f"({s['agree'] / s['scored']:.0%}).")
    for status in sorted(s["by_status"]):
        row = s["by_status"][status]
        print(f"  engineer {status:<4} {row['agree']:>3}/{row['n']:<3} "
              f"({row['agree'] / row['n']:.0%}) matched")
    if s["disagreements"]:
        print(f"\n{len(s['disagreements'])} disagreement(s) "
              "(engineer / assist, assist confidence):")
        for cid, actual, proposed, conf in s["disagreements"]:
            print(f"  {cid}: {actual} / {proposed}"
                  f"{f'  ({conf})' if conf else ''}")
    if s["skipped"]:
        print(f"\n{len(s['skipped'])} proposal(s) not scored (no decide "
              "status or not on the reviewed sheet).")
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


def _cmd_review_assist(args) -> int:
    import json

    from . import review_assist as ra
    from . import review_queue as rq
    from .binder import BinderIndex, render_crash_pages

    review = rq.load_review_sheet(args.workbook, args.sheet)
    idx = BinderIndex.load(args.index)
    coords = rq.parse_coordinates(args.coords) if args.coords else None
    point = None
    if args.study_point:
        lat, lon = (float(x) for x in args.study_point.split(","))
        point = (lat, lon)
    mp_range = None
    if args.mp_range:
        lo, hi = (float(x) for x in args.mp_range.split(":"))
        mp_range = (lo, hi)
    queue = rq.build_queue(review, binder_index=idx, coords=coords,
                           study_point=point, mp_range=mp_range)
    from .location import (FeatureInventory, clean_shape, read_location_block,
                           resolve)
    inventory = None
    if args.features:
        inventory = FeatureInventory.from_files(args.features)
        print(f"  features reports: {len(args.features)} file(s), routes "
              f"{sorted(inventory.features)}")
    else:
        print("  no features report supplied (--features): mileposts will not "
              "be resolved and the assist is told so")
    # The DetailedFiche doubles as the route shape: hundreds of coded crashes
    # on the milepost road are a dense (milepost, coordinate) map of it, so
    # coordinates resolve to a milepost instead of punting to the engineer.
    if inventory is not None and args.coords:
        for key in list(inventory.features):
            pts = rq.parse_shape_points(args.coords, key)
            if pts:
                inventory.shape[key] = clean_shape(pts)
        if inventory.shape:
            print("  route shape from the DetailedFiche: "
                  + ", ".join(f"{k} ({len(v)} pts)"
                              for k, v in inventory.shape.items()))
    ctx = ra.StudyContext(name=args.study_name, analysis_type=args.analysis_type,
                          study_point=point, mp_range=mp_range,
                          target_definition=args.target)
    initial = None
    if getattr(args, "initial_ids", None):
        from .fiche_workbook import parse_initial_ids
        _, raw = parse_initial_ids(args.initial_ids)
        initial = {str(r[0]) for r in raw}
        print(f"  initial study: {len(initial)} crashes; decide vocabulary "
              "narrows to the branch (docs/03)")
    only = {str(c) for c in args.only} if getattr(args, "only", None) else None

    import anthropic
    client = anthropic.Anthropic()
    n = 0
    with open(args.output, "w", encoding="utf-8") as fh:
        for item in queue:
            if args.limit and n >= args.limit:
                break
            if only is not None and str(item.row.crash_id) not in only:
                continue
            row = item.row
            if initial is not None:
                ctx.in_initial_study = str(row.crash_id) in initial
            pages = (render_crash_pages(idx, row.crash_id, dpi=idx.dpi)
                     if item.has_report else [])
            ctx.prescreen_ft = item.dist_ft
            # The location block survives redaction by design, so it is read
            # off the same redacted page the assist sees, and resolved against
            # the features reports supplied for this evaluation.
            ctx.fiche_milepost = row.mp
            ctx.resolved_location = None
            if pages:
                from .redact import ocr_words
                import tempfile as _tf
                with _tf.TemporaryDirectory() as _t:
                    _p = os.path.join(_t, "loc.png")
                    pages[0].save(_p)
                    words = ocr_words(_p, page=1)
                loc = read_location_block(words, pages[0].width, pages[0].height)
                ctx.resolved_location = resolve(
                    loc, inventory, fiche_milepost=row.mp,
                    fallback_coordinates=(coords.get(row.crash_id)
                                          if coords else None))
            res = ra.assist(row, ctx, pages, mode=args.mode, client=client,
                            redacted=True, model=args.model)
            fh.write(json.dumps(vars(res)) + "\n")
            n += 1
            rl = ctx.resolved_location
            if rl is not None:
                print(f"    location: {rl.summary()}")
            label = res.proposed_status or ("prepared" if res.mode == "prepare"
                                            else "-")
            flags = " ".join(res.flags) or ""
            print(f"  {row.crash_id}: {label}"
                  f"{' [needs manual]' if res.needs_manual else ''}"
                  f"{' ' + flags if flags else ''}")
    print(f"{n} proposal(s) -> {args.output} (mode={args.mode}). Proposals "
          "only; the engineer reviews and seals every determination.")
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

    am = sub.add_parser(
        "archive-manifest",
        help="Build the evaluation-archive manifest (docs/10): meta records, "
             "companion clustering, deterministic stratified 50/50 "
             "train/verify split, missing-piece flags.")
    am.add_argument("--inventory", required=True,
                    help="Directory of per-WO inventory JSONs.")
    am.add_argument("--emails", required=True,
                    help="Directory of downloaded assignment emails "
                         "(<WO>__<name>.msg).")
    am.add_argument("--output", required=True,
                    help="Output directory (manifest.jsonl + meta/*.yaml).")
    am.add_argument("--docx",
                    help="Directory of archived assumptions .docx files "
                         "(<WO>__assumptions.docx), the fallback when a "
                         "folder has no .msg thread.")
    am.set_defaults(func=_cmd_archive_manifest)

    be = sub.add_parser(
        "bench",
        help="Report-drafting benchmark: extract datasets from archived "
             "workbooks, draft with train-half exemplars, score vs the "
             "delivered text (docs/10; verify half measured, never mined).")
    be.add_argument("stage", choices=["extract", "draft", "score"])
    be.add_argument("--workbooks", help="extract: downloaded workbook dir.")
    be.add_argument("--msgs", help="extract: dir of downloaded assignment "
                    "threads (<wo>__*.msg) to attach authoritative "
                    "assumptions for msg-sourced WOs (docs/10).")
    be.add_argument("--manifest", default="archive/manifest.jsonl")
    be.add_argument("--outdir", default="datasets", help="extract output dir.")
    be.add_argument("--dataset", help="draft/score: records .jsonl.")
    be.add_argument("--drafts", help="score: drafts.jsonl to score against "
                    "the dataset.")
    be.add_argument("--train", help="train-half records .jsonl (exemplars).")
    be.add_argument("--output", help="draft: drafts.jsonl; score: report.json.")
    be.add_argument("--model", default=None,
                    help="Default: SAFETY_EVAL_ASSIST_MODEL or the measured "
                         "assist default.")
    be.add_argument("--exemplars", type=int, default=3)
    be.add_argument("--mode", choices=["batch", "sync"], default="batch")
    be.add_argument("--rehearsal", action="store_true",
                    help="Allow drafting the train half (tuning runs).")
    be.add_argument("--limit", type=int)
    be.set_defaults(func=_cmd_bench)

    rv = sub.add_parser(
        "review-assist",
        help="LLM-assisted fiche determinations over REDACTED DMV-349 pages "
             "(docs/03): 'decide' proposes a call with evidence; 'prepare' "
             "assembles the evidence and a draft comment and leaves the status "
             "to the engineer. Writes proposals.jsonl; never applies anything.")
    rv.add_argument("--workbook", required=True,
                    help="Workbook whose Filtered Fiche is being reviewed.")
    rv.add_argument("--sheet", default="Filtered Fiche")
    rv.add_argument("--index", required=True,
                    help="Binder index JSON (redacted per-crash page retrieval).")
    rv.add_argument("--analysis-type", dest="analysis_type",
                    choices=["intersection", "section"], default="intersection")
    rv.add_argument("--mode", choices=["decide", "prepare"], default="decide")
    rv.add_argument("--coords", help="DetailedFiche for the GPS pre-screen "
                    "(never the report's own coordinates).")
    rv.add_argument("--study-point", dest="study_point", help="lat,lon.")
    rv.add_argument("--mp-range", dest="mp_range", help="lo:hi (sections).")
    rv.add_argument("--features", nargs="+", metavar="FILE",
                    help="Features report(s) for this evaluation, one per "
                         "study route (TEAAS Features Report .pdf, a text "
                         "dump, or a route,feature,milepost .csv). Supplied "
                         "per analysis; without them no milepost is resolved "
                         "and the assist is told not to infer one.")
    rv.add_argument("--target", default="",
                    help="Target-crash definition text for context.")
    rv.add_argument("--study-name", dest="study_name", default="")
    rv.add_argument("--model", default=None,
                    help="Default: SAFETY_EVAL_ASSIST_MODEL or the measured "
                         "assist default.")
    rv.add_argument("--limit", type=int)
    rv.add_argument("--only", nargs="*",
                    help="Crash IDs to assist (default: the whole queue).")
    rv.add_argument("--initial-ids", dest="initial_ids",
                    help="TEAAS ID export. Sets in_initial_study per crash, "
                         "which narrows the decide vocabulary to its branch "
                         "(docs/03): in the study IS/RE/DEL, out ADD/NIS.")
    rv.add_argument("--output", required=True, help="proposals.jsonl")
    rv.set_defaults(func=_cmd_review_assist)

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
        help="Generate the assumptions email .docx (docs/05 team template) "
             "from a YAML, or draft it straight from the NCDOT Master "
             "Evaluation Spreadsheet row for an order.")
    ae.add_argument("--input", help="Assumptions YAML.")
    ae.add_argument("--master",
                    help="Master Evaluation Spreadsheet .xlsx; drafts the "
                         "document from the order's row instead of a YAML.")
    ae.add_argument("--order-id",
                    help="Evaluation Order Number to pull with --master.")
    ae.add_argument("--outdir", default=".")
    ae.set_defaults(func=_cmd_assumptions)

    tw = sub.add_parser(
        "check-branches",
        help="Gate: flag statuses that contradict Initial Study membership "
             "(docs/03). An initial-study crash that does not belong is DEL, "
             "never NIS. Exits non-zero if any violation is found, so it can "
             "guard the import list.")
    tw.add_argument("--workbook", required=True)
    tw.add_argument("--sheet", required=True)
    tw.add_argument("--initial-ids", required=True,
                    help="Pipe-delimited TEAAS ID export.")
    tw.set_defaults(func=_cmd_check_branches)

    ti = sub.add_parser(
        "teaas-import",
        help="Write the TEAAS milepost import files (Before_Import.txt / "
             "After_Import.txt) from a Section workbook's reviewed Before and "
             "After sheets. In-study crashes with no milepost go to a HELD "
             "list instead of the import.")
    ti.add_argument("--workbook", required=True)
    ti.add_argument("--outdir", default=".")
    ti.add_argument("--initial-ids",
                    help="Pipe-delimited TEAAS ID export. When given, the "
                         "branch gate runs first and refuses to write while "
                         "any status contradicts Initial Study membership.")
    ti.add_argument("--sheet", help="Sheet for the branch gate.")
    ti.add_argument("--prefix", default="",
                    help="Filename prefix, e.g. '04-15-39049_'.")
    ti.set_defaults(func=_cmd_teaas_import)

    ar = sub.add_parser(
        "apply-review",
        help="Write engineer determinations (a JSONL of crash_id / status / "
             "new_mp / comment) onto the fiche working sheet and regroup it "
             "into the reviewed layout: banner-headed IS / RE / ADD / DEL "
             "blocks, reviewed NIS split from never-reviewed, original order "
             "kept inside each block. Validates the branch vocabulary first "
             "and writes nothing on a violation (docs/03).")
    ar.add_argument("--workbook", required=True)
    ar.add_argument("--determinations", required=True,
                    help="JSONL, one determination per line.")
    ar.add_argument("--out", help="Output path (default: in place).")
    ar.add_argument("--sheet", help="Working sheet (default: the *_Fiche one).")
    ar.add_argument("--analysis-type", dest="analysis_type",
                    choices=["section", "intersection"], default="section")
    ar.add_argument("--initial-ids", dest="initial_ids",
                    help="TEAAS ID export; enables the branch check.")
    ar.set_defaults(func=_cmd_apply_review)

    wa = sub.add_parser(
        "warrants",
        help="Screen a REVIEWED HSIP fiche workbook (docs/12): reads the "
             "engineer's IS/RE/ADD rows off the working sheet, rebuilds the "
             "Warrant sheet (live formulas, facility dropdown, per-warrant "
             "sub-section findings), and prints the screen. Optionally writes "
             "the ADD+RE import list in the same run.")
    wa.add_argument("--workbook", required=True,
                    help="The study fiche workbook, after review.")
    wa.add_argument("--sheet", help="Working sheet (default: the *_Fiche one).")
    wa.add_argument("--facility", default="freeway",
                    choices=["freeway", "us", "nc", "sr", "city"])
    wa.add_argument("--lo", type=float, required=True, help="Study MP begin.")
    wa.add_argument("--hi", type=float, required=True, help="Study MP end.")
    wa.add_argument("--multilane", action="store_true",
                    help="SSSD counts as ROR (docs/12; off by default).")
    wa.add_argument("--override", action="append", default=[],
                    metavar="CRASH_ID:FIELD=VALUE",
                    help="Engineer correction, e.g. 107591377:l=5. The "
                         "analysis uses the corrected value and the Warrant "
                         "sheet paints that one cell the reserved yellow; the "
                         "fiche sheet keeps the original. Repeatable.")
    wa.add_argument("--study-type", default="hsip",
                    choices=[k for k, _ in _study_choices()],
                    help="Guard: only HSIP Package Analyses run warrants.")
    wa.add_argument("--import-out", dest="import_out",
                    help="Also write the ADD+RE milepost import here.")
    wa.add_argument("--padded", action="store_true",
                    help="Pad mileposts to three places (13.100) instead of "
                         "the stripped default (13.1).")
    wa.add_argument("--initial-ids", dest="initial_ids",
                    help="TEAAS ID export; runs the branch gate first and "
                         "refuses on any violation.")
    wa.add_argument("--no-save", dest="no_save", action="store_true",
                    help="Print the screen without touching the workbook.")
    wa.add_argument("--inclusive-minimums", dest="inclusive_minimums",
                    action="store_true",
                    help="Overview reading of the facility minimums: a count "
                         "equal to the minimum clears it (>=). Default "
                         "follows the warrant workbook, which tests strictly "
                         "greater than.")
    wa.add_argument("--report-out", dest="report_out",
                    help="Also write the analysis as report text (docs/05 "
                         "style): totals, warrants met and not, sub-section "
                         "findings, engineering notes.")
    wa.add_argument("--study", help="Study number for the report header.")
    wa.add_argument("--route", help="Route for the report header, e.g. US 74.")
    wa.add_argument("--county", help="County for the report header.")
    wa.set_defaults(func=_cmd_warrants)

    il = sub.add_parser(
        "import-list",
        help="Write the section-study TEAAS milepost import from a reviewed "
             "fiche workbook: ADD and RE crashes only, at their final "
             "mileposts, crash-ID order (docs/09).")
    il.add_argument("--workbook", required=True)
    il.add_argument("--sheet", help="Working sheet (default: the *_Fiche one).")
    il.add_argument("--out", required=True, help="e.g. 41000079305_Import.txt")
    il.add_argument("--padded", action="store_true",
                    help="Pad mileposts to three places instead of stripping "
                         "trailing zeros.")
    il.add_argument("--initial-ids", dest="initial_ids",
                    help="TEAAS ID export; runs the branch gate first.")
    il.set_defaults(func=_cmd_import_list)

    fl = sub.add_parser(
        "feature-list",
        help="Write a TEAAS feature-inclusion import from '<text>|<milepost>' "
             "lines (mile markers, curve PC/PI/PT estimates). Text is capped "
             "at 20 characters; the format is unverified against a live "
             "import (docs/09).")
    fl.add_argument("--pairs", required=True,
                    help="Text file, one '<text>|<milepost>' per line "
                         "(comma also accepted; # comments ignored).")
    fl.add_argument("--out", required=True)
    fl.add_argument("--truncate", action="store_true",
                    help="Shorten over-length text instead of refusing.")
    fl.set_defaults(func=_cmd_feature_list)

    cm = sub.add_parser(
        "crash-map",
        help="Build a self-contained GIS crash map (one HTML file, basemap "
             "tiles embedded, works offline) from a reviewed fiche "
             "workbook: crashes by status, RE/ADD moves drawn to the New "
             "MP, study limits, feature labels, optional shaded "
             "sub-section. Positions are approximate: the centreline is "
             "derived from the corridor's coded crashes.")
    cm.add_argument("--workbook", required=True)
    cm.add_argument("--route", required=True, help='e.g. "US 74".')
    cm.add_argument("--lo", type=float, required=True, help="Study MP begin.")
    cm.add_argument("--hi", type=float, required=True, help="Study MP end.")
    cm.add_argument("--out", help="Output HTML (default CrashMap.html).")
    cm.add_argument("--sheet", help="Working sheet (default: *_Fiche).")
    cm.add_argument("--coords",
                    help="DetailedFiche source (default: the workbook's own "
                         "DetailedFiche sheet).")
    cm.add_argument("--features-pairs", dest="features_pairs",
                    help="'<label>|<milepost>' lines (the feature-list "
                         "--pairs file): mile markers become MM chips, "
                         "everything else labelled points.")
    cm.add_argument("--window", help="Shade a sub-section, lo:hi.")
    cm.add_argument("--window-label", dest="window_label",
                    help="Label for the shaded sub-section.")
    cm.add_argument("--subtitle", help="Header note, e.g. 'F-2 met at 82%%'.")
    cm.add_argument("--county")
    cm.add_argument("--no-basemap", dest="no_basemap", action="store_true",
                    help="Skip tile downloads (points on a blank "
                         "background; offline builds and tests).")
    cm.add_argument("--diagram", action="store_true",
                    help="Collision-diagram style (the 41000078675 example): "
                         "the analysis crashes laddered off the roadway at "
                         "their final mileposts, severity letter in the "
                         "badge, Target/Other fill, road-condition ring.")
    cm.add_argument("--targets",
                    help="Comma-separated target crash types for the diagram "
                         "fill (default: the ROR warrant set).")
    cm.add_argument("--centerline",
                    help="Route geometry GeoJSON with vertex mileposts "
                         "([lon, lat, m], or 2D vertices with begin/end MP "
                         "properties; the NCDOT LRS export or a calibrated "
                         "trace). Replaces the crash-cloud centreline.")
    cm.add_argument("--diagram-round", dest="diagram_round", type=float,
                    default=0.1,
                    help="Diagram grouping increment in miles: 0.1 "
                         "(default, the example's MPRound1), 0.05 "
                         "(half-pitch columns, smaller symbols), or "
                         "0.01 (MPRound2; exact anchors, composed "
                         "reaches where crashes crowd).")
    cm.add_argument("--gis-out", dest="gis_out",
                    help="Also write the diagram as DATA for ArcGIS: a "
                         "GeoJSON (plus CSV twin) with every analysis "
                         "crash at its exact final milepost and the "
                         "MPRound1/05/2 + Offset grouping columns, with "
                         "the centreline, limits and window as "
                         "features.")
    cm.add_argument("--route-id", dest="route_id",
                    help="NCDOT RouteID carried into the GIS export "
                         "(e.g. 20000074075).")
    cm.set_defaults(func=_cmd_crash_map)

    sc = sub.add_parser(
        "assist-score",
        help="Score review-assist decide proposals against the ENGINEER'S "
             "reviewed statuses, which are ground truth: overall and "
             "per-status agreement plus every disagreement. Measures the "
             "assist, never the engineer.")
    sc.add_argument("--proposals", required=True, help="proposals.jsonl")
    sc.add_argument("--workbook", required=True,
                    help="The engineer's reviewed workbook.")
    sc.add_argument("--sheet", help="Reviewed sheet (default: the *_Fiche one).")
    sc.add_argument("--status-col", dest="status_col", type=int, default=9,
                    help="1-based status column (default 9, the fiche IS? "
                         "column).")
    sc.add_argument("--id-col", dest="id_col", type=int, default=12,
                    help="1-based crash-ID column (default 12).")
    sc.set_defaults(func=_cmd_assist_score)

    fw = sub.add_parser(
        "fiche-workbook",
        help="Assemble the study fiche workbook from the TEAAS exports: the "
             "Fiche Report becomes the Original Fiche sheet, the pipe-"
             "delimited ID export and the fiche crash IDs are cross-"
             "referenced on the ID sheet, and the Strip Analysis Report and "
             "Detailed Fiche come in as their own sheets.")
    fw.add_argument("--study", required=True, help="Study number, e.g. 41000079305.")
    fw.add_argument("--fiche", required=True, help="Fiche Report CSV.")
    fw.add_argument("--initial-study", help="Strip/Intersection Analysis Report CSV.")
    fw.add_argument("--initial-ids", help="Pipe-delimited TEAAS ID export.")
    fw.add_argument("--detailed", help="Detailed Fiche CSV (carries lat/lon).")
    fw.add_argument("--out", help="Output path (default <study>_Fiche.xlsx).")
    fw.add_argument("--study-type", default="evaluation",
                    choices=[k for k, _ in _study_choices()],
                    help="Fatal Crash Analysis, HSIP Package Analysis, or "
                         "Evaluation. HSIP deletes animal crashes and runs the "
                         "warrant screen (docs/12).")
    fw.add_argument("--features",
                    help="Features Report (.pdf/.txt/.csv). With --lo/--hi/"
                         "--route, runs the colour screen after the build: "
                         "IS for Initial Study crashes, ? for anything the "
                         "colours cannot clear, NIS otherwise, DEL for "
                         "animals on an HSIP study, and the grey "
                         "NOT-REVIEWED banner.")
    fw.add_argument("--lo", type=float, help="Study MP begin (screen).")
    fw.add_argument("--hi", type=float, help="Study MP end (screen).")
    fw.add_argument("--route", default="", help='Study route, e.g. "US 74".')
    fw.set_defaults(func=_cmd_fiche_workbook)

    td = sub.add_parser(
        "tsu-diagram",
        help="Render the TSU collision diagram sheet (11x17 HTML) from a "
             "TEAAS CollisionDiagramData export and a layout JSON. The "
             "layout's kind selects the sheet: 'intersection' draws the "
             "junction north up at its legs' true bearings (validated "
             "against 41000077750); anything else draws the section sheet.")
    td.add_argument("--data", required=True,
                    help="<WO>_CollisionDiagramData.txt (one row per unit).")
    td.add_argument("--layout", required=True, help="Layout JSON.")
    td.add_argument("--out", required=True, help="Output .html (print to "
                    "PDF at 17x11 in a browser or headless Chromium).")
    td.set_defaults(func=_cmd_tsu_diagram)

    d = sub.add_parser("doctor", help="Report available optional backends.")
    d.set_defaults(func=_cmd_doctor)
    return p


def _cmd_tsu_diagram(args) -> int:
    from .collision_diagram import build_diagram

    n = build_diagram(args.out, args.data, args.layout)
    print(f"Rendered {n} crash(es) -> {args.out}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
