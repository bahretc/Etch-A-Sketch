"""qa_sweep: context gathering and the reviewer/refuter loop with a fake client."""
import json
import os
from types import SimpleNamespace

import pytest

from safety_eval.qa_sweep import (DIMENSIONS, SweepFinding, context_blocks, gather_context, run_sweep,
                                  sweep_to_markdown, workbook_text)

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
    assert blocks[0]["text"].startswith("Hard rules") and len(DIMENSIONS) == 6
