"""Benchmark plumbing tests: primary-workbook selection must pick the
largest *Evaluation Workbook* per WO and never a fiche-report sibling
(real case: 41000073407, whose evaluation workbook exceeded the download
transport limit and only the fiche .xlsm landed on disk)."""
import os

from safety_eval.bench import _primary_workbooks


def _touch(dirpath, name, size):
    with open(os.path.join(dirpath, name), "wb") as fh:
        fh.write(b"\0" * size)


def test_primary_picks_largest_eval_workbook(tmp_path):
    d = str(tmp_path)
    _touch(d, "41000000001__Intersection Evaluation Workbook - A (1 of 2).xlsx", 100)
    _touch(d, "41000000001__Intersection Evaluation Workbook - A (2 of 2).xlsx", 300)
    _touch(d, "41000000001__M210813002 Fiche Report.xlsm", 900)
    _touch(d, "41000000002__221223020CA_Fiche Report.xlsm", 500)
    _touch(d, "41000000003__Section Evaluation Workbook - B.xlsx", 50)
    # a blank scope-package template dropped in the folder must be ignored
    # even though it is the largest "evaluation workbook" file present
    _touch(d, "41000000003__Section Evaluation Workbook - 2023-12-04.xlsx", 999)
    _touch(d, "notes.txt", 10)

    primaries = _primary_workbooks(d)
    assert primaries["41000000001"].endswith("(2 of 2).xlsx")
    # fiche-only WO gets no primary at all (reported as missing downstream)
    assert "41000000002" not in primaries
    assert primaries["41000000003"].endswith("Section Evaluation Workbook - B.xlsx")


def test_blank_template_only_wo_has_no_primary(tmp_path):
    """A WO whose only workbook-named file is the blank 2023-12-04 template
    (real deliverable was over the download cap) must report NO primary, so
    it is counted missing rather than scored on empty content."""
    d = str(tmp_path)
    _touch(d, "41000073368__05-18-51357 Intersection Evaluation Workbook - "
              "2023-12-04.xlsx", 458357)
    assert "41000073368" not in _primary_workbooks(d)
