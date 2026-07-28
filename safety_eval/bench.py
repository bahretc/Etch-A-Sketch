"""Credibility benchmark runner (docs/10): extract -> draft -> score.

Pipeline stages, each resumable from files:

1. ``extract``  - build ``train.jsonl`` / ``verify.jsonl`` from downloaded
   deliverable workbooks + the archive manifest (one record per evaluation;
   for evaluations delivered as several workbooks the largest part is used
   and the simplification is recorded on the record).
2. ``draft``    - generate drafts for a dataset's records with train-half
   exemplars, either synchronously or via the Message Batches API (50%
   price). Never mutates datasets.
3. ``score``    - similarity of drafts vs the delivered text plus gate
   results; writes the benchmark report (median/quartiles, per-stratum,
   per-evaluation detail).

The verify half is measured, never mined: exemplars always come from the
train file, and ``draft`` refuses to run with a train dataset unless
``--rehearsal`` is passed (rehearsal = tuning runs on the train half).
"""
from __future__ import annotations

import json
import os
import re
from statistics import median

from . import draft as D

# WO ids are normally 11 digits; one archived folder is mis-named with 12
# (410000749019) and is preserved verbatim, so allow up to 12.
_WB_NAME_RE = re.compile(r"^(?P<wo>\d{10,12})__(?P<name>.+)$")


# Blank scope-package templates are named with the template release date
# (e.g. "... Evaluation Workbook - 2023-12-04.xlsx"); a copy sometimes sits
# in an evaluation's Background subfolder. It has no authored content, so
# extracting it as the deliverable scores a spurious zero. A real delivered
# workbook is named for the project, never the bare template date.
_TEMPLATE_NAME_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\s*(?:\(\d+\))?\.xls[mx]$",
                               re.I)


def _is_eval_workbook(fn: str) -> bool:
    """Deliverable evaluation workbooks only; folders also hold fiche
    reports, blank templates, and other .xlsm/.xlsx siblings that must
    never be extracted as an evaluation's results."""
    if "evaluation workbook" not in fn.lower():
        return False
    if _TEMPLATE_NAME_RE.search(fn):
        return False
    return True


def _primary_workbooks(workbook_dir: str) -> dict[str, str]:
    """wo -> path of the largest workbook part for that evaluation."""
    best: dict[str, tuple[int, str]] = {}
    for fn in os.listdir(workbook_dir):
        m = _WB_NAME_RE.match(fn)
        if not m or not fn.lower().endswith((".xlsx", ".xlsm")):
            continue
        if not _is_eval_workbook(fn):
            continue
        path = os.path.join(workbook_dir, fn)
        size = os.path.getsize(path)
        wo = m.group("wo")
        if wo not in best or size > best[wo][0]:
            best[wo] = (size, path)
    return {wo: path for wo, (size, path) in best.items()}


_MSG_NAME_RE = re.compile(r"^(?P<wo>\d{10,12})__.+\.(?:msg|eml)$", re.I)


def _assignment_msgs(msg_dir: str) -> dict[str, list[str]]:
    """wo -> downloaded assignment-thread files (``<wo>__*.msg`` / ``.eml``)."""
    out: dict[str, list[str]] = {}
    for fn in os.listdir(msg_dir):
        m = _MSG_NAME_RE.match(fn)
        if m:
            out.setdefault(m.group("wo"), []).append(
                os.path.join(msg_dir, fn))
    return out


def _msg_assumptions(wo: str, meta: dict, msg_paths: list[str]):
    """Authoritative assumptions for a msg-sourced WO from its assignment
    thread, or None. Selects the thread block whose Order ID (or Project ID)
    is this WO; provenance is enforced downstream (extract_record refuses any
    assumptions whose source is not the .msg thread, docs/10)."""
    if meta.get("assumptions_source") != "msg" or not msg_paths:
        return None
    from .assignment_email import parse_assignment_email, to_assumptions_dict

    want = re.sub(r"\D", "", wo)
    for path in msg_paths:
        try:
            blocks = parse_assignment_email(path)
        except Exception:                           # noqa: BLE001 - skip bad
            continue
        for pa in blocks.values():
            if re.sub(r"\D", "", pa.order_id) == want or (
                    pa.project_id and pa.project_id == meta.get("project_id")):
                return to_assumptions_dict(pa)
    return None


def extract_datasets(workbook_dir: str, manifest_path: str,
                     outdir: str, msg_dir: str | None = None,
                     progress=None) -> dict:
    """Build train/verify record files; returns counts and problems.

    ``msg_dir`` (optional): a directory of downloaded assignment threads named
    ``<wo>__<name>.msg``. When given, msg-sourced evaluations get their
    authoritative assumptions attached to ``inputs.assumptions`` (docs/10);
    without it every record's assumptions stay null.
    """
    from .report_dataset import extract_record

    metas = {json.loads(l)["wo"]: json.loads(l)
             for l in open(manifest_path, encoding="utf-8")}
    paths = _primary_workbooks(workbook_dir)
    msgs = _assignment_msgs(msg_dir) if msg_dir else {}
    os.makedirs(outdir, exist_ok=True)
    out = {"train": [], "verify": []}
    problems: list[str] = []
    done = 0
    with_assumptions = 0
    for wo, meta in sorted(metas.items()):
        path = paths.get(wo)
        if path is None:
            problems.append(f"{wo}: no downloaded workbook")
            continue
        try:
            rec = extract_record(path, meta,
                                 assumptions=_msg_assumptions(
                                     wo, meta, msgs.get(wo, [])))
        except Exception as exc:                    # noqa: BLE001 - collect
            problems.append(f"{wo}: extract failed: {exc}")
            continue
        if rec["inputs"].get("assumptions") is not None:
            with_assumptions += 1
        rec["companions"] = meta.get("companions", [])
        parts = [f for f in os.listdir(workbook_dir)
                 if f.startswith(wo + "__") and _is_eval_workbook(f)]
        if len(parts) > 1:
            rec["note"] = (f"primary of {len(parts)} workbook parts "
                           f"({os.path.basename(path)})")
        out.setdefault(meta.get("split") or "train", []).append(rec)
        done += 1
        if progress:
            progress(done, len(metas))
    for split, recs in out.items():
        with open(os.path.join(outdir, f"{split}.jsonl"), "w",
                  encoding="utf-8") as fh:
            for rec in recs:
                fh.write(json.dumps(rec) + "\n")
    return {"train": len(out.get("train", [])),
            "verify": len(out.get("verify", [])),
            "with_assumptions": with_assumptions,
            "problems": problems}


def _load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def run_drafts(dataset_path: str, train_path: str, outpath: str,
               model: str = D.DEFAULT_MODEL, k: int = 3,
               mode: str = "batch", rehearsal: bool = False,
               limit: int | None = None, client=None,
               poll_seconds: int = 30, progress=None) -> dict:
    """Draft every record of a dataset; write drafts.jsonl.

    ``mode='batch'`` uses the Message Batches API (half price; minutes to
    hours of latency); ``'sync'`` calls the Messages API record by record.
    """
    records = _load(dataset_path)
    train = _load(train_path)
    if records and records[0].get("split") == "train" and not rehearsal:
        raise ValueError(
            "Refusing to draft the train half without rehearsal=True; "
            "the benchmark dataset is the verify half")
    if limit:
        records = records[:limit]
    boiler = D.boilerplate_texts(train + records)

    if client is None:
        import anthropic
        client = anthropic.Anthropic()

    drafts: dict[str, dict] = {}
    errors: dict[str, str] = {}
    if mode == "sync":
        for i, rec in enumerate(records, 1):
            ex = D.select_exemplars(rec, train, k=k)
            try:
                drafts[rec["wo"]] = D.generate_draft(client, rec, ex, boiler,
                                                     model=model)
            except Exception as exc:               # noqa: BLE001 - collect
                errors[rec["wo"]] = str(exc)
            if progress:
                progress(i, len(records))
    else:
        from anthropic.types.message_create_params import (
            MessageCreateParamsNonStreaming)
        from anthropic.types.messages.batch_create_params import Request

        requests = []
        for rec in records:
            ex = D.select_exemplars(rec, train, k=k)
            params = D.draft_request_params(rec, ex, boiler, model=model)
            requests.append(Request(
                custom_id=f"wo-{rec['wo']}",
                params=MessageCreateParamsNonStreaming(**params)))
        batch = client.messages.batches.create(requests=requests)
        import time
        while True:
            batch = client.messages.batches.retrieve(batch.id)
            if batch.processing_status == "ended":
                break
            if progress:
                progress(batch.request_counts.succeeded
                         + batch.request_counts.errored, len(requests))
            time.sleep(poll_seconds)
        for result in client.messages.batches.results(batch.id):
            wo = result.custom_id.removeprefix("wo-")
            if result.result.type == "succeeded":
                msg = result.result.message
                if msg.stop_reason == "refusal":
                    errors[wo] = "refusal"
                    continue
                text = next((b.text for b in msg.content
                             if b.type == "text"), "")
                try:
                    drafts[wo] = D.parse_draft(text)
                except (json.JSONDecodeError, KeyError) as exc:
                    errors[wo] = f"unparseable draft: {exc}"
            else:
                errors[wo] = result.result.type

    with open(outpath, "w", encoding="utf-8") as fh:
        for wo, dr in drafts.items():
            fh.write(json.dumps({"wo": wo, "model": model,
                                 "draft": dr}) + "\n")
    return {"drafted": len(drafts), "errors": errors,
            "mode": mode, "model": model}


def score_run(drafts_path: str, dataset_path: str, train_path: str,
              report_path: str) -> dict:
    """Score drafts against the delivered text; write the report JSON."""
    records = {r["wo"]: r for r in _load(dataset_path)}
    train = _load(train_path)
    boiler = D.boilerplate_texts(train + list(records.values()))
    scores = []
    detail = []
    for line in _load(drafts_path):
        rec = records.get(line["wo"])
        if rec is None:
            continue
        s = D.score_draft(line["draft"], rec, boiler)
        scores.append(s)
        detail.append({
            "wo": s.wo,
            "analysis_type": rec.get("analysis_type"),
            "countermeasure_family": rec.get("countermeasure_family"),
            "similarity": s.char_similarity,
            "cells_scored": s.cells_scored,
            "cells_missing": s.cells_missing,
            "cells_extra": s.cells_extra,
            "gate_problems": s.gate_problems,
        })
    summary = D.benchmark_summary(scores)
    strata: dict[str, list[float]] = {}
    for d in detail:
        key = f"{d['analysis_type']}/{d['countermeasure_family']}"
        strata.setdefault(key, []).append(d["similarity"])
    summary["per_stratum_median"] = {
        k: round(median(v), 4) for k, v in sorted(strata.items())}
    report = {"summary": summary, "evaluations": detail}
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    return report
