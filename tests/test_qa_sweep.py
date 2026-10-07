"""qa_sweep: context gathering and the reviewer/refuter loop with a fake client."""
import json
import os
from types import SimpleNamespace

import pytest

from safety_eval.qa_sweep import (COMMENTS_KEY, DETERMINISTIC_KEY, DIMENSIONS, SweepFinding, context_blocks,
                                  gather_context, pdf_text, read_accepted, run_sweep, sweep_to_markdown,
                                  workbook_text)

TEMPLATE = "templates/Intersection Evaluation Workbook - 2023-12-04.xlsx"


class FakeClient:
    """Reviewers return two findings; refuters confirm '-1' and refute '-2'."""

    def __init__(self):
        self.messages = self
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        schema = kw["output_config"]["format"]["schema"]
        user = kw["messages"][0]["content"]
        if "verdicts" in schema["properties"]:
            ids = [line.split("]")[0][1:] for line in user.splitlines() if line.startswith("[")]
            body = {"verdicts": [{"id": i, "verdict": "CONFIRMED" if i.endswith("-1") else "REFUTED",
                                  "evidence": "checked", "fix_ok": True, "better_fix": ""} for i in ids]}
        else:
            body = {"findings": [{"severity": "High", "where": "D18", "claim": "one", "evidence": "e", "fix": "f"},
                                 {"severity": "Low", "where": "C58", "claim": "two", "evidence": "e", "fix": "f"}],
                    "verified": ["totals"]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=50,
                                                     cache_creation_input_tokens=0))


def test_status_rules():
    f = SweepFinding("a-1", "a", "High", "x", "c")
    assert f.status == "UNVERIFIED"
    f.verdicts = [(0, "CONFIRMED", "", True, ""), (1, "CONFIRMED", "", True, ""), (2, "REFUTED", "", True, "")]
    assert f.status == "CONFIRMED"
    f.verdicts = [(0, "PARTIAL", "", True, ""), (1, "CONFIRMED", "", True, ""), (2, "REFUTED", "", True, "")]
    assert f.status == "PARTIAL"
    f.verdicts = [(0, "REFUTED", "", True, ""), (1, "REFUTED", "", True, "")]
    assert f.status == "REFUTED"


def test_run_sweep_with_fake_client():
    ctx = {"_inventory": "# inventory\nfile.xlsx", "notes.md": "# notes\nhello"}
    fake = FakeClient()
    msgs = []
    rep = run_sweep(ctx, client=fake, dimensions=["calculations", "text"], n_refuters=3, progress=msgs.append)
    assert len(fake.calls) == 5                     # 2 reviewers + 3 refuters
    assert len(rep.findings) == 4
    assert {f.id for f in rep.by_status("CONFIRMED")} == {"calculations-1", "text-1"}
    assert {f.id for f in rep.by_status("REFUTED")} == {"calculations-2", "text-2"}
    assert rep.usage["input_tokens"] == 500 and rep.verified["text"] == ["totals"]
    md = sweep_to_markdown(rep)
    assert "## CONFIRMED (2)" in md and "verifier 3: REFUTED" in md and "—" not in md
    sys_blocks = fake.calls[0]["system"]
    assert sys_blocks[1]["cache_control"] == {"type": "ephemeral"} and "PACKAGE MATERIAL" in sys_blocks[1]["text"]
    assert fake.calls[0]["thinking"] == {"type": "adaptive"} and fake.calls[0]["model"] == "claude-opus-5"


def test_reviewer_failure_is_recorded_not_fatal():
    class Broken(FakeClient):
        def create(self, **kw):
            if "verdicts" not in kw["output_config"]["format"]["schema"]["properties"]:
                raise RuntimeError("boom")
            return super().create(**kw)

    rep = run_sweep({"_inventory": "x"}, client=Broken(), dimensions=["pdf"], n_refuters=1)
    assert rep.errors and not rep.findings


@pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template not present")
def test_gather_context_reads_workbook_and_inventory(tmp_path):
    import shutil
    shutil.copy(TEMPLATE, tmp_path / "Intersection Evaluation Workbook - x.xlsx")
    (tmp_path / "notes.md").write_text("# notes\nhello")
    ctx = gather_context(str(tmp_path))
    assert "_inventory" in ctx and any(k.endswith(".xlsx") for k in ctx) and "notes.md" in ctx
    wt = workbook_text(TEMPLATE)
    assert "Evaluation Set-up" in wt and "1 page results - 1 Target" in wt
    blocks = context_blocks(ctx)
    assert blocks[0]["text"].startswith("Hard rules") and len(DIMENSIONS) == 7


# --------------------------------------------------------------------------- #
# October 2026 (08-18-51363 (W-5708K)): accessible packages, reviewer comments,
# accepted items, deterministic facts, page images
# --------------------------------------------------------------------------- #
def _mini_package(tmp_path):
    from test_qa_package import _package          # tests/ is on sys.path (pytest prepend mode)

    root = _package(tmp_path)
    os.makedirs(os.path.join(root, "Crash Reports"))
    with open(os.path.join(root, "Crash Reports", "600504376.txt"), "w") as fh:
        fh.write("DRIVER NAME: JANE DOE")
    return root


def test_gather_context_accessible_package(tmp_path):
    root = _mini_package(tmp_path)
    with open(os.path.join(root, "Notes", "review.eml"), "w") as fh:
        fh.write("Subject: RE: Safety Evaluation\nContent-Type: text/plain\n\nDelete Crashes\n 106926706 - PVA\n")
    ctx = gather_context(root, comments="Add a comment on the A injury crash")
    docx = next(k for k in ctx if k.endswith("One Pager.docx"))
    assert "Volume (2018, 2023) | 36,700 | 36,200" in ctx[docx] and "East leg:" in ctx[docx]
    assert any(k.endswith("2 of 2.xlsx") and "Sheet 'One Pager'" in v for k, v in ctx.items())
    assert any(v.startswith("# Correspondence review.eml") for v in ctx.values())
    assert ctx[COMMENTS_KEY].startswith("# Correspondence") and "A injury" in ctx[COMMENTS_KEY]
    assert "Deterministic checks" in ctx[DETERMINISTIC_KEY] and "41000076576BEFORE2" in ctx[DETERMINISTIC_KEY]
    assert "~$" not in ctx["_inventory"] and "JANE DOE" not in "".join(ctx.values())


def test_pdf_text_gives_a_repeated_page_once(monkeypatch):
    pages = {"a.pdf": ["one\nTotal 46", "two"], "ce.pdf": ["cover", "one\nTotal  46", "two"]}
    monkeypatch.setattr("safety_eval.print_results.pdf_page_texts", lambda p: pages[p])
    seen = {}
    pdf_text("a.pdf", seen=seen)
    text = pdf_text("ce.pdf", seen=seen)
    assert "--- page 1 ---\ncover" in text and "[same text as a.pdf page 1]" in text
    assert "[same text as a.pdf page 2]" in text


def test_comments_dimension_needs_comments():
    fake = FakeClient()
    rep = run_sweep({"_inventory": "x"}, client=fake, dimensions=["text", "comments"], n_refuters=0)
    assert len(fake.calls) == 1 and rep.skipped and "REVIEWER COMMENTS" in rep.skipped[0]
    assert "## Skipped" in sweep_to_markdown(rep)
    fake = FakeClient()
    run_sweep({"_inventory": "x", COMMENTS_KEY: "# Correspondence: reviewer comments\nfix it"}, client=fake,
              dimensions=["text", "comments"], n_refuters=0)
    assert len(fake.calls) == 2
    assert any("REVIEWER COMMENTS reviewer" in str(c["messages"][0]["content"]) for c in fake.calls)


def test_accepted_items_reach_reviewers_and_refuters():
    fake = FakeClient()
    accepted = read_accepted("# accepted\n- Hidden ~$ lock file\n2. Representative years 2018 and 2023\n")
    assert accepted == ["Hidden ~$ lock file", "Representative years 2018 and 2023"]
    run_sweep({"_inventory": "x"}, client=fake, dimensions=["pdf"], n_refuters=1, accepted=accepted)
    system = fake.calls[0]["system"]
    assert "KNOWN AND ACCEPTED" in system[0]["text"] and "- Representative years 2018 and 2023" in system[0]["text"]
    assert system[1]["cache_control"] == {"type": "ephemeral"}
    refuter_user = fake.calls[-1]["messages"][0]["content"]
    assert "known and accepted" in refuter_user


def test_page_images_go_to_the_pdf_and_text_reviewers_only():
    fake = FakeClient()
    img = [{"type": "text", "text": "Image: x One Pager.pdf, 1"},
           {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA=="}}]
    run_sweep({"_inventory": "x"}, client=fake, dimensions=["pdf", "text", "calculations"], n_refuters=0, images=img)
    kinds = {}
    for c in fake.calls:
        content = c["messages"][0]["content"]
        title = (content[0]["text"] if isinstance(content, list) else content).split(" reviewer")[0]
        kinds[title] = isinstance(content, list) and any(b["type"] == "image" for b in content)
    assert kinds == {"You are the PDF ASSEMBLY": True, "You are the REPORT TEXT": True,
                     "You are the CALCULATIONS": False}
