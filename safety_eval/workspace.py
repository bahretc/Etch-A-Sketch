"""Per-study workspace: attach the inputs once, every page reads from them.

A study lives in one folder under the studies base directory
(``SAFETY_EVAL_STUDIES_DIR``, default ``./studies`` beside the app):

    studies/<study>/
        manifest.json   study type, params, and what is attached, by role
        inputs/         attached files, byte-for-byte as provided
        outputs/        everything the app builds for this study

The manifest records files by ROLE (``fiche_csv``, ``features_report``, ...)
so a page never guesses which csv is which: attaching replaces the file for
single-file roles and accumulates for multi-file roles, and ``path(role)``
hands a page its default. Params are the study facts the pages share
(route, milepost limits, urban/rural context, study point) so they are
typed once.

Nothing here deletes anything: removing a study or an attached file is a
file-manager job, on purpose, and the app only ever adds. The workspace is
also strictly optional; every page still runs from uploads alone.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime

#: role -> (label shown in the UI, accepts multiple files)
ROLES = {
    "fiche_csv": ("Fiche Report (.csv)", False),
    "initial_study_csv": ("Strip/Intersection Analysis Report (.csv)", False),
    "initial_ids_txt": ("TEAAS ID export (.txt)", False),
    "detailed_fiche_csv": ("Detailed Fiche (.csv)", False),
    "features_report": ("Features Report", True),
    "binder_index": ("Binder index (.json)", False),
    "collision_diagram_data": ("CollisionDiagramData (.txt)", False),
    "centerline": ("Route centerline GeoJSON", False),
    "before_ids": ("Before Crash ID list (.txt)", False),
    "after_ids": ("After Crash ID list (.txt)", False),
    "before_mp": ("Before milepost import (.txt)", False),
    "after_mp": ("After milepost import (.txt)", False),
    "setup_yaml": ("Set-up YAML", False),
    "results_yaml": ("Results YAML", False),
    "statuses_workbook": ("Workbook with reviewed Filtered Fiche", False),
    # outputs the app adopts back into the study
    "workbook": ("Study fiche workbook (.xlsx)", False),
    "reviewed_workbook": ("Reviewed workbook (.xlsx)", False),
    "evaluation_workbook": ("Populated Evaluation Workbook (.xlsx)", False),
}

ENV_BASE = "SAFETY_EVAL_STUDIES_DIR"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$")


def base_dir(base: str | None = None) -> str:
    return base or os.environ.get(ENV_BASE, "").strip() or "studies"


def list_studies(base: str | None = None) -> list[str]:
    """Study folder names under the base, newest manifest first."""
    root = base_dir(base)
    if not os.path.isdir(root):
        return []
    found = []
    for name in os.listdir(root):
        mf = os.path.join(root, name, "manifest.json")
        if os.path.isfile(mf):
            found.append((os.path.getmtime(mf), name))
    return [n for _, n in sorted(found, reverse=True)]


def _check_name(study: str) -> str:
    study = str(study).strip()
    if not _NAME_RE.match(study):
        raise ValueError(
            "study names are letters, digits, dots, dashes, underscores and "
            f"spaces (up to 80 characters), got {study!r}")
    return study


@dataclass
class Workspace:
    root: str
    manifest: dict

    # ---- lifecycle --------------------------------------------------------
    @classmethod
    def create(cls, study: str, study_type: str = "hsip",
               base: str | None = None) -> "Workspace":
        study = _check_name(study)
        root = os.path.join(base_dir(base), study)
        if os.path.isfile(os.path.join(root, "manifest.json")):
            raise ValueError(f"study {study} already exists; open it instead")
        os.makedirs(os.path.join(root, "inputs"), exist_ok=True)
        os.makedirs(os.path.join(root, "outputs"), exist_ok=True)
        ws = cls(root=root, manifest={
            "study": study, "study_type": study_type,
            "created": _now(), "files": {}, "params": {}})
        ws.save()
        return ws

    @classmethod
    def open(cls, study: str, base: str | None = None) -> "Workspace":
        study = _check_name(study)
        root = os.path.join(base_dir(base), study)
        mf = os.path.join(root, "manifest.json")
        with open(mf, encoding="utf-8") as fh:
            manifest = json.load(fh)
        return cls(root=root, manifest=manifest)

    def save(self) -> None:
        self.manifest["updated"] = _now()
        path = os.path.join(self.root, "manifest.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.manifest, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)

    # ---- identity ---------------------------------------------------------
    @property
    def study(self) -> str:
        return self.manifest.get("study", os.path.basename(self.root))

    @property
    def study_type(self) -> str:
        return self.manifest.get("study_type", "hsip")

    # ---- files by role ----------------------------------------------------
    def attach(self, role: str, filename: str, data: bytes) -> str:
        """Store one input file under the role; returns its absolute path."""
        dest = self._store("inputs", role, os.path.basename(filename), data)
        return dest

    def attach_path(self, role: str, src: str) -> str:
        with open(src, "rb") as fh:
            return self.attach(role, os.path.basename(src), fh.read())

    def adopt_output(self, role: str, src: str, name: str | None = None) -> str:
        """Record a built file as this study's output for the role.

        A file already inside the study folder is recorded in place; one
        outside is copied into ``outputs/`` first (as ``name`` when given).
        """
        src = os.path.abspath(src)
        if src.startswith(os.path.abspath(self.root) + os.sep):
            self._record(role, os.path.relpath(src, self.root))
            self.save()
            return src
        with open(src, "rb") as fh:
            return self._store("outputs", role,
                               os.path.basename(name or src), fh.read())

    def _store(self, area: str, role: str, name: str, data: bytes) -> str:
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}; expected one of "
                             + ", ".join(sorted(ROLES)))
        dest = os.path.join(self.root, area, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        self._record(role, os.path.join(area, name))
        self.save()
        return dest

    def _record(self, role: str, rel: str) -> None:
        _, multiple = ROLES[role]
        files = self.manifest.setdefault("files", {})
        if multiple:
            kept = [p for p in files.get(role, []) if p != rel]
            files[role] = kept + [rel]
        else:
            files[role] = [rel]

    def paths(self, role: str) -> list[str]:
        """Absolute paths attached under the role (missing files dropped)."""
        out = []
        for rel in self.manifest.get("files", {}).get(role, []):
            p = os.path.join(self.root, rel)
            if os.path.exists(p):
                out.append(p)
        return out

    def path(self, role: str) -> str | None:
        found = self.paths(role)
        return found[-1] if found else None

    @property
    def outputs_dir(self) -> str:
        d = os.path.join(self.root, "outputs")
        os.makedirs(d, exist_ok=True)
        return d

    # ---- shared study facts ----------------------------------------------
    def param(self, key: str, default=None):
        return self.manifest.get("params", {}).get(key, default)

    def set_params(self, **values) -> None:
        """Record study facts (route, mp_lo, mp_hi, context, ...); None is
        "no change", so pages can pass everything they know each run."""
        params = self.manifest.setdefault("params", {})
        changed = False
        for k, v in values.items():
            if v is not None and params.get(k) != v:
                params[k] = v
                changed = True
        if changed:
            self.save()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def copy_into(ws: Workspace, role: str, uploaded) -> str | None:
    """Attach a Streamlit upload (or None) to the workspace; path or None."""
    if uploaded is None:
        return None
    return ws.attach(role, uploaded.name, uploaded.getbuffer().tobytes())
