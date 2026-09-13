"""package: discovery, clean names, zip, and the finish pipeline (no print)."""
import os
import shutil
import zipfile

import pytest

from safety_eval.package import (FinishOptions, clean_name, discover, finish_package, workbook_summary,
                                 zip_package)

TEMPLATE = "templates/Intersection Evaluation Workbook - 2023-12-04.xlsx"
needs_template = pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template not present")


def test_clean_name_strips_tip_prefix():
    assert clean_name("WO-41000076160 10-18-223 (TIP #W-5710AM)") == "WO-41000076160 10-18-223 (W-5710AM)"
    assert clean_name("10-18-223 (TIP # W-5710AM) Web.pdf") == "10-18-223 (W-5710AM) Web.pdf"
    assert clean_name("Crash Analysis") == "Crash Analysis"


def _mini_package(tmp_path, with_workbook=True):
    root = tmp_path / "WO-41000076160 10-18-223 (TIP #W-5710AM)"
    (root / "Crash Analysis").mkdir(parents=True)
    (root / "Notes").mkdir()
    (root / "Crash Reports").mkdir()
    if with_workbook:
        shutil.copy(TEMPLATE, root / "Crash Analysis" / "Intersection Evaluation Workbook - 10-18-223 (TIP #W-5710AM).xlsx")
    (root / "Crash Analysis" / "41000076160BEFORE.pdf").write_bytes(b"%PDF-1.4 stub")
    (root / "Notes" / "Crash Report Review Notes.md").write_text("notes\n")
    (root / "Crash Reports" / "600504376_1.tif").write_bytes(b"II*\x00stub")
    return root


@needs_template
def test_discover_and_zip_with_clean_names(tmp_path):
    root = _mini_package(tmp_path)
    pkg = discover(str(root))
    assert pkg.label == "10-18-223 (TIP #W-5710AM)"
    assert pkg.workbook and pkg.before_pdf and pkg.after_pdf is None
    assert len(pkg.crash_reports) == 1 and pkg.notes_dir.endswith("Notes")
    out = str(tmp_path / "out.zip")
    n = zip_package(str(root), out)
    assert n == 4
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert all("TIP #" not in n for n in names)
    assert "WO-41000076160 10-18-223 (W-5710AM)/Crash Analysis/Intersection Evaluation Workbook - 10-18-223 (W-5710AM).xlsx" in names
    n2 = zip_package(str(root), str(tmp_path / "keep.zip"), rename=False)
    with zipfile.ZipFile(str(tmp_path / "keep.zip")) as z:
        assert any("TIP #" in n for n in z.namelist()) and n2 == 4


@needs_template
def test_workbook_summary_reads_by_label():
    summ = workbook_summary(TEMPLATE)
    assert "total_before" in summ and "volume_label" in summ and "1 page results - 1 Target" in summ["sheets"]


@needs_template
def test_finish_without_print_runs_qa_and_zips(tmp_path):
    root = _mini_package(tmp_path)
    opts = FinishOptions(redact_reports=False, print_page=False, bind=False, run_qa=True,
                         reference_workbook=TEMPLATE, zip_out=str(tmp_path / "fin.zip"))
    rep = finish_package(str(root), opts)
    names = [s.name for s in rep.steps]
    assert names == ["QA checks", "QA certificate", "zip"] and rep.ok, [(s.name, s.detail) for s in rep.steps]
    assert os.path.exists(rep.zip_path)
    logs = [f for f in os.listdir(root / "Notes") if f.startswith("QA Checks")]
    assert logs and "Verified" in (root / "Notes" / logs[0]).read_text()
    assert rep.certificate and os.path.exists(rep.certificate) and rep.certificate.endswith(".docx")


def test_finish_reports_missing_workbook(tmp_path):
    root = _mini_package(tmp_path, with_workbook=False) if os.path.exists(TEMPLATE) else tmp_path / "empty"
    root.mkdir(exist_ok=True)
    rep = finish_package(str(root), FinishOptions(redact_reports=False, print_page=False, bind=False))
    assert not rep.ok and rep.steps[0].name == "discover"
