"""End-to-end orchestration: fiche + assignment -> completed evaluation."""
from __future__ import annotations

from dataclasses import dataclass

from .analysis import evaluate
from .assignment import load_assignment
from .classify import classify_all
from .config import Config
from .fiche_parser import parse_fiche
from .models import Assignment, EvaluationResult
from .periods import build_periods
from .report import render_markdown, write_markdown, write_workbook


@dataclass
class Inputs:
    fiche: str            # path or raw text
    assignment: Assignment
    fmt: str = "auto"     # fiche format: auto|csv|teaas|pdf


def run(
    fiche_source: str,
    assignment: Assignment,
    cfg: Config | None = None,
    fmt: str = "auto",
) -> EvaluationResult:
    """Run the full pipeline and return the evaluation result."""
    cfg = cfg or Config.load()
    crashes = parse_fiche(fiche_source, fmt=fmt)
    periods = build_periods(assignment, cfg)
    classify_all(crashes, assignment, periods, cfg)
    return evaluate(crashes, assignment, periods, cfg)


def run_from_files(
    fiche_path: str,
    assignment_path: str,
    config_path: str | None = None,
    fmt: str = "auto",
) -> EvaluationResult:
    cfg = Config.load(config_path)
    assignment = load_assignment(assignment_path)
    return run(fiche_path, assignment, cfg=cfg, fmt=fmt)


__all__ = [
    "run", "run_from_files", "Inputs",
    "write_workbook", "write_markdown", "render_markdown",
]
