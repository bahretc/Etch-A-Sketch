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

    d = sub.add_parser("doctor", help="Report available optional backends.")
    d.set_defaults(func=_cmd_doctor)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
