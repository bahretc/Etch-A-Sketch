"""safety_eval — automate NCDOT before/after safety evaluations.

Pipeline: TEAAS fiche (+ OCR for PDFs) + assignment -> parse -> classify
(in-study, period, target crash types) -> before/after analysis -> Excel
workbook + Markdown report.
"""
from .config import Config
from .models import Assignment, Crash, EvaluationResult
from .pipeline import run, run_from_files

__version__ = "0.1.0"
__all__ = ["Config", "Assignment", "Crash", "EvaluationResult", "run", "run_from_files"]
