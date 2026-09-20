"""File intake: recognise a dropped file and attach it under its study role.

The engineer drops everything TEAAS and the field gave them into one zone;
nothing asks "which csv is this". Each file is recognised from what it IS
(the TEAAS banner, the header row, the PDF's first page, the workbook's
sheet names), never from its name alone, and lands under the workspace ROLE
the pages read from (:mod:`safety_eval.workspace`). A file the sniff cannot
place is offered back with the closest choices; nothing is guessed silently
and nothing is ever deleted.
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field

from safety_eval.workspace import ROLES, Workspace

#: A short, engineer-facing description of what the drop zone recognises.
RECOGNISED = (
    "Fiche Report, Strip or Intersection Analysis Report, DetailedFiche and "
    "TEAAS ID export (csv/txt); Features Report (pdf/txt); crash reports and "
    "scanned binders (pdf/tif); fatal slips (pdf); fiche, reviewed and "
    "Evaluation workbooks (xlsx); set-up and results YAML; route centerline "
    "GeoJSON; maps and memos.")

#: roles that are the same kind of file, so the engineer picks between them
_AMBIGUOUS = {
    "milepost_import": (("before_mp", "after_mp"), "TEAAS milepost import (.txt)"),
    "crash_id_list": (("before_ids", "after_ids"), "Crash ID list (5-col .txt)"),
}


@dataclass
class Detection:
    """What a dropped file was recognised as."""
    role: str | None            # workspace role, or None when unsure
    label: str                  # what to call it in the UI
    why: str                    # the evidence, in words
    choices: tuple = field(default_factory=tuple)   # roles to pick between

    @property
    def sure(self) -> bool:
        return self.role is not None


def _text_head(data: bytes, n: int = 6000) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data[:n].decode(enc)
        except UnicodeDecodeError:
            continue
    return data[:n].decode("latin-1", errors="replace")


def _pdf_first_page(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if not reader.pages:
            return ""
        return reader.pages[0].extract_text() or ""
    except Exception:                                # noqa: BLE001 - sniff only
        return ""


def _xlsx_sheets(data: bytes) -> list[str]:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
        names = list(wb.sheetnames)
        wb.close()
        return names
    except Exception:                                # noqa: BLE001 - sniff only
        return []


def _csv_or_txt(name: str, head: str) -> Detection:
    flat = " ".join(head.split())
    low = flat.lower()
    if "fiche report" in low and "detailed" not in low[:300]:
        return Detection("fiche_csv", ROLES["fiche_csv"][0],
                         "TEAAS Fiche Report banner")
    if "analysis report" in low[:400]:
        which = "Intersection" if "intersection analysis" in low else "Strip"
        return Detection("initial_study_csv", ROLES["initial_study_csv"][0],
                         f"TEAAS {which} Analysis Report banner")
    if "features report" in low[:400]:
        return Detection("features_report", ROLES["features_report"][0],
                         "TEAAS Features Report banner")
    first = head.splitlines()[0].strip() if head.strip() else ""
    if first.upper().startswith("CRASH ID|"):
        return Detection("initial_ids_txt", ROLES["initial_ids_txt"][0],
                         "pipe-delimited CRASH ID export")
    cols = [c.strip().strip('"').lower() for c in first.split(",")]
    if "latitude" in cols and "longitude" in cols and "crash id" in cols:
        return Detection("detailed_fiche_csv", ROLES["detailed_fiche_csv"][0],
                         "Crash ID with Latitude/Longitude columns")
    if "county code" in cols and any("y-line" in c for c in cols):
        return Detection(None, "DetailedFiche parameters",
                         "the DetailedFiche parameters sheet; the pages do "
                         "not need it", choices=("detailed_fiche_csv",))
    lines = [ln for ln in head.splitlines() if ln.strip()][:12]
    if lines and all(re.match(r"^\d{7,9}\|?\s*\d+(\.\d+)?\s*$", ln.strip())
                     for ln in lines):
        roles, label = _AMBIGUOUS["milepost_import"]
        return Detection(None, label, "crash id and milepost per line; "
                         "before or after period?", choices=roles)
    if lines and all(len(re.split(r"[\t ,]+", ln.strip())) == 5
                     and re.match(r"^[\d\t ,]+$", ln.strip()) for ln in lines):
        roles, label = _AMBIGUOUS["crash_id_list"]
        return Detection(None, label, "five numbers per line; before or "
                         "after period?", choices=roles)
    if "collision" in low and "diagram" in low:
        return Detection("collision_diagram_data",
                         ROLES["collision_diagram_data"][0],
                         "CollisionDiagramData header")
    if name.lower().endswith(".txt") and ("feature" in low or " mp " in low):
        return Detection("features_report", ROLES["features_report"][0],
                         "feature listing text")
    return Detection(None, "Text file", "no TEAAS banner or known header",
                     choices=("fiche_csv", "initial_study_csv",
                              "detailed_fiche_csv", "initial_ids_txt",
                              "features_report", "collision_diagram_data"))


def _pdf(name: str, data: bytes) -> Detection:
    text = " ".join(_pdf_first_page(data).split())
    low = text.lower()
    if "features report" in low:
        return Detection("features_report", ROLES["features_report"][0],
                         "TEAAS Features Report on page 1")
    if "dmv-349" in low or "dmv 349" in low or "crash report" in low:
        return Detection("crash_report", ROLES["crash_report"][0],
                         "DMV-349 form on page 1")
    if "fatal" in low and ("slip" in low or "investigation" in low
                           or "crash" in low):
        return Detection("fatal_slip", ROLES["fatal_slip"][0],
                         "fatal crash slip text on page 1")
    if "disclaimer" in low:
        return Detection(None, "Disclaimer PDF",
                         "the data disclaimer; the Finish page picks it up "
                         "from the package folder")
    if not text.strip():
        return Detection("crash_report", ROLES["crash_report"][0],
                         "scanned PDF with no text layer; treated as a "
                         "crash report binder")
    return Detection(None, "PDF", "page 1 names no known TEAAS or DMV form",
                     choices=("crash_report", "features_report", "fatal_slip",
                              "location_map"))


def _xlsx(name: str, data: bytes) -> Detection:
    sheets = _xlsx_sheets(data)
    if not sheets:
        return Detection(None, "Workbook", "could not read the sheet list",
                         choices=("workbook", "reviewed_workbook",
                                  "evaluation_workbook", "statuses_workbook",
                                  "field_investigation"))
    joined = " ".join(sheets).lower()
    if any(s.lower().endswith("_fiche") for s in sheets):
        if "review" in name.lower():
            return Detection("reviewed_workbook",
                             ROLES["reviewed_workbook"][0],
                             "study fiche sheet, named as reviewed")
        return Detection("workbook", ROLES["workbook"][0],
                         "study fiche working sheet")
    if "filtered fiche" in joined or "set-up" in joined or "setup" in joined \
            or "results" in joined:
        return Detection("evaluation_workbook",
                         ROLES["evaluation_workbook"][0],
                         "Evaluation Workbook sheets")
    if "field" in joined and "investigation" in joined:
        return Detection("field_investigation",
                         ROLES["field_investigation"][0],
                         "Field Investigation sheets")
    return Detection(None, "Workbook", "sheets: " + ", ".join(sheets[:6]),
                     choices=("workbook", "reviewed_workbook",
                              "evaluation_workbook", "statuses_workbook"))


def _yaml(name: str, head: str) -> Detection:
    low = head.lower()
    if re.search(r"^\s*(aadt|set[-_ ]?up|legs?|periods?)\s*:", low, re.M):
        return Detection("setup_yaml", ROLES["setup_yaml"][0],
                         "set-up keys (aadt, legs, periods)")
    if re.search(r"^\s*(results?|before|after|epdo|crash_rate)\s*:", low, re.M):
        return Detection("results_yaml", ROLES["results_yaml"][0],
                         "results keys (before, after, epdo)")
    return Detection(None, "YAML", "no set-up or results keys at top level",
                     choices=("setup_yaml", "results_yaml"))


def sniff(name: str, data: bytes) -> Detection:
    """Recognise one dropped file from its content (name breaks ties only)."""
    ext = os.path.splitext(name)[1].lower()
    if ext in (".csv", ".txt", ".tsv", ".dat"):
        return _csv_or_txt(name, _text_head(data))
    if ext == ".pdf":
        return _pdf(name, data)
    if ext in (".tif", ".tiff"):
        return Detection("crash_report", ROLES["crash_report"][0],
                         "scanned TIFF binder")
    if ext in (".xlsx", ".xlsm"):
        return _xlsx(name, data)
    if ext in (".yaml", ".yml"):
        return _yaml(name, _text_head(data))
    if ext == ".json":
        head = _text_head(data, 2000)
        if '"crashes"' in head and '"dpi"' in head:
            return Detection("binder_index", ROLES["binder_index"][0],
                             "binder index keys")
        return Detection(None, "JSON", "not a binder index",
                         choices=("binder_index", "centerline"))
    if ext == ".geojson":
        return Detection("centerline", ROLES["centerline"][0],
                         "GeoJSON route centerline")
    if ext == ".jsonl":
        return Detection("train_dataset", ROLES["train_dataset"][0],
                         "JSON lines drafting set")
    if ext in (".html", ".htm"):
        return Detection("crash_map", ROLES["crash_map"][0], "HTML map")
    if ext in (".docx", ".md"):
        return Detection("analysis_memo", ROLES["analysis_memo"][0],
                         "memo document")
    if ext in (".png", ".jpg", ".jpeg"):
        return Detection("location_map", ROLES["location_map"][0],
                         "image; the provided location map")
    if ext == ".zip":
        return Detection(None, "Package zip", "load it on the Finish "
                         "Package page; it is not a study input")
    return Detection(None, f"{ext or 'file'} file",
                     "no rule for this file type")


def sniff_path(path: str) -> Detection:
    with open(path, "rb") as fh:
        return sniff(os.path.basename(path), fh.read())


@dataclass
class Attached:
    name: str
    role: str
    path: str


def attach_all(ws: Workspace, files, roles: dict[str, str] | None = None
               ) -> tuple[list[Attached], list[tuple[str, Detection]]]:
    """Attach ``(name, bytes)`` pairs under their sniffed roles.

    ``roles`` overrides the sniff per file name (the engineer's pick in the
    UI). Returns what was attached and what was skipped with its detection,
    so the UI can say both in words.
    """
    done, skipped = [], []
    for name, data in files:
        det = sniff(name, data)
        role = (roles or {}).get(name) or det.role
        if not role or role == "skip":
            skipped.append((name, det))
            continue
        path = ws.attach(role, name, data)
        done.append(Attached(name, role, path))
    return done, skipped


#: The roles a study needs before each core step can run, for the checklist.
CHECKLIST = (
    ("fiche_csv", "Fiche Report", "builds the working sheet"),
    ("initial_study_csv", "Analysis Report", "the Initial Study sheet"),
    ("initial_ids_txt", "TEAAS ID export", "marks the Initial Study crashes"),
    ("detailed_fiche_csv", "DetailedFiche", "coordinates for placing crashes"),
    ("features_report", "Features Report", "the colour screen"),
    ("crash_report", "Crash reports", "the report review"),
)
