"""Report-sheet drafting layer (docs/07 Phase 5 - drafts only).

Turns a report-dataset record (see ``report_dataset.py``) into DRAFT text for
the engineer-authored cells of the 1-page results sheets, using a Claude
model with few-shot exemplars drawn STRICTLY from the train half of the
archive. The engineer reviews every draft; nothing here is auto-final
(docs/07: the tool prepares, the PE decides).

Design rules:

* **Boilerplate vs authored** is decided by data, not guesswork: cell text
  that appears (normalized) in several different evaluations is template
  boilerplate; text unique to an evaluation is engineer-authored and is what
  the model must learn to draft.
* **Provenance:** exemplars come only from records whose ``split`` is
  ``train``; passing a verify record as an exemplar raises. Assumptions in
  the inputs follow the docs/10 rule (only .msg-sourced ones are present).
* **Gates before eyes:** every draft passes the docs/05 style gate (no em
  dashes, plain tone is prompted) and a numeric gate - any "N ... crash(es)"
  quote must match a computed tally from the record's inputs.
* **Model-agnostic:** generation goes through the Anthropic SDK against any
  OpenAI-compatible or Anthropic endpoint the caller configures (base_url),
  so a local server (e.g. Ollama's Anthropic-compatible proxy) and the
  hosted API are the same code path. Batch mode uses the Message Batches
  API for half-price offline runs.

Scoring (the credibility benchmark) is similarity between the drafted and
delivered text per authored cell: 1 - normalized Levenshtein distance,
char-weighted per evaluation. The verify half is measured, never mined.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from .results_sheet import check_style

#: text appearing in this many distinct evaluations is template boilerplate
BOILERPLATE_MIN_EVALS = 3
#: authored cells shorter than this are dropped from targets (stray labels)
MIN_AUTHORED_LEN = 12
DEFAULT_MODEL = "claude-opus-4-8"

_WS_RE = re.compile(r"\s+")
_COUNT_RE = re.compile(r"(?<!-)\b(\d{1,4})\s+(?:[a-z][a-z\- ]{0,40}\s)?"
                       r"crash(?:es)?\b", re.I)


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


# --------------------------------------------------------------------------- #
# boilerplate classification
# --------------------------------------------------------------------------- #
def boilerplate_texts(records: list[dict],
                      min_evals: int = BOILERPLATE_MIN_EVALS) -> set[str]:
    """Normalized cell texts that recur across evaluations (template text)."""
    seen: Counter = Counter()
    for rec in records:
        texts = {
            _norm(t)
            for cells in rec["targets"]["results_text"].values()
            for t in cells.values()
        }
        seen.update(texts)
    return {t for t, n in seen.items() if n >= min_evals}


def authored_cells(rec: dict, boilerplate: set[str],
                   min_len: int = MIN_AUTHORED_LEN) -> dict[str, dict]:
    """{sheet: {cell: text}} for the engineer-authored cells of one record."""
    out: dict[str, dict] = {}
    for sheet, cells in rec["targets"]["results_text"].items():
        keep = {c: t for c, t in cells.items()
                if _norm(t) not in boilerplate and len(t.strip()) >= min_len}
        if keep:
            out[sheet] = keep
    return out


# --------------------------------------------------------------------------- #
# prompt assembly
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """\
You draft the manual text of NCDOT HSIP before/after safety evaluation \
results sheets for a licensed engineer's review. Follow the NCDOT house \
style exactly: plain and understated sentences, no em dashes anywhere, no \
flourishes, no marketing language. Every crash count you write must match \
the tallies provided in the input data; never invent or adjust a number. \
Where the input genuinely does not determine what to say, write the most \
conservative factual statement supported by the data. You produce drafts \
only; the engineer decides."""


def _inputs_view(rec: dict) -> dict:
    """The model-visible slice of a record's inputs."""
    inp = rec["inputs"]
    return {
        "analysis_type": rec.get("analysis_type"),
        "countermeasure_family": rec.get("countermeasure_family"),
        "tallies": inp.get("tallies"),
        "ledger": inp.get("ledger"),
        "assumptions": inp.get("assumptions"),
    }


def build_prompt(rec: dict, exemplars: list[dict],
                 boilerplate: set[str],
                 targets: dict[str, list] | None = None
                 ) -> tuple[str, list[dict]]:
    """(system, messages) for one draft request.

    ``exemplars`` must be train-half records; each contributes its inputs
    and its authored cells as a worked example. The target lists the sheet
    and cell addresses to fill (the tan manual cells the engineer filled on
    the delivered workbook), so drafted text aligns cell-for-cell for
    review and scoring. On a delivered workbook the targets are its own
    authored cells (the benchmark); a NEW workbook has none yet, so the
    caller passes ``targets`` located on the template by label
    (results_sheet.manual_text_targets).
    """
    for ex in exemplars:
        if ex.get("split") != "train":
            raise ValueError(
                f"Exemplar {ex.get('wo')} is not train-half "
                f"(split={ex.get('split')!r}); the verify half is measured, "
                "never mined (docs/10)")

    parts: list[str] = []
    for i, ex in enumerate(exemplars, 1):
        parts.append(
            f"## Example {i}\n"
            f"Input data:\n{json.dumps(_inputs_view(ex), indent=1)}\n"
            f"Text the engineer wrote:\n"
            f"{json.dumps(authored_cells(ex, boilerplate), indent=1)}")

    if targets is None:
        targets = {sheet: sorted(cells)
                   for sheet, cells in authored_cells(rec, boilerplate).items()}
    parts.append(
        "## Your task\n"
        f"Input data:\n{json.dumps(_inputs_view(rec), indent=1)}\n"
        "Draft the text for exactly these cells (same JSON shape as the "
        f"examples: sheet -> cell -> text):\n{json.dumps(targets, indent=1)}")
    return SYSTEM_PROMPT, [{"role": "user", "content": "\n\n".join(parts)}]


def select_exemplars(rec: dict, train_records: list[dict],
                     k: int = 3) -> list[dict]:
    """Stratum-matched exemplars: same analysis type first, then same
    countermeasure family, then anything - never the record itself and
    never its companions."""
    ban = {rec.get("wo")} | set(rec.get("companions") or [])
    pool = [t for t in train_records if t["wo"] not in ban]

    def rank(t: dict) -> tuple:
        return (t["analysis_type"] != rec.get("analysis_type"),
                t["countermeasure_family"] != rec.get("countermeasure_family"),
                t["wo"])                     # deterministic tiebreak
    return sorted(pool, key=rank)[:k]


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #
_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "cells": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sheet": {"type": "string"},
                    "cell": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["sheet", "cell", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cells"],
    "additionalProperties": False,
}


def draft_request_params(rec: dict, exemplars: list[dict],
                         boilerplate: set[str],
                         model: str = DEFAULT_MODEL,
                         max_tokens: int = 8192,
                         targets: dict[str, list] | None = None) -> dict:
    """Messages-API params for one draft (create or batch entry)."""
    system, messages = build_prompt(rec, exemplars, boilerplate,
                                    targets=targets)
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "output_config": {"format": {"type": "json_schema",
                                     "schema": _DRAFT_SCHEMA}},
    }


def parse_draft(text: str) -> dict[str, dict]:
    """Model JSON -> {sheet: {cell: text}}."""
    data = json.loads(text)
    out: dict[str, dict] = {}
    for item in data.get("cells", []):
        out.setdefault(item["sheet"], {})[item["cell"]] = item["text"]
    return out


def generate_draft(client, rec: dict, exemplars: list[dict],
                   boilerplate: set[str],
                   model: str = DEFAULT_MODEL,
                   targets: dict[str, list] | None = None) -> dict[str, dict]:
    """One synchronous draft via the Messages API."""
    params = draft_request_params(rec, exemplars, boilerplate, model,
                                  targets=targets)
    response = client.messages.create(**params)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model declined drafting {rec.get('wo')}")
    text = next(b.text for b in response.content if b.type == "text")
    return parse_draft(text)


def draft_new(xlsx_path: str, train_path: str, *,
              sheet: str | None = None,
              analysis_type: str = "", countermeasure_family: str = "",
              assumptions: dict | None = None, treatment: str | None = None,
              client=None, model: str | None = None, k: int = 3) -> dict:
    """Draft the manual text of a NEW evaluation workbook (drafts only).

    The benchmark drafts a delivered workbook against its own authored
    cells; a new workbook has none yet, so the targets are located on the
    workbook by label (results_sheet.manual_text_targets): the Items for
    Discussion cell and the Additional Information rows. Exemplars come
    strictly from ``train_path`` (the archive's train half, docs/10), and
    every draft passes the docs/05 style gate and the numeric gate before
    the engineer sees it. Nothing is written to the workbook: the
    engineer reviews, edits and pastes.

    ``model=None`` resolves through SAFETY_EVAL_ASSIST_MODEL then the
    drafting default. Returns ``{"draft": {sheet: {cell: text}},
    "problems": [...], "targets": {sheet: [cells]}, "exemplars": [wo...],
    "sheet": sheet}``.
    """
    import os as _os

    from .report_dataset import extract_record, results_sheet_names
    from .results_sheet import manual_text_targets
    from .xlsx_patch import sheet_files

    with open(train_path, encoding="utf-8") as fh:
        train = [json.loads(ln) for ln in fh if ln.strip()]
    if not train:
        raise ValueError(f"no train records in {train_path}; run "
                         "`safety-eval bench extract` on the archive first")
    boilerplate = boilerplate_texts(train)

    rec = extract_record(xlsx_path, meta={
        "wo": "candidate", "split": "candidate",
        "analysis_type": analysis_type,
        "countermeasure_family": countermeasure_family,
    }, assumptions=assumptions, treatment=treatment)

    if sheet is None:
        sheets = results_sheet_names(list(sheet_files(xlsx_path)))
        if len(sheets) != 1:
            raise ValueError(
                "say which results sheet to draft for; the workbook has "
                + (", ".join(sorted(sheets)) or "no results sheet"))
        sheet = sheets[0]
    targets = {sheet: manual_text_targets(xlsx_path, sheet)}
    if not targets[sheet]:
        raise ValueError(f"no draftable cells located on {sheet!r}; the "
                         "sheet is missing its Items for Discussion / "
                         "Additional Information labels")

    exemplars = select_exemplars(rec, train, k=k)
    model = (model or "").strip() \
        or _os.environ.get("SAFETY_EVAL_ASSIST_MODEL", "").strip() \
        or DEFAULT_MODEL
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    draft = generate_draft(client, rec, exemplars, boilerplate,
                           model=model, targets=targets)
    problems = gate_draft(draft, rec)
    return {"draft": draft, "problems": problems, "targets": targets,
            "exemplars": [e.get("wo", "") for e in exemplars],
            "sheet": sheet}


# --------------------------------------------------------------------------- #
# gates (before any engineer sees a draft)
# --------------------------------------------------------------------------- #
def gate_draft(draft: dict[str, dict], rec: dict) -> list[str]:
    """docs/05 style + numeric-tally violations; empty means clean."""
    problems: list[str] = []
    legit: set[int] = set()
    for v in (rec["inputs"].get("tallies") or {}).values():
        if isinstance(v, dict):
            legit.update(x for x in v.values() if isinstance(x, int))
        elif isinstance(v, int):
            legit.add(v)
    for t in (rec["inputs"].get("ledger") or {}).values():
        if isinstance(t, dict):
            legit.update(x for x in t.values() if isinstance(x, int))
            if "centerline" in t and "right" in t:
                legit.add(t["centerline"] + t["right"])

    for sheet, cells in draft.items():
        for cell, text in cells.items():
            where = f"{sheet}!{cell}"
            try:
                check_style(text, where)
            except ValueError as exc:
                problems.append(str(exc))
            for m in _COUNT_RE.finditer(text):
                n = int(m.group(1))
                if legit and n not in legit:
                    problems.append(
                        f"{where}: quotes {m.group(0)!r} but no computed "
                        f"tally equals {n}")
    return problems


# --------------------------------------------------------------------------- #
# scoring (the credibility benchmark)
# --------------------------------------------------------------------------- #
def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """1 - normalized edit distance on whitespace-normalized text."""
    a, b = _WS_RE.sub(" ", a).strip(), _WS_RE.sub(" ", b).strip()
    if not a and not b:
        return 1.0
    return 1.0 - _levenshtein(a, b) / max(len(a), len(b))


@dataclass
class DraftScore:
    wo: str
    cells_scored: int = 0
    cells_missing: int = 0            # authored in reference, absent in draft
    cells_extra: int = 0              # drafted but not authored in reference
    char_similarity: float = 0.0      # char-weighted across scored cells
    gate_problems: list = field(default_factory=list)
    per_cell: dict = field(default_factory=dict)


def score_draft(draft: dict[str, dict], rec: dict,
                boilerplate: set[str]) -> DraftScore:
    """Compare a draft against what the engineer actually delivered."""
    ref = authored_cells(rec, boilerplate)
    score = DraftScore(wo=rec.get("wo", ""))
    weighted = 0.0
    chars = 0
    for sheet, cells in ref.items():
        for cell, ref_text in cells.items():
            drafted = (draft.get(sheet) or {}).get(cell)
            if drafted is None:
                score.cells_missing += 1
                continue
            sim = similarity(drafted, ref_text)
            score.per_cell[f"{sheet}!{cell}"] = round(sim, 4)
            weighted += sim * len(ref_text)
            chars += len(ref_text)
            score.cells_scored += 1
    for sheet, cells in draft.items():
        for cell in cells:
            if (ref.get(sheet) or {}).get(cell) is None:
                score.cells_extra += 1
    score.char_similarity = round(weighted / chars, 4) if chars else 0.0
    score.gate_problems = gate_draft(draft, rec)
    return score


def benchmark_summary(scores: list[DraftScore]) -> dict:
    sims = sorted(s.char_similarity for s in scores)

    def pct(p: float) -> float:
        if not sims:
            return 0.0
        i = (len(sims) - 1) * p
        lo, hi = int(i), min(int(i) + 1, len(sims) - 1)
        return round(sims[lo] + (sims[hi] - sims[lo]) * (i - lo), 4)

    return {
        "evaluations": len(scores),
        "median_similarity": pct(0.5),
        "p25": pct(0.25), "p75": pct(0.75),
        "worst": pct(0.0), "best": pct(1.0),
        "clean_gate_rate": round(
            sum(1 for s in scores if not s.gate_problems) / len(scores), 4)
            if scores else 0.0,
        "cells_scored": sum(s.cells_scored for s in scores),
        "cells_missing": sum(s.cells_missing for s in scores),
    }
