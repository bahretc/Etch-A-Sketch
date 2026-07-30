"""Evaluation-archive manifest builder (docs/10).

Turns the raw archive of past evaluations into the dataset record the
report-drafting layer will train and verify on:

* one meta record per evaluation (work order), classified for
  stratification: analysis type, countermeasure family, county/division,
  completion year, target count where known;
* companion clustering: evaluations that share an assignment email thread
  (SS-6002M / SS-6002AS arrived as Assignment #22 & #23 in ONE email) are
  one cluster and always land in the same split half (docs/10: one in each
  half is leakage);
* a deterministic, stratified 50/50 train/verify split, assigned once and
  recorded (hash-ordered within each stratum, so re-running never reshuffles
  what was already assigned);
* a manifest.jsonl whose lines carry the Drive file IDs of the key files
  (deliverable workbooks, fiches, assignment emails), so later phases fetch
  exactly what they need on demand;
* explicit flags for anything missing (no email, no workbook, no fiche) -
  a thin folder is a finding, not a silent gap.

Inputs are the folder inventories (one JSON per work order, produced by the
Drive enumeration) and the downloaded assignment emails; nothing here talks
to Drive itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field

from .assignment_email import ParsedAssignment, parse_assignment_email

#: countermeasure text -> family, first match wins (order matters: a rumble
#: strip project usually mentions markings too)
_FAMILIES = (
    ("rumble", "rumble-strips"),
    ("vewf", "flashers-vewf"),
    ("vehicle entering", "flashers-vewf"),
    ("flasher", "flashers-vewf"),
    ("all-way stop", "awsc"),
    ("all way stop", "awsc"),
    ("awsc", "awsc"),
    ("roundabout", "roundabout"),
    ("signal", "signal"),
    ("turn lane", "turn-lanes"),
    ("left over", "geometry"),
    ("reduced conflict", "geometry"),
    ("resurfac", "resurfacing"),
    ("high friction", "surface-treatment"),
    ("skid", "surface-treatment"),
    ("marking", "markings"),
    ("thermoplastic", "markings"),
    ("chevron", "signing"),
    ("sign", "signing"),
    ("guardrail", "barrier"),
    ("cable", "barrier"),
    ("shoulder", "shoulders"),
    ("lighting", "lighting"),
)

_WO_RE = re.compile(r"(4\d{9,10})")
_PROJECT_RE = re.compile(r"\b(\d{2}-\d{2}-\d{3,6})\b")
_TIP_RE = re.compile(r"\(\s*(?:TIP\s*#?)?\s*((?:SS|W|HE|R|U|B)-[0-9A-Z]+)\s*\)")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def classify_family(text: str) -> str:
    low = (text or "").lower()
    for needle, family in _FAMILIES:
        if needle in low:
            return family
    return "other"


@dataclass
class EvaluationMeta:
    wo: str
    title: str = ""
    folder_ids: list = field(default_factory=list)
    project_id: str = ""
    tip: str = ""
    analysis_type: str = "unknown"        # section | intersection | unknown
    targets: int | None = None
    countermeasure: str = ""
    countermeasure_family: str = "other"
    county: str = ""
    division: str = ""
    completed: int | None = None
    companions: list = field(default_factory=list)
    split: str = ""
    #: where the assumption data came from (per the engineer, 2026-07):
    #: 'msg' = the assignment email thread, the AUTHORITATIVE record with
    #: NCDOT's feedback incorporated; 'docx-draft' = VHB's initial
    #: assumptions document BEFORE feedback - used for classification only
    #: (countermeasure family, county, study type), never as final
    #: assumptions; 'none' = no parseable source.
    assumptions_source: str = "none"
    flags: list = field(default_factory=list)
    files: dict = field(default_factory=dict)   # role -> [{path,id,size}]

    def record(self) -> dict:
        return asdict(self)


def _norm_wo(name: str) -> str:
    m = _WO_RE.search(name)
    return m.group(1) if m else name


def load_inventories(inventory_dir: str) -> dict[str, dict]:
    """{wo: merged inventory}; *_1of2/_2of2 folders merge into one WO."""
    merged: dict[str, dict] = {}
    for fn in sorted(os.listdir(inventory_dir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(inventory_dir, fn), encoding="utf-8") as fh:
            inv = json.load(fh)
        wo = _norm_wo(fn)
        if wo in merged:
            merged[wo]["files"].extend(inv.get("files", []))
            merged[wo]["folder_ids"].append(inv.get("folder_id", ""))
            merged[wo]["split_folders"] = True
        else:
            merged[wo] = {
                "title": inv.get("title", fn),
                "folder_ids": [inv.get("folder_id", "")],
                "files": list(inv.get("files", [])),
            }
    return merged


def _pick(files: list[dict], *patterns: str) -> list[dict]:
    out = []
    for f in files:
        name = (f.get("title") or os.path.basename(f.get("path", ""))).lower()
        if any(re.search(p, name) for p in patterns):
            out.append({"path": f.get("path"), "id": f.get("id"),
                        "size": f.get("size")})
    return out


def _email_blocks(emails_dir: str, wo: str) -> dict[str, ParsedAssignment]:
    """Parse every downloaded email for a WO; {order_id: block}."""
    out: dict[str, ParsedAssignment] = {}
    if not os.path.isdir(emails_dir):
        return out
    for fn in sorted(os.listdir(emails_dir)):
        if not fn.startswith(f"{wo}__"):
            continue
        path = os.path.join(emails_dir, fn)
        try:
            parsed = parse_assignment_email(path)
        except Exception:                              # noqa: BLE001
            continue
        for pa in parsed.values():
            key = pa.order_id or f"{wo}#{pa.number}"
            out.setdefault(key, pa)
    return out


def _docx_block(docx_dir: str | None, wo: str) -> ParsedAssignment | None:
    """Parse the archived 'Assumptions Email - ....docx' when present."""
    if not docx_dir or not os.path.isdir(docx_dir):
        return None
    path = os.path.join(docx_dir, f"{wo}__assumptions.docx")
    if not os.path.exists(path):
        return None
    try:
        from .assignment_email import parse_assumptions_docx
        return parse_assumptions_docx(path)
    except Exception:                                  # noqa: BLE001
        return None


def build_meta(wo: str, inv: dict, emails_dir: str,
               docx_dir: str | None = None) -> EvaluationMeta:
    meta = EvaluationMeta(wo=wo, title=inv.get("title", ""),
                          folder_ids=inv.get("folder_ids", []))
    title = meta.title
    m = _PROJECT_RE.search(title)
    if m:
        meta.project_id = m.group(1)
    m = _TIP_RE.search(title)
    if m:
        meta.tip = m.group(1)
    if inv.get("split_folders"):
        meta.flags.append("split-folders-merged")

    files = inv.get("files", [])
    meta.files = {
        "workbooks": _pick(files, r"evaluation workbook.*\.xlsx$",
                           r"\.xlsm$",
                           r"(section|intersection).*\.xlsx$"),
        "fiche_workbooks": _pick(files, r"fiche.*\.xlsx$"),
        "emails": _pick(files, r"\.msg$", r"\.eml$"),
        "fiche_csv": _pick(files, r"fiche.*\.csv$", r"\.csv$"),
        "id_lists": _pick(files, r"crashid.*\.txt$", r"_id\.txt$",
                          r"import.*\.txt$"),
        "reports": _pick(files, r"complete ?eval.*\.pdf$", r"web\.pdf$",
                         r"evaluation.*\.pdf$"),
        # TEAAS Features Reports: the route inventory that turns a report's
        # "N miles from <route>" into a milepost (location.py). Named either
        # way round: FeaturesReport_US13.pdf or US13_FeaturesReport.pdf.
        "features": _pick(files, r"features ?report.*\.pdf$",
                          r"features ?import ?list.*\.txt$",
                          r"features.*\.pdf$"),
    }
    if not files:
        meta.flags.append("empty-folder")
    if not meta.files["workbooks"] and not meta.files["fiche_workbooks"]:
        meta.flags.append("no-workbook")
    if not meta.files["emails"]:
        meta.flags.append("no-assignment-email")
    if not meta.files["reports"]:
        meta.flags.append("no-report-pdf")
    if not meta.files["features"]:
        meta.flags.append("no-features-report")

    # classification from the workbook filename first (ground truth of what
    # was delivered), the email second
    wb_names = " ".join((f["path"] or "") for f in meta.files["workbooks"])
    if re.search(r"intersection", wb_names, re.I):
        meta.analysis_type = "intersection"
    elif re.search(r"section", wb_names, re.I):
        meta.analysis_type = "section"

    blocks = _email_blocks(emails_dir, wo)
    pa = blocks.get(wo)
    if pa is None and blocks:
        # email whose blocks are keyed by other order ids: take the one that
        # matches this WO if present under a synthetic key, else none
        pa = next((b for k, b in blocks.items() if k.startswith(f"{wo}#")),
                  None)
    if pa is not None:
        meta.assumptions_source = "msg"
    else:
        # fall back to the archived assumptions .docx for CLASSIFICATION
        # only: it is VHB's initial draft sent to NCDOT, without their
        # feedback or later changes, so it must never be treated as the
        # final assumptions record (engineer's direction, 2026-07)
        pa = _docx_block(docx_dir, wo)
        if pa is not None:
            meta.assumptions_source = "docx-draft"
            meta.flags.append("assumptions-draft-only")
    if pa is not None:
        meta.countermeasure = pa.countermeasure_text()
        meta.county = pa.county
        meta.division = pa.division
        if not meta.project_id and pa.project_id:
            meta.project_id = pa.project_id
        if not meta.tip and pa.tip:
            meta.tip = pa.tip
        if meta.analysis_type == "unknown":
            if pa.study_type:
                meta.analysis_type = ("intersection"
                                      if "intersection" in pa.study_type.lower()
                                      else "section")
            else:
                meta.analysis_type = ("intersection" if pa.intersection_study
                                      else "section")
        m = _YEAR_RE.search(pa.completion or "")
        if m:
            meta.completed = int(m.group(1))
        elif "construction" in pa.periods:
            meta.completed = pa.periods["construction"][1].year
        two_target_hint = any("target-2" in n.lower() or "second target" in
                              n.lower() for n in pa.target_notes)
        meta.targets = 2 if two_target_hint else 1
    else:
        meta.flags.append("email-not-parsed")

    meta.countermeasure_family = classify_family(
        meta.countermeasure or meta.title)
    if meta.analysis_type == "unknown":
        meta.flags.append("analysis-type-unknown")
    return meta


# --------------------------------------------------------------------------- #
# companion clustering and the split
# --------------------------------------------------------------------------- #
def companion_clusters(metas: dict[str, EvaluationMeta],
                       emails_dir: str) -> list[set[str]]:
    """Cluster WOs that share an assignment email thread.

    Two signals: an email file under one WO whose parsed blocks carry the
    order IDs of other archived WOs, and byte-identical email files saved
    under different WOs.
    """
    parent: dict[str, str] = {wo: wo for wo in metas}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_hash: dict[str, str] = {}
    if os.path.isdir(emails_dir):
        for fn in sorted(os.listdir(emails_dir)):
            wo = fn.split("__", 1)[0]
            if wo not in metas:
                continue
            path = os.path.join(emails_dir, fn)
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            if digest in by_hash:
                union(wo, by_hash[digest])
            else:
                by_hash[digest] = wo
            try:
                parsed = parse_assignment_email(path)
            except Exception:                          # noqa: BLE001
                continue
            for pa in parsed.values():
                other = pa.order_id
                if other and other in metas and other != wo:
                    union(wo, other)

    clusters: dict[str, set[str]] = {}
    for wo in metas:
        clusters.setdefault(find(wo), set()).add(wo)
    return sorted(clusters.values(), key=lambda c: min(c))


def assign_split(metas: dict[str, EvaluationMeta],
                 clusters: list[set[str]]) -> None:
    """Deterministic stratified 50/50 by companion cluster (docs/10).

    Clusters are bucketed by stratum (analysis type + countermeasure
    family), ordered by a stable hash of their smallest WO, and dealt
    alternately train/verify within each bucket, tracking the global
    balance so the halves stay near 50/50 overall. Companions always move
    together, and the hash ordering means adding new evaluations later
    never reshuffles the ones already assigned within their bucket prefix.
    """
    def stratum(cluster: set[str]) -> tuple:
        lead = metas[min(cluster)]
        return (lead.analysis_type, lead.countermeasure_family)

    buckets: dict[tuple, list[set[str]]] = {}
    for cluster in clusters:
        buckets.setdefault(stratum(cluster), []).append(cluster)

    total = {"train": 0, "verify": 0}
    for key in sorted(buckets):
        ordered = sorted(
            buckets[key],
            key=lambda c: hashlib.sha256(min(c).encode()).hexdigest())
        local = {"train": 0, "verify": 0}
        for cluster in ordered:
            if local["train"] < local["verify"]:
                half = "train"
            elif local["verify"] < local["train"]:
                half = "verify"
            elif total["train"] < total["verify"]:
                half = "train"
            elif total["verify"] < total["train"]:
                half = "verify"
            else:                      # full tie: hash parity decides
                digest = hashlib.sha256(min(cluster).encode()).hexdigest()
                half = "train" if int(digest, 16) % 2 == 0 else "verify"
            for wo in cluster:
                metas[wo].split = half
                metas[wo].companions = sorted(set(cluster) - {wo})
                local[half] += 1
                total[half] += 1


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def load_folder_inventories(inventory_dir: str) -> dict[str, dict]:
    """Load per-folder inventory JSONs of the newer enumeration format
    ({"folder": "WO-<digits> <project> (<TIP>)", "id": ..., "files":
    [{path,id,name,mimeType,size}]}) into the same shape
    ``load_inventories`` produces. Folders sharing a WO number (multi
    -project assignments) merge into one evaluation record.

    The WO is taken as the FULL digit run after "WO-" so a nonstandard
    id (e.g. the 12-digit 410000749019) is preserved verbatim for the
    engineer to resolve rather than silently truncated by ``_WO_RE``.
    """
    merged: dict[str, dict] = {}
    for fn in sorted(os.listdir(inventory_dir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(inventory_dir, fn), encoding="utf-8") as fh:
            inv = json.load(fh)
        title = inv.get("folder") or fn[:-5]
        m = re.match(r"WO-(\d+)", title)
        if not m:
            continue                       # not a WO folder (e.g. Documents)
        wo = m.group(1)
        files = [{"path": f.get("path"), "id": f.get("id"),
                  "size": f.get("size"), "title": f.get("name")}
                 for f in inv.get("files", [])
                 if f.get("mimeType") != "application/vnd.google-apps.folder"
                 and not (f.get("name") or "").startswith("~$")]
        if wo in merged:
            merged[wo]["files"].extend(files)
            merged[wo]["folder_ids"].append(inv.get("id", ""))
            merged[wo]["title"] += " + " + title
            merged[wo]["split_folders"] = True
        else:
            merged[wo] = {"title": title,
                          "folder_ids": [inv.get("id", "")],
                          "files": files}
    return merged


def _flag_stray_workbooks(meta: EvaluationMeta) -> None:
    """Reconcile workbook filenames against the folder's project code.

    Two distinct situations, distinguished by whether ANY workbook matches
    the folder's project code:

    * The folder has its own deliverable AND an extra one named for a
      different project (observed: a 13-18-210 workbook inside
      WO-41000075960 next to its own 10-19-230). The extras are moved to
      ``stray_workbooks`` and flagged, so nothing downstream treats a
      neighbour's deliverable as this evaluation's.
    * NO workbook matches the folder's project code (observed:
      WO-41000073336 titled 02-17-43501 whose workbook and both emails say
      02-17-45301 - a single-digit folder-title typo). Here the filenames,
      not the folder title, are the reliable identity, so the workbooks are
      KEPT as this WO's own and the disagreement is flagged rather than
      stranding the evaluation with zero workbooks.
    """
    own = set(_PROJECT_RE.findall(meta.title))
    if not own:
        return
    matching, nonmatching = [], []
    for f in meta.files.get("workbooks", []):
        name = os.path.basename(f.get("path") or "")
        codes = set(_PROJECT_RE.findall(name))
        (nonmatching if codes and not (codes & own) else matching).append(f)
    if not nonmatching:
        return
    if matching:
        meta.files["workbooks"] = matching
        meta.files["stray_workbooks"] = nonmatching
        meta.flags.append("stray-workbook")
    else:
        meta.flags.append("folder-project-mismatch")


def assign_split_frozen(metas: dict[str, EvaluationMeta],
                        clusters: list[set[str]],
                        existing: list[dict]) -> None:
    """Deal ONLY the new clusters, keeping every existing assignment
    frozen (docs/10: the split is assigned once and recorded).

    The per-stratum and global counters are seeded from the existing
    manifest records, so new clusters balance against what is already
    assigned instead of re-dealing it.
    """
    total = {"train": 0, "verify": 0}
    local: dict[tuple, dict[str, int]] = {}
    for rec in existing:
        half = rec.get("split")
        if half not in total:
            continue
        total[half] += 1
        key = (rec.get("analysis_type"), rec.get("countermeasure_family"))
        local.setdefault(key, {"train": 0, "verify": 0})[half] += 1

    def stratum(cluster: set[str]) -> tuple:
        lead = metas[min(cluster)]
        return (lead.analysis_type, lead.countermeasure_family)

    buckets: dict[tuple, list[set[str]]] = {}
    for cluster in clusters:
        buckets.setdefault(stratum(cluster), []).append(cluster)

    for key in sorted(buckets):
        counts = local.setdefault(key, {"train": 0, "verify": 0})
        ordered = sorted(
            buckets[key],
            key=lambda c: hashlib.sha256(min(c).encode()).hexdigest())
        for cluster in ordered:
            if counts["train"] < counts["verify"]:
                half = "train"
            elif counts["verify"] < counts["train"]:
                half = "verify"
            elif total["train"] < total["verify"]:
                half = "train"
            elif total["verify"] < total["train"]:
                half = "verify"
            else:
                digest = hashlib.sha256(min(cluster).encode()).hexdigest()
                half = "train" if int(digest, 16) % 2 == 0 else "verify"
            for wo in cluster:
                metas[wo].split = half
                metas[wo].companions = sorted(set(cluster) - {wo})
                counts[half] += 1
                total[half] += 1


def extend_manifest(inventory_dir: str, emails_dir: str, output_dir: str,
                    docx_dir: str | None = None) -> dict:
    """Add a new batch of evaluations to an existing archive manifest.

    Existing records (and their split assignments) are carried over
    byte-for-byte; new WOs get meta built from the per-folder inventories
    and a frozen-split assignment. Returns the same summary shape as
    ``build_manifest`` plus the list of newly added WOs.
    """
    import yaml

    manifest_path = os.path.join(output_dir, "manifest.jsonl")
    existing: list[dict] = []
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            existing = [json.loads(l) for l in fh if l.strip()]
    known = {rec["wo"] for rec in existing}

    inventories = {wo: inv
                   for wo, inv in load_folder_inventories(inventory_dir).items()
                   if wo not in known}
    metas = {wo: build_meta(wo, inv, emails_dir, docx_dir=docx_dir)
             for wo, inv in inventories.items()}
    for meta in metas.values():
        _flag_stray_workbooks(meta)
        if len(meta.wo) != 11:
            meta.flags.append("wo-nonstandard-length")
    clusters = companion_clusters(metas, emails_dir)
    assign_split_frozen(metas, clusters, existing)

    os.makedirs(os.path.join(output_dir, "meta"), exist_ok=True)
    records = existing + [metas[wo].record() for wo in sorted(metas)]
    with open(manifest_path, "w", encoding="utf-8") as mf:
        for record in records:
            mf.write(json.dumps(record) + "\n")
    for wo in sorted(metas):
        with open(os.path.join(output_dir, "meta", f"{wo}.yaml"), "w",
                  encoding="utf-8") as yf:
            yaml.safe_dump(metas[wo].record(), yf, sort_keys=False,
                           allow_unicode=True)

    halves = {"train": 0, "verify": 0}
    strata: dict[str, dict[str, int]] = {}
    flagged: dict[str, list[str]] = {}
    for rec in records:
        if rec.get("split") in halves:
            halves[rec["split"]] += 1
        key = f"{rec.get('analysis_type')}/{rec.get('countermeasure_family')}"
        strata.setdefault(key, {"train": 0, "verify": 0})
        if rec.get("split") in ("train", "verify"):
            strata[key][rec["split"]] += 1
    for wo, meta in metas.items():
        for flag in meta.flags:
            flagged.setdefault(flag, []).append(wo)
    return {
        "evaluations": len(records),
        "added": sorted(metas),
        "clusters": len(clusters),
        "multi_wo_clusters": [sorted(c) for c in clusters if len(c) > 1],
        "split": halves,
        "strata": strata,
        "flags": {k: sorted(v) for k, v in sorted(flagged.items())},
        "manifest": manifest_path,
    }


def build_manifest(inventory_dir: str, emails_dir: str,
                   output_dir: str, docx_dir: str | None = None) -> dict:
    """Build meta records + manifest.jsonl; returns a summary dict."""
    import yaml

    inventories = load_inventories(inventory_dir)
    metas = {wo: build_meta(wo, inv, emails_dir, docx_dir=docx_dir)
             for wo, inv in inventories.items()}
    clusters = companion_clusters(metas, emails_dir)
    assign_split(metas, clusters)

    os.makedirs(os.path.join(output_dir, "meta"), exist_ok=True)
    manifest_path = os.path.join(output_dir, "manifest.jsonl")
    with open(manifest_path, "w", encoding="utf-8") as mf:
        for wo in sorted(metas):
            record = metas[wo].record()
            mf.write(json.dumps(record) + "\n")
            with open(os.path.join(output_dir, "meta", f"{wo}.yaml"), "w",
                      encoding="utf-8") as yf:
                yaml.safe_dump(record, yf, sort_keys=False,
                               allow_unicode=True)

    halves = {"train": 0, "verify": 0}
    strata: dict[str, dict[str, int]] = {}
    flagged: dict[str, list[str]] = {}
    for wo, meta in metas.items():
        halves[meta.split] += 1
        key = f"{meta.analysis_type}/{meta.countermeasure_family}"
        strata.setdefault(key, {"train": 0, "verify": 0})[meta.split] += 1
        for flag in meta.flags:
            flagged.setdefault(flag, []).append(wo)
    return {
        "evaluations": len(metas),
        "clusters": len(clusters),
        "multi_wo_clusters": [sorted(c) for c in clusters if len(c) > 1],
        "split": halves,
        "strata": strata,
        "flags": {k: sorted(v) for k, v in sorted(flagged.items())},
        "manifest": manifest_path,
    }
