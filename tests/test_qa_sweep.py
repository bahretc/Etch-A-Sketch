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
    assert any(v.startswith("# Correspondence (review comments) review.eml") for v in ctx.values())
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
    run_sweep({"_inventory": "x", COMMENTS_KEY: "# Correspondence (review comments): supplied\nfix it"}, client=fake,
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


def test_assignment_or_assumptions_email_is_not_review_comments(tmp_path):
    """An assumptions thread in Notes must not start the REVIEWER COMMENTS
    reviewer (it would grade the assignment text as comments)."""
    from safety_eval.qa_sweep import has_correspondence, looks_like_review

    assumptions = ("Hi Chris! I have no notes! Looks great!\n"
                   "*\tOrder ID: 41000076576\n*\tCountermeasure: Upgrade traffic signals\n"
                   "*\tTarget Crashes: LTSR Crashes involving WB left-turns\n")
    review = ("Intersection 28\n*\tRemove comma between (LTSR) and Crashes\n"
              "*\tAdd a comment on the A injury crash in the after period.\n")
    assert not looks_like_review(assumptions) and looks_like_review(review)
    assert looks_like_review("Delete Crashes\n*\t106926706 - fully in the PVA\n")
    root = _mini_package(tmp_path)
    with open(os.path.join(root, "Notes", "assumptions.eml"), "w") as fh:
        fh.write("Subject: RE: Safety Evaluation\nContent-Type: text/plain\n\n" + assumptions)
    ctx = gather_context(root, deterministic=False)
    assert not has_correspondence(ctx)
    fake = FakeClient()
    rep = run_sweep(ctx, client=fake, dimensions=["comments"], n_refuters=0)
    assert not fake.calls and rep.skipped


# --------------------------------------------------------------------------- #
# regressions from the adversarial review of the sweep (October 2026)
# --------------------------------------------------------------------------- #
def test_nested_crash_report_folders_are_never_read(tmp_path):
    from safety_eval.qa_sweep import page_images

    root = _mini_package(tmp_path)
    nested = os.path.join(root, "Crash Reports", "Before")
    os.makedirs(nested)
    with open(os.path.join(nested, "600504377.txt"), "w") as fh:
        fh.write("DRIVER NAME: JOHN ROE")
    ctx = gather_context(root, deterministic=False)
    blob = "".join(ctx.values())
    assert "JOHN ROE" not in blob and "JANE DOE" not in blob and "600504377" not in blob
    assert page_images(os.path.join(root, "Crash Reports")) == []          # pruned at the walk


def test_pdf_text_whole_pages_within_budget_keeps_the_study_criteria(monkeypatch):
    from safety_eval.qa_sweep import pdf_text

    pages = [f"crash listing page {i}\n" + "x" * 1000 for i in range(8)]
    pages.append("Study Criteria\nStudy Name ADT 36200\n  Included Accidents\n    106726655")
    store = {"a.pdf": pages, "ce.pdf": pages[:3]}
    monkeypatch.setattr("safety_eval.print_results.pdf_page_texts", lambda p: store[p])
    seen = {}
    text = pdf_text("a.pdf", seen=seen, budget=3500)
    assert "Included Accidents" in text and "106726655" in text          # the appendix survives
    assert "not shown: over the size budget" in text
    shown = [ln for ln in text.splitlines() if ln.startswith("--- page")]
    assert all(not ln.endswith("]") for ln in shown)                       # whole pages only
    ce = pdf_text("ce.pdf", seen=seen)
    for line in ce.splitlines():
        if "[same text as a.pdf page" in line:
            n = int(line.split("page ")[-1].rstrip("]"))
            assert f"--- page {n} ---" in text                             # a pointer never leads to a dropped page


def test_read_accepted_keeps_leading_ids():
    from safety_eval.qa_sweep import read_accepted

    got = read_accepted("- Study Criteria appendix not bound\n106926706 kept as IS per reviewer\n"
                        "2. 2020 never used\n3) item three\n")
    assert got == ["Study Criteria appendix not bound", "106926706 kept as IS per reviewer",
                   "2020 never used", "item three"]


def test_refuters_see_the_pages_for_findings_from_the_page_reviewers():
    fake = FakeClient()
    img = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA=="}}]
    run_sweep({"_inventory": "x"}, client=fake, dimensions=["pdf"], n_refuters=2, images=img)
    refuter_calls = [c for c in fake.calls if "verdicts" in c["output_config"]["format"]["schema"]["properties"]]
    assert len(refuter_calls) == 2
    assert all(isinstance(c["messages"][0]["content"], list) for c in refuter_calls)
    fake = FakeClient()
    run_sweep({"_inventory": "x"}, client=fake, dimensions=["calculations"], n_refuters=1, images=img)
    assert isinstance(fake.calls[-1]["messages"][0]["content"], str)


def test_first_reviewer_runs_alone_to_warm_the_cache():
    order = []

    class Recording(FakeClient):
        def create(self, **kw):
            c = kw["messages"][0]["content"]
            order.append((c[0]["text"] if isinstance(c, list) else c).split(" reviewer")[0])
            return super().create(**kw)

    run_sweep({"_inventory": "x"}, client=Recording(), dimensions=["teaas", "pdf", "text"], n_refuters=0)
    assert order[0] == "You are the TEAAS CROSS-CHECK"


def test_truncated_answer_is_a_clear_error():
    class Truncated(FakeClient):
        def create(self, **kw):
            r = super().create(**kw)
            r.stop_reason = "max_tokens"
            return r

    rep = run_sweep({"_inventory": "x"}, client=Truncated(), dimensions=["text"], n_refuters=0)
    assert rep.errors and "ran out of output tokens" in rep.errors[0]


def test_gather_context_reads_the_deliverable_workbooks_and_checks_paths(tmp_path):
    import shutil

    root = _mini_package(tmp_path)
    ca = os.path.join(root, "Crash Analysis")
    src = os.path.join(ca, "Accessible Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx")
    shutil.copy(src, os.path.join(ca, "Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx"))
    ctx = gather_context(root, deterministic=False)
    assert any(k.endswith("Accessible Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx") for k in ctx)
    assert not any(k.endswith(os.sep + "Intersection Evaluation Workbook - 08-18-51363 (W-5708K) 2 of 2.xlsx") for k in ctx)
    assert "not the deliverable workbook" in ctx["_inventory"]
    with pytest.raises(FileNotFoundError):
        gather_context(root, workbook=os.path.join(ca, "nope.xlsm"), deterministic=False)
